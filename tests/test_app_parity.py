"""The app shows what the analyses compute: each number on a page equals the analysis API's.

P6 Check Schedule stays the reference for the calculations themselves (test_p6_check_schedule.py,
`xerscope check --expect`); this file proves the pages add nothing to them: no recomputation, no
lost parameter (baseline, update, standard), no stale cache. The expected values are built here
from the same API the CLI uses, with the page's display format.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from xerkit import done, todo, xer_text

import xerscope
from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.analysis.checks import results_frame, run_metric
from xerscope.analysis.evm import bei_series, evm_series
from xerscope.analysis.explain import fmt_value
from xerscope.analysis.progress import ppc_series
from xerscope.app.state import BL_NONE, BL_PLANNED
from xerscope.app.ui import status_label

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
STANDARDS = builtin_standards()


def _tick_all(at):
    """Nothing is read until ticked: tick every file of the folder."""
    for box in (box for box in at.sidebar.checkbox if box.key.startswith("read:")):
        box.check()
    return at.run()


@pytest.fixture(scope="module")
def app(sample_dir):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        yield _tick_all(AppTest.from_file(APP, default_timeout=180).run())


def _run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def _metrics(at) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _number(value) -> float:
    """A result's value, None (no population) as NaN like the series."""
    return float("nan") if value is None else float(value)


def _baseline(store, choice: str, snapshot):
    if choice == BL_NONE:
        return None
    if choice == BL_PLANNED:
        return Baseline.planned(snapshot)
    return Baseline.from_snapshot(store.by_label(choice))


@pytest.mark.parametrize("bl_choice", ["first update", BL_PLANNED, BL_NONE])
@pytest.mark.parametrize("standard_id", sorted(STANDARDS))
def test_health_table_equals_run_standard(app, store, standard_id, bl_choice):
    """Status, value, counts and items listed of every check, on the first and the latest update."""
    choice = store.labels[0] if bl_choice == "first update" else bl_choice
    app.sidebar.selectbox(key="bl_choice").set_value(choice)
    _run(app)
    app.switch_page("views/health.py")
    _run(app)
    app.get("button_group")[0].set_value(standard_id)
    _run(app)
    standard = STANDARDS[standard_id]
    for label in (store.labels[0], store.labels[-1]):
        app.selectbox(key="health_snap").set_value(label)
        _run(app)
        snapshot = store.by_label(label)
        results = run_standard(standard, AnalysisContext(snapshot, store, _baseline(store, choice, snapshot)))
        columns = ["status", "result", "count", "flagged"]
        expected = results_frame(results).assign(flagged=[len(result.flagged) for result in results])
        expected["status"] = expected["status"].map(status_label)
        shown = app.dataframe[0].value
        pd.testing.assert_frame_equal(
            shown[columns].reset_index(drop=True).astype({"flagged": int}),
            expected[columns].astype({"flagged": int}),
            check_dtype=False,
            obj=f"health table {label}",
        )
        assert list(shown["id"]) == list(expected["id"])


def test_earned_value_kpis_equal_evm_series(app, store):
    """EV %, PV %, SPI, SV, BEI and EAC of every update; BEI is the value of the Health checks P6-13 / DCMA-14."""
    app.sidebar.selectbox(key="bl_choice").set_value(store.labels[0])
    _run(app)
    app.switch_page("views/earned_value.py")
    _run(app)
    assert "SPI" not in _metrics(app)  # Costs off by default: no cost card
    app.sidebar.checkbox(key="costs").set_value(True)
    _run(app)
    baseline = Baseline.from_snapshot(store.first)
    series = evm_series(store, baseline)
    bei_metrics = {"P6": STANDARDS["P6"]["P6-13"], "DCMA": STANDARDS["DCMA"]["DCMA-14"]}
    bei = bei_series(store, bei_metrics, lambda _snapshot: baseline).set_index("data_date")
    for snapshot in store:
        app.selectbox(key="ev_snap").set_value(snapshot.label)
        _run(app)
        row = series[series["data_date"] == snapshot.data_date].iloc[-1]
        context = AnalysisContext(snapshot, store, baseline)
        health_bei = [_number(run_metric(metric, context).value) for metric in bei_metrics.values()]
        assert list(bei.loc[snapshot.data_date, ["bei_p6", "bei_dcma"]]) == pytest.approx(health_bei, nan_ok=True)
        shown = _metrics(app)
        assert shown["Percent complete"] == f"{row['ev_pct']:.1f} %", snapshot.label
        assert shown["Percent scheduled"] == f"{row['pv_pct']:.1f} %", snapshot.label
        expected_cost_spi = "n/a — no cost in the baseline" if pd.isna(row["spi_cost"]) else f"{row['spi_cost']:.3f}"
        assert shown["SPI"] == expected_cost_spi, snapshot.label
        assert shown["SPI (labor units)"] == ("–" if pd.isna(row["spi"]) else f"{row['spi']:.3f}"), snapshot.label
        assert shown["SV"] == f"{row['sv_hr']:+,.0f} h", snapshot.label
        assert shown["BEI (P6 / DCMA)"] == " / ".join(
            "–" if pd.isna(value) else f"{value:.2f}" for value in health_bei
        ), snapshot.label
        assert shown["EAC"] == f"{row['eac_hr']:,.0f} h", snapshot.label


@pytest.mark.parametrize("with_milestones", [True, False])
def test_ppc_kpis_equal_ppc_series(app, store, with_milestones):
    """Committed, finished and PPC of every week: the KPI row and the chart's series agree."""
    app.switch_page("views/ppc.py")
    _run(app)
    next(toggle for toggle in app.toggle if toggle.label == "Include milestones").set_value(with_milestones)
    _run(app)
    series = ppc_series(store, with_milestones).set_index("snapshot_idx")
    for index, label in enumerate(store.labels[1:], start=1):
        app.selectbox(key="ppc_week").set_value(label)
        _run(app)
        row, shown = series.loc[index], _metrics(app)
        assert int(shown["Committed"]) == row["committed"], label
        assert int(shown["Finished as committed"]) == row["completed"], label
        assert shown["PPC this week"] == ("–" if pd.isna(row["ppc"]) else f"{row['ppc']:.0f} %"), label


def test_ppc_leaves_a_deleted_commitment_out(tmp_path, monkeypatch):
    """W-1 commits A, B, C (forecast to finish before W's data date). W: A complete, B open,
    C deleted. A deleted activity is a scope change, not a miss: 1 finished / 2 committed = 50 %."""
    week_1 = [todo(code, early_end_date="2026-03-06 17:00") for code in ("A", "B", "C")]
    week_2 = [done("A", act_end_date="2026-03-06 17:00"), todo("B", early_start_date="2026-03-09 08:00")]
    (tmp_path / "w1.xer").write_text(xer_text(week_1, data_date="2026-03-02 08:00"))
    (tmp_path / "w2.xer").write_text(xer_text(week_2, data_date="2026-03-09 08:00"))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = _tick_all(AppTest.from_file(APP, default_timeout=120).run())
    assert not at.exception, [e.value for e in at.exception]
    at.switch_page("views/ppc.py")
    _run(at)
    shown = _metrics(at)
    assert (shown["Committed"], shown["Finished as committed"], shown["PPC this week"]) == ("2", "1", "50 %")


def test_overview_kpis_equal_store_summary(app, store):
    app.switch_page("views/overview.py")
    _run(app)
    last, before = store.summary.iloc[-1], store.summary.iloc[-2]
    shown = _metrics(app)
    assert shown["Activities complete"] == f"{int(last['complete'])} / {int(last['activities'])}"
    assert int(shown["Critical activities"]) == int(last["critical"])
    critical = next(metric for metric in app.metric if metric.label == "Critical activities")
    assert critical.delta == f"{int(last['critical'] - before['critical']):+d} this week"


def test_debug_page_shows_the_options_comparisons_and_targets_as_computed(app, store):
    """Block 1 = ``Options.from_snapshot``, block 3 = the rows of ``compare_with_stored`` that
    disagree, block 4 = the targets of standards/p6.toml, on the latest update."""
    from xerscope.analysis.cpm import Options, compare_with_stored

    app.switch_page("views/debug.py")
    _run(app)
    snapshot = store.latest
    frames = [frame.value for frame in app.dataframe]
    options = next(frame for frame in frames if "origin" in frame).set_index("option")["applied"]
    expected = Options.from_snapshot(snapshot)
    for name in ("float_type", "progressed", "lag_calendar", "use_expected_finish", "open_critical"):
        assert options[name] == str(getattr(expected, name)), name
    comparison = compare_with_stored(snapshot)
    disagreeing = sorted(comparison[comparison["stored"].notna() & ~comparison["agree"]]["task_code"].unique())
    listed = [frame for frame in frames if "differs" in frame and "taskrsrc_id" not in frame]
    assert (sorted(listed[0]["task_code"]) if listed else []) == disagreeing
    parameters = next(frame for frame in frames if "tab" in frame).set_index("check")
    for metric in STANDARDS["P6"].metrics:
        row = parameters.loc[f"{metric.id} · {metric.name}"]
        assert row["target"] == metric.threshold_label
        # x is read from p6.toml (limit_hours), not from a constant: 352 on P6-04/05/06, blank elsewhere
        expected_x = metric.params.get("limit_hours")
        assert (None if pd.isna(row["x_hours"]) else row["x_hours"]) == expected_x, metric.id


def _open_audit(app, standard_id: str, metric_id: str):
    app.switch_page("views/audit.py")
    _run(app)
    app.get("button_group")[0].set_value(standard_id)
    _run(app)
    app.selectbox(key=f"audit_check:{standard_id}").set_value(metric_id)
    _run(app)


def _shown_sets(app) -> dict[str, int]:
    """Tab label 'Counted (12)' -> {'Counted': 12}."""
    return {tab.label.rsplit(" (", 1)[0]: int(tab.label.rsplit("(", 1)[1].rstrip(")")) for tab in app.tabs}


@pytest.mark.parametrize("standard_id", sorted(STANDARDS))
def test_audit_page_equals_run_metric_for_every_check(app, store, standard_id):
    """Every check of every standard on the latest update, first update as baseline: the value, the
    counts and the size of each set shown are those of run_metric and audit.split."""
    from xerscope.analysis.audit import split

    app.sidebar.selectbox(key="bl_choice").set_value(store.labels[0])
    _run(app)
    snapshot = store.latest
    context = AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first))
    for metric in STANDARDS[standard_id].metrics:
        _open_audit(app, standard_id, metric.id)
        result = run_metric(metric, context)
        shown = _metrics(app)
        assert shown["Standard"] == results_frame([result]).loc[0, "result"], metric.id
        assert shown["Standard status"] == status_label(result.status), metric.id
        assert "Audit" not in shown, metric.id  # nothing changed: one result only
        sets = split(result, snapshot)
        if sets is None:
            assert not app.tabs, metric.id
            continue
        tabs = _shown_sets(app)
        assert tabs["Checked, not counted"] == len(sets.not_counted), metric.id
        if result.numerator is not None:
            assert tabs["Counted"] == result.numerator, metric.id
        if sets.excluded is not None:
            assert tabs["Excluded"] == len(sets.excluded), metric.id


def test_audit_settings_rerun_the_check_and_leave_schedule_health_alone(app, store):
    """x = 100 h on P6-06: the Audit column is run_metric with that parameter; Schedule health and the
    standard keep x = 352 h; Reset brings the standard back."""
    from xerscope.analysis.audit import with_settings

    app.sidebar.selectbox(key="bl_choice").set_value(store.labels[0])
    _run(app)
    _open_audit(app, "P6", "P6-06")
    app.number_input(key="audit:P6:P6-06:limit_hours").set_value(100.0)
    app.text_input(key="audit:P6:P6-06:target").set_value("< 10%")
    _run(app)
    metric = STANDARDS["P6"]["P6-06"]
    context = AnalysisContext(store.latest, store, Baseline.from_snapshot(store.first))
    audited = run_metric(with_settings(metric, "< 10%", {"limit_hours": 100.0}), context)
    standard = run_metric(metric, context)
    assert audited.numerator != standard.numerator  # the demo has float between 100 and 352 h
    shown = _metrics(app)
    assert shown["Audit"] == fmt_value(audited.value, "%")
    assert shown["Audit status"] == status_label(audited.status)
    assert shown["Standard"] == fmt_value(standard.value, "%")
    assert _shown_sets(app)["Counted"] == audited.numerator
    assert any("limit_hours = 100" in code.value for code in app.code)
    assert builtin_standards()["P6"]["P6-06"].params == {"limit_hours": 352}

    app.switch_page("views/health.py")
    _run(app)
    app.get("button_group")[0].set_value("P6")
    _run(app)
    app.selectbox(key="health_snap").set_value(store.labels[-1])
    _run(app)
    row = app.dataframe[0].value.set_index("id").loc["P6-06"]
    assert row["count"] == f"{standard.numerator} / {standard.denominator}"

    _open_audit(app, "P6", "P6-06")
    assert "Audit" in _metrics(app)  # the session keeps the audit settings while it lasts
    app.button(key="audit:P6:P6-06:reset").click()
    _run(app)
    assert "Audit" not in _metrics(app)


def test_audit_page_shows_the_calculation_sheet_of_a_p6_check(app, store):
    """The sheet shown is the file's text (the P6-04 sheet names its field and x)."""
    from xerscope.analysis.audit import sheet

    _open_audit(app, "P6", "P6-04")
    expected = sheet("P6", STANDARDS["P6"]["P6-04"])
    shown = [block.value for block in app.markdown if "remain_drtn_hr_cnt" in block.value]
    assert shown == [expected.strip()]


@pytest.mark.parametrize("metric_id", [m.id for m in STANDARDS["P6"].metrics])
def test_audit_funnel_equals_the_rule_steps(app, store, metric_id):
    """The step table of the Audit page is the rule's funnel: start, removed and left per step, counted."""
    app.sidebar.selectbox(key="bl_choice").set_value(store.labels[0])
    _run(app)
    _open_audit(app, "P6", metric_id)
    result = run_metric(
        STANDARDS["P6"][metric_id], AnalysisContext(store.latest, store, Baseline.from_snapshot(store.first))
    )
    shown = next(frame.value for frame in app.dataframe if "step" in frame.value.columns)
    expected = [("start", "", None, result.funnel.start)]
    expected += [(s.label, s.source, len(s.removed), s.left) for s in result.funnel.steps]
    expected += [("counted", "", None, result.numerator)]
    got = [
        (row.step, row.source, None if pd.isna(row.removed) else int(row.removed), int(row.left))
        for row in shown.itertuples()
    ]
    assert got == expected


def test_audit_lists_the_rows_a_step_removed(app, store):
    """P6-04, step 'not milestone': the table shown is the milestones the rule removed there."""
    _open_audit(app, "P6", "P6-04")
    result = run_metric(STANDARDS["P6"]["P6-04"], AnalysisContext(store.latest, store))
    removed = next(step.removed for step in result.funnel.steps if step.label == "not milestone")
    assert not removed.empty  # the demo has open milestones
    app.selectbox(key="funnel_step:P6-04").set_value("not milestone")
    _run(app)
    shown = [frame.value for frame in app.dataframe if "task_code" in frame.value.columns]
    assert any(sorted(frame["task_code"]) == sorted(removed["task_code"]) for frame in shown)
