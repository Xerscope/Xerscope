"""Smoke test of the Streamlit UI: every page renders, key options don't crash.

Uses Streamlit's headless AppTest, so it runs the same on Linux, Windows and macOS
without a browser. It checks that pages run; test_app_parity.py checks that they show the analyses' numbers.
"""

import json
import re
from pathlib import Path

import pandas as pd
import pytest
from conftest import (
    P6_CORPUS_HINT,
    baseline_box,
    close_window,
    file_boxes,
    files_done,
    files_line,
    missing,
    open_files,
    pick_project,
    project_box,
    read_folder,
    selection,
)
from streamlit.testing.v1 import AppTest
from xerkit import active, hours, todo, with_second_project, xer_text

import xerscope
from xerscope.analysis import Baseline
from xerscope.analysis.evm import earned, evm_series
from xerscope.app import ui
from xerscope.app.state import BL_FILE, BL_PLANNED, anonymizers_built
from xerscope.csv_safe import csv_safe
from xerscope.store import SnapshotStore
from xerscope.xer import build_snapshot
from xerscope.xer.parser import parse_text

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
PAGES = [
    "views/overview.py",
    "views/gantt.py",
    "views/activity.py",
    "views/health.py",
    "views/audit.py",
    "views/changelog.py",
    "views/earned_value.py",
    "views/milestones.py",
    "views/ppc.py",
    "views/export.py",
    "views/debug.py",
]


@pytest.fixture
def app(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    return read_folder(AppTest.from_file(APP, default_timeout=120).run())


def test_files_window_opens_from_the_button_reads_on_done_and_reopens_with_the_choice(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(APP, default_timeout=120).run()
    _ok(at)
    assert not file_boxes(at) and files_line(at) == "Files · none read"
    open_files(at)
    _ok(at)
    assert len(file_boxes(at)) == 8 and at.text_input(key="files_folder").value == str(sample_dir)
    for box in file_boxes(at)[:2]:
        box.check()
    at.run()
    assert at.session_state["store"] is None  # ticking reads nothing: the files are read on Done
    files_done(at)
    _ok(at)
    assert not file_boxes(at) and not at.session_state["files_open"]  # Done closed the window
    assert files_line(at) == "Files · 2 files · 1 project"
    open_files(at)
    assert [box.value for box in file_boxes(at)] == [True, True] + [False] * 6


def test_widget_keys_do_not_show_the_folder_path(sample_dir, monkeypatch):
    # A widget key is written into the page as a CSS class (st-key-...). On the remote image the
    # folder is the server's and the visitor never sees it (_data_locked), so no key may hold it.
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "1")
    at = open_files(read_folder(AppTest.from_file(APP, default_timeout=120).run()))
    keys = [element.key for element in [*at.checkbox, *at.button, *at.expander] if element.key]
    assert len(file_boxes(at)) == len(list(sample_dir.glob("*.xer")))
    assert keys and not [key for key in keys if str(sample_dir) in key]


def test_milestone_trend_starts_on_finish_milestones_and_keeps_the_picks(app, store):
    """The page opens on the finish milestones of the latest update (critical first, at most six);
    Clear empties it; a pick survives a visit to another page."""
    from xerscope.analysis.progress import milestone_codes

    app.switch_page("views/milestones.py").run()
    _ok(app)
    picker = app.multiselect(key="mta_pick")
    latest = store.latest.activities
    finish = latest[latest["is_milestone"] & ~latest["is_start_milestone"]]
    assert picker.value and set(picker.value) <= set(finish["task_code"]) and len(picker.value) <= 6
    assert len(app.get("plotly_chart")) == 1
    app.button(key="mta_clear").click().run()
    _ok(app)
    assert app.multiselect(key="mta_pick").value == [] and not app.get("plotly_chart")
    picks = milestone_codes(store, open_only=True)[:2]
    app.multiselect(key="mta_pick").set_value(picks).run()
    _ok(app)
    assert len(app.get("plotly_chart")) == 1
    app.switch_page("views/overview.py").run()
    app.switch_page("views/milestones.py").run()
    _ok(app)
    assert app.multiselect(key="mta_pick").value == picks


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def _shown(markdown: str) -> str:
    """Text as the page shows it: file text reaches Markdown escaped (ui.md_text)."""
    return markdown.replace("\\", "")


def test_every_page_renders(app):
    _ok(app)
    for page in PAGES:
        app.switch_page(page).run()
        _ok(app)
        assert app.title, f"{page} rendered no title"


def _gantt_data(at) -> dict:
    """The Gantt component's data, as the browser receives it."""
    return json.loads(at.get("bidi_component")[0].proto.json)


def _group(at, key: str):
    """The pills or segmented control with ``key``."""
    return next(group for group in at.get("button_group") if group.key == key)


def _toggle(at, label: str, value: bool) -> None:
    next(toggle for toggle in at.toggle if toggle.label == label).set_value(value).run()
    _ok(at)


def test_gantt_wbs_choice_filters_and_options(app):
    app.switch_page("views/gantt.py").run()
    _ok(app)
    data = _gantt_data(app)
    tasks = [r for r in data["rows"] if r["kind"] == "task"]
    assert data["rows"][0]["id"] == "w:__project__" and data["open"] == ["w:__project__"]
    assert {r["code"] for r in tasks} >= {"C3020", "M9999"} and data["links"] == []
    app.selectbox(key="gantt_node").set_value("7003").run()  # demo WBS "CIV"
    _ok(app)
    data = _gantt_data(app)
    assert data["rows"][0]["id"] == "w:7003" and data["selected"] == "w:7003"
    assert {r["code"][0] for r in data["rows"] if r["kind"] == "task"} <= {"C", "M"}  # CIV only
    assert any(m.label == "Focus" and m.value == "CIV" for m in app.metric)
    _toggle(app, "Logic links", True)
    assert _gantt_data(app)["links"]
    app.multiselect[0].set_value(["Not started", "In progress", "Complete"]).run()
    assert _gantt_data(app)["open"] == ["w:7003"]  # every status ticked: nothing filtered, nothing opened
    app.multiselect[0].set_value([]).run()
    app.text_input[1].set_value("earthworks").run()  # a search opens every branch on the matches
    data = _gantt_data(app)
    assert [r["code"] for r in data["rows"] if r["kind"] == "task"] == ["C3020"]
    assert set(data["open"]) == {r["id"] for r in data["rows"] if r["kind"] == "wbs"}
    app.text_input[1].set_value("").run()
    # the Ask field, the page's first control: a sentence becomes filters, an answer and chips
    app.text_input[0].set_value("critical not started in civil works").run()
    _ok(app)
    data = _gantt_data(app)
    drawn = [r for r in data["rows"] if r["kind"] == "task"]
    assert drawn and all(r["code"][0] in "CM" and r["category"] == "Critical" for r in drawn)
    assert any(m.value.startswith(f"{len(drawn)} activities critical not started in CIV") for m in app.markdown)
    # the page is on CIV already: the funnel starts from its 8 tasks and names each step
    assert any(c.value.startswith("8 → WBS CIV · Civil works 8 → status Not started ") for c in app.caption)
    chips = _group(app, "ask_pills:critical not started in civil works")
    assert chips.value == ["Float: Critical", "Status: Not started", "WBS: CIV · Civil works"]
    chips.set_value(["Status: Not started", "WBS: CIV · Civil works"]).run()  # a chip off: its filter goes
    _ok(app)
    rows = [r for r in _gantt_data(app)["rows"] if r["kind"] == "task"]
    assert len(rows) > len(drawn) and any(r["category"] != "Critical" for r in rows)
    line = next(c.value for c in app.caption if c.value.startswith("8 → WBS CIV · Civil works 8 → status Not started "))
    assert "float Critical" not in line  # the funnel lost that step
    app.text_input[0].set_value("jalons xyzzy génie civil").run()  # a word the file does not hold is dropped
    data = _gantt_data(app)
    assert all(r["milestone"] for r in data["rows"] if r["kind"] == "task") and data["rows"][0]["id"] == "w:7003"
    assert any("« xyzzy » is in neither this file nor the lexicon" in m.value for m in app.markdown)
    app.text_input[0].set_value("commiss").run()  # a word nothing holds, close to Commissioning
    _ok(app)
    app.button(key="teach_commiss_COM · Commissioning").click().run()  # taught for the session
    _ok(app)
    assert _group(app, "ask_pills:commiss").value == ["WBS: COM · Commissioning"]
    assert app.session_state["taught"] == [("commiss", "COM · Commissioning")]
    assert app.get("download_button")[0].label.startswith("Download the 1 word(s) taught")
    app.button(key="ask_clear").click().run()  # Show all empties the field
    _ok(app)
    assert app.text_input[0].value == "" and not app.get("button_group")[0].key.startswith("ask_pills")
    _group(app, "gantt_timescale").set_value("Week").run()
    assert _gantt_data(app)["timescale"] == "week"
    app.selectbox(key="gantt_cmp").set_value("Baseline (BL)").run()
    first = app.selectbox(key="gantt_snap").options[0]
    app.selectbox(key="gantt_snap").set_value(first).run()
    _ok(app)


@pytest.mark.parametrize("std", ["P6", "DCMA", "INTEGRITY"])
@pytest.mark.parametrize("baseline", ["Planned dates in each file (target_*)", "None"])
def test_health_standards_and_baselines(app, std, baseline):
    baseline_box(app).set_value(baseline).run()
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value(std).run()  # segmented control
    _ok(app)
    assert app.dataframe[0].value["status"].notna().all()


def test_integrity_page_states_its_purpose(app):
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()
    assert not any("Integrity answers one question" in c.value for c in app.caption)
    app.get("button_group")[0].set_value("INTEGRITY").run()
    _ok(app)
    purpose = [c.value for c in app.caption if "Integrity answers one question" in c.value]
    assert purpose and "Schedule Project Log" in purpose[0] and "reschedule in P6 (F9)" in purpose[0]
    summary = app.dataframe[0].value
    assert list(summary["id"]) == [f"INT-0{n}" for n in range(1, 9)]


def test_health_lists_culprits_of_every_check(app):
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()
    _ok(app)
    summary = app.dataframe[0].value
    listed = summary.loc[summary["flagged"] > 0]
    # one table per check that flags something, holding exactly the flagged items
    tables = {e.label.split(" · ")[0].split()[-1]: e for e in app.expander if "target" in e.label}
    for _, row in listed.iterrows():
        frames = tables[row["id"]].dataframe
        assert frames and len(frames[-1].value) == row["flagged"], row["id"]


def test_health_compares_counts_typed_from_a_p6_report(app):
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()

    def report():
        return next(u for u in app.file_uploader if u.key == "report_csv_P6")

    report().set_value(("report.csv", b"id,found,total\nP6-01,99999,99999\n", "text/csv")).run()
    _ok(app)
    assert [e.value for e in app.error] == ["1 of 1 checks differ from the report"]
    compared = next(d.value for d in app.dataframe if "match" in d.value.columns)
    row = compared.iloc[0]  # xerscope's own counts, typed back as the report
    text = f"id,found,total\nP6-01,{row['found']},{row['total']}\n".encode()
    report().set_value(("report.csv", text, "text/csv")).run()
    _ok(app)
    assert not app.error and [s.value for s in app.success] == ["All 1 checks match the report"]


def test_earned_value_needs_hours_and_baseline(app):
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    assert app.metric[0].label == "Percent complete"
    baseline_box(app).set_value("None").run()
    _ok(app)
    assert any("Choose a baseline" in i.value for i in app.info)


def _costs(at, on: bool):
    at.sidebar.checkbox(key="costs").set_value(on).run()
    _ok(at)
    return at


def _caption_texts(at):
    return [c.value for c in at.caption]


def test_earned_value_shows_the_labour_units_spi_first_while_costs_are_off(app):
    """The demo schedules carry hours, no cost: the labour units index leads and no caption mentions costs."""
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    labels = [m.label for m in app.metric]
    assert "SPI" not in labels
    assert labels.index("SPI (labor units)") == labels.index("Percent scheduled") + 1
    labour = next(m for m in app.metric if m.label == "SPI (labor units)")
    assert "Schedule Performance Index - Labor Units" in labour.help
    assert not any("Costs ignored" in text for text in _caption_texts(app))


def test_earned_value_shows_the_cost_spi_first_and_the_labour_units_one_second_when_costs_are_on(app):
    """No cost in the demo schedules: the cost SPI reads n/a and the labour units index stays."""
    app.switch_page("views/earned_value.py").run()
    _costs(app, True)
    labels = [m.label for m in app.metric]
    assert labels.index("SPI") + 1 == labels.index("SPI (labor units)")
    cost = next(m for m in app.metric if m.label == "SPI")
    assert cost.value == "n/a — no cost in the baseline"
    assert "EV cost / PV cost" in cost.help and "Schedule Performance Index" in cost.help


def test_earned_value_bei_help_states_the_two_populations(app):
    """P6-13 divides by every baseline task (no 'due' step); DCMA-14 by the tasks due, a task without a
    baseline finish counted as due (fourteen_point.dcma_14_bei)."""
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    bei = next(m for m in app.metric if m.label == "BEI (P6 / DCMA)")
    assert "P6 (P6-13): completed / every baseline task" in bei.help
    assert "no baseline finish = due" in bei.help.split("DCMA (DCMA-14)")[1]


def _banner(at) -> str:
    return at.button(key="context_banner").label.replace("\\", "")


def test_earned_value_says_the_planned_dates_history_follows_the_update_shown(app, store):
    """With the planned dates as baseline, every update is measured against the planned dates of
    the update shown: the page says so, and names that update."""
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    assert not any("planned dates (`target_*`) of the update shown" in text for text in _caption_texts(app))
    baseline_box(app).set_value(BL_PLANNED)
    app.session_state["files_open"] = False
    app.run()
    _ok(app)
    legend = [text for text in _caption_texts(app) if "planned dates (`target_*`) of the update shown" in text]
    assert len(legend) == 1 and ui.md_text(store.latest.label) in legend[0]


def test_the_context_banner_states_each_setting_and_follows_its_changes(app, store):
    """Projects, data date of the update shown, baseline, EV basis, costs, files: each change shows."""
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    first = store.labels[0].split(" · ")[0]
    code = store.latest.project_code
    assert _banner(app) == (
        f"{code} · status date {ui.fmt_date(store.latest.data_date)} · BL update {first} · "
        "EV budgeted, planned dates · costs off · 8 files · 1 project"
    )
    app.selectbox(key="ev_snap").set_value(store.labels[2]).run()
    assert f"status date {ui.fmt_date(store[2].data_date)} ·" in _banner(app)
    baseline_box(app).set_value(BL_PLANNED)
    assert " · BL planned dates · " in _banner(app)
    baseline_box(app, "ev_basis").set_value("at_completion_current")
    assert " · EV at completion, current dates · " in _banner(app)
    app.session_state["files_open"] = False  # baseline_box leaves the window open
    _costs(app.run(), True)
    assert " · costs on · " in _banner(app)
    assert (
        f"Status date of the update shown: {ui.fmt_date(store[2].data_date)}" in app.button(key="context_banner").help
    )


def test_the_context_banner_counts_the_files_read_and_opens_the_window(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run(), count=3)
    _ok(at)
    assert _banner(at).endswith(" · 3 files · 1 project")
    at.button(key="context_banner").click().run()
    assert at.session_state["files_open"] and file_boxes(at)


def _costed_week(tmp_path, cost: str = "5000"):
    """A (cost 5000, 50 % complete) over Mon-Fri, data date Wednesday 08:00: PV cost 5000 x 0.4 = 2000,
    EV cost 5000 x 0.5 = 2500, SPI 1.25; the labour units index (40 h x 0.5 / 40 h x 0.4) is the same here.
    A second assignment without cost makes the count 1 of 2."""
    week = dict(
        target_start_date="2026-03-02 08:00",
        target_end_date="2026-03-06 17:00",
        early_start_date="2026-03-02 08:00",
        early_end_date="2026-03-06 17:00",
    )
    tasks = [
        active(
            "A", target_work_qty="40", remain_work_qty="20", target_drtn_hr_cnt="40", remain_drtn_hr_cnt="20", **week
        )
    ]
    assign = [
        dict(task_code="A", rsrc_id="R1", rsrc_type="RT_Labor", target_qty="40", target_cost=cost),
        dict(task_code="A", rsrc_id="R2", rsrc_type="RT_Labor", target_qty="0", target_cost="0"),
    ]
    (tmp_path / "w1.xer").write_text(xer_text(tasks, assign=assign, data_date="2026-03-04 08:00"))


def _ev_table(at):
    return next(d.value for d in at.dataframe if "measure" in d.value.columns).set_index("measure")


def test_earned_value_cost_spi_from_a_file_with_costs(tmp_path, monkeypatch):
    _costed_week(tmp_path)
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/earned_value.py").run()
    _costs(at, True)
    assert next(m for m in at.metric if m.label == "SPI").value == "1.25"
    assert not any("Costs ignored" in text for text in _caption_texts(at))
    table = _ev_table(at)
    assert table.loc["BAC cost"].iloc[-1] == "5,000.0"
    assert table.loc["PV cost"].iloc[-1].startswith("2,000.0")
    assert table.loc["EV cost"].iloc[-1].startswith("2,500.0")
    assert table.loc["SPI", "P6 column"] == "Schedule Performance Index"
    assert table.loc["SPI"].iloc[-1] == "2,500.0 / 2,000.0 = 1.25"


def test_earned_value_hides_every_cost_figure_while_costs_are_off(tmp_path, monkeypatch):
    _costed_week(tmp_path)
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/earned_value.py").run()
    _ok(at)
    labour = next(m for m in at.metric if m.label == "SPI (labor units)")
    assert labour.value == "1.25"
    assert [m.label for m in at.metric].index("SPI (labor units)") == 2
    assert (
        "Costs ignored: 1 of 2 assignments carry a cost in the file (resource prices). "
        "Turn on Costs in the sidebar to see P6's cost SPI."
    ) in _caption_texts(at)
    table = _ev_table(at)
    assert not [name for name in table.index if "cost" in name.lower() or name == "SPI"]
    for frame in (d.value for d in at.dataframe):
        assert not [c for c in frame.columns if "cost" in str(c).lower()]
        assert "SPI" not in frame.columns


def test_earned_value_hours_do_not_depend_on_the_costs_in_the_file(tmp_path):
    """Same schedule with and without prices: hours, PV, EV and SPI are the same per activity and per update."""
    results = []
    for cost in ("5000", "0"):
        _costed_week(tmp_path, cost)
        snapshot = build_snapshot(parse_text((tmp_path / "w1.xer").read_text(), source="w1.xer"))
        baseline = Baseline.from_snapshot(snapshot)
        results.append((earned(snapshot, baseline), evm_series(SnapshotStore([snapshot]), baseline)))
    columns = ["bl_labor_hr", "pv_hr", "ev_hr"]
    pd.testing.assert_frame_equal(results[0][0][columns], results[1][0][columns])
    series = ["bac_hr", "pv_hr", "ev_hr", "ac_hr", "etc_hr", "eac_hr", "spi"]
    pd.testing.assert_frame_equal(results[0][1][series], results[1][1][series])
    assert results[0][1]["ev_cost"].iloc[0] == 2500 and results[1][1]["ev_cost"].iloc[0] == 0


def test_earned_value_warns_when_a_wbs_computes_its_etc_with_a_performance_factor(tmp_path, monkeypatch):
    """Two WBS, one on remaining units and one on PF = 1: the calculation table counts 1 / 1 and
    the warning names the second."""
    wbs = [
        {
            "wbs_id": code,
            "proj_id": "1",
            "wbs_short_name": code,
            "wbs_name": code,
            "proj_node_flag": "N",
            "parent_wbs_id": "",
            "seq_num": "1",
            "ev_compute_type": "EC_Cmp_pct",
            "ev_etc_compute_type": etc,
            "ev_etc_user_value": "1",
        }
        for code, etc in (("WREM", "EE_Rem_hr"), ("WPF", "EE_PF_1"))
    ]
    labour = {"target_start_date": "2026-03-02 08:00", "target_end_date": "2026-03-13 17:00"}
    tasks = [
        todo("A", wbs_id="WREM", target_work_qty="80", remain_work_qty="80", **labour),
        todo("B", wbs_id="WPF", target_work_qty="40", remain_work_qty="40", **labour),
    ]
    (tmp_path / "w1.xer").write_text(xer_text(tasks, wbs=wbs))
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/earned_value.py").run()
    _ok(at)
    table = next(d.value for d in at.dataframe if "measure" in d.value.columns).set_index("measure")
    assert table.loc["ETC technique"].iloc[-1] == "PF = 1: 1 WBS · remaining units: 1 WBS"
    warnings = [w.value for w in at.warning if "performance factor" in w.value]
    assert len(warnings) == 1 and "1 WBS use a performance factor" in warnings[0] and "WPF" in warnings[0]
    assert "WREM" not in warnings[0]


def test_earned_value_shows_the_cpi_beside_ev_per_ac_on_baselined_work(app):
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    table = next(d.value for d in app.dataframe if "measure" in d.value.columns).set_index("measure")
    assert table.loc["CPI (labor units)", "P6 column"] == "Cost Performance Index - Labor Units"
    ev, ac, cpi = (
        float(n.replace(",", "")) for n in re.findall(r"[\d,]+\.\d+", table.loc["CPI (labor units)"].iloc[-1])
    )
    assert cpi == pytest.approx(ev / ac, abs=0.005)
    assert "not a P6 column" in table.loc["EV / AC (baselined work)", "P6 column"]


def test_ev_calculation_rows_add_up_as_shown(app):
    """The operands shown, one decimal, give the result shown to the last digit: an
    independently rounded pair could otherwise read 186,420 − 186,110 = +311."""
    app.switch_page("views/earned_value.py").run()
    for label in app.selectbox(key="ev_snap").options:
        app.selectbox(key="ev_snap").set_value(label).run()
        table = next(d.value for d in app.dataframe if "measure" in d.value.columns).set_index("measure")
        shown = table.iloc[:, -1]
        numbers = {
            measure: [float(n.replace(",", "")) for n in re.findall(r"[+-]?[\d,]+\.\d+", text)]
            for measure, text in shown.items()
        }
        ev, pv, sv = numbers["SV"]
        assert sv == pytest.approx(ev - pv, abs=0.1 + 1e-9), label
        ac, etc, eac = numbers["EAC"]
        assert eac == pytest.approx(ac + etc, abs=0.1 + 1e-9), label
        if shown["SPI (labor units)"].endswith("–"):
            continue
        ev, pv, spi = numbers["SPI (labor units)"]
        assert len(shown["SPI (labor units)"].rsplit(".", 1)[-1]) == 2  # SPI to 2 decimals, as BEI and EV / AC
        assert spi == pytest.approx(ev / pv, abs=0.005), label


def test_changelog_and_ppc_pick_weeks(app):
    app.switch_page("views/changelog.py").run()
    labels = app.selectbox(key="cl_new").options
    app.selectbox(key="cl_old").set_value(labels[3]).run()
    app.selectbox(key="cl_new").set_value(labels[4]).run()
    _ok(app)
    app.switch_page("views/ppc.py").run()
    app.selectbox(key="ppc_week").set_value(app.selectbox(key="ppc_week").options[2]).run()
    _ok(app)


def test_the_app_skips_a_file_without_a_status_date(tmp_path, monkeypatch):
    """The app's boundary: such a file never reaches the weekly pages (ppc_series copes with it
    for a SnapshotStore built in code)."""
    task = todo("A", early_end_date="2026-03-05 17:00")
    (tmp_path / "w1.xer").write_text(xer_text([task], data_date="2026-03-02 08:00"), encoding="utf-8")
    (tmp_path / "w2.xer").write_text(xer_text([task], data_date="", project={"plan_start_date": ""}), encoding="utf-8")
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/ppc.py").run()
    _ok(at)
    # messages go through ui.md_text (#156): the page shows the plain text, the element holds it escaped
    assert [e.value for e in at.error] == [
        ui.md_text("w2.xer: no status date (PROJECT.last_recalc_date); the file is skipped")
    ]


def test_empty_state_explains_what_to_do_under_the_page_title(monkeypatch):
    monkeypatch.delenv("XERSCOPE_DATA", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    _ok(at)
    assert any("xerscope sample" in i.value for i in at.info)
    assert [title.value for title in at.title] == ["Overview"]
    at.switch_page("views/debug.py").run()
    _ok(at)
    assert [title.value for title in at.title] == ["Debug"] and any("xerscope sample" in i.value for i in at.info)


def _run(data_dir, monkeypatch, baseline=None):
    monkeypatch.setenv("XERSCOPE_DATA", str(data_dir))
    if baseline is None:
        monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    else:
        monkeypatch.setenv("XERSCOPE_BASELINE", str(baseline))
    return read_folder(AppTest.from_file(APP, default_timeout=120).run())


def test_gantt_filters_by_p6_activity_code_values_or_text(app, tmp_path, monkeypatch):
    """Two steps: the code type, then values picked from the suggestions (exact, as P6's
    "equals") or text typed (every value containing it, as "contains")."""
    app.switch_page("views/gantt.py").run()
    assert not [box for box in app.selectbox if box.label == "Task code (P6 activity code)"]  # the demo has no codes

    codes = [("A", "Zone", "B1/L1"), ("B", "Zone", "B1/L2"), ("C", "Zone", "B2"), ("D", "Zone", "B1")]
    tasks = [todo(code) for code in "ABCD"]
    (tmp_path / "codes.xer").write_text(xer_text(tasks, codes=codes), encoding="utf-8")
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/gantt.py").run()
    _ok(at)
    code_type = next(box for box in at.selectbox if box.label == "Task code (P6 activity code)")
    assert code_type.value is None  # nothing picked by default
    code_type.set_value("Zone").run()
    search = at.multiselect(key="gantt_code_values:Zone")
    labels = search.options

    def shown(picks):
        search.set_value(picks).run()
        _ok(at)
        return {row["code"] for row in _gantt_data(at)["rows"] if row["kind"] == "task"}

    b1 = next(label for label in labels if label.split(" · ")[0] == "B1")  # path · description
    assert shown([b1]) == {"D"}  # picked value: exactly B1, not its sub-values L1, L2
    assert shown(["l"]) == {"A", "B"}  # typed text: values L1, L2 (case ignored)


def test_gantt_code_search_scales_to_a_thousand_values(tmp_path, monkeypatch):
    """1,000 values of one code: all offered as suggestions, and one typed text keeps every
    value containing it without ticking them one by one."""
    tasks = [todo(f"T{n:04d}") for n in range(1000)]
    codes = [(f"T{n:04d}", "Room", f"R{n:04d}") for n in range(1000)]
    (tmp_path / "rooms.xer").write_text(xer_text(tasks, codes=codes), encoding="utf-8")
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/gantt.py").run()
    next(box for box in at.selectbox if box.label == "Task code (P6 activity code)").set_value("Room").run()
    search = at.multiselect(key="gantt_code_values:Room")
    assert len(search.options) == 1000
    search.set_value(["r012"]).run()  # R0120..R0129
    _ok(at)
    assert {row["code"] for row in _gantt_data(at)["rows"] if row["kind"] == "task"} == {
        f"T{n:04d}" for n in range(120, 130)
    }


def test_one_snapshot_renders_every_page(sample_dir, tmp_path, monkeypatch):
    """Series pages (PPC, trend, earned value) need two updates; with one they say so."""
    first = sorted(sample_dir.glob("*.xer"))[0]
    (tmp_path / first.name).write_bytes(first.read_bytes())
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    for page in PAGES:
        at.switch_page(page).run()
        _ok(at)


def test_baseline_file_from_env_and_its_date_check(sample_dir, tmp_path, monkeypatch):
    files = sorted(sample_dir.glob("*.xer"))
    for f in files[:3]:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    # the first export as the baseline: read, named in the sidebar, no warning
    at = _run(tmp_path, monkeypatch, baseline=files[0])
    _ok(at)
    assert baseline_box(at).value == "Separate baseline file"
    assert any(files[0].stem in _shown(c.value) and "labor h" in c.value for c in at.sidebar.caption)
    assert not at.sidebar.warning
    # the last export as the baseline: newer than every loaded update
    at = _run(tmp_path, monkeypatch, baseline=files[-1])
    _ok(at)
    assert any("after the first update" in w.value for w in at.sidebar.warning)


def test_same_data_date_twice_is_refused(sample_dir, tmp_path, monkeypatch):
    """No series is built while two ticked files share a data date: the user unticks one."""
    files = sorted(sample_dir.glob("*.xer"))
    for f in files[:2]:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "zz-copy.xer").write_bytes(files[0].read_bytes())
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    assert any(f"{files[0].name}, zz-copy.xer" in _shown(e.value) and "Untick" in e.value for e in at.sidebar.error)
    assert files_line(at) == "Files · none read"


def test_a_file_the_model_cannot_type_is_named_and_the_others_load(sample_dir, tmp_path, monkeypatch):
    """Two TASK rows on one task_id made the model raise a pandas error that only the background
    reader caught. On the synchronous path (one ticked file, or XERSCOPE_SYNC_LOAD as here) every
    page then failed and the Files line was no longer drawn: the session could not untick the
    file. The file is now refused as unreadable, named in the sidebar, and the others load."""
    files = sorted(sample_dir.glob("*.xer"))[:2]
    for f in files:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    lines = files[0].read_bytes().decode("cp1252").split("\r\n")
    first_task = lines.index("%T\tTASK") + 2
    lines.insert(first_task, lines[first_task])
    (tmp_path / "zz-crafted.xer").write_bytes("\r\n".join(lines).encode("cp1252"))
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    assert any("zz-crafted.xer" in _shown(e.value) and "duplicate task_id" in _shown(e.value) for e in at.sidebar.error)
    assert files_line(at).startswith("Files · 2 files")


def test_folder_not_found_clears_the_data(sample_dir, monkeypatch):
    at = _run(sample_dir, monkeypatch)
    open_files(at)
    at.text_input(key="files_folder").input(str(sample_dir / "missing")).run()
    _ok(at)
    assert any("Folder not found" in e.value for e in at.error) and not file_boxes(at)
    files_done(at)
    _ok(at)
    assert at.session_state["store"] is None
    assert any("xerscope sample" in i.value for i in at.info)


def _with_baseline_file_choice(at):
    baseline_box(at).set_value(baseline_box(at).options[0]).run()
    _ok(at)
    return at


def test_locked_folder_gives_the_visitor_no_path_field_and_no_upload(sample_dir, monkeypatch):
    """Remote deployment (XERSCOPE_DATA_LOCKED): the server's folder is read, no field can point
    elsewhere and nothing can be uploaded (exports and baseline: each parsed one costs memory), so
    the window offers no separate baseline file either."""
    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    at = open_files(_with_baseline_file_choice(_run(sample_dir, monkeypatch)))
    assert "…or read a folder" in [t.label for t in at.text_input]
    assert len(at.get("file_uploader")) == 2  # exports and baseline, both in the window
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "true")
    at = _run(sample_dir, monkeypatch)
    assert BL_FILE not in baseline_box(at).options
    open_files(at)
    assert "…or read a folder" not in [t.label for t in at.text_input]
    assert len(at.get("file_uploader")) == 0
    assert len(file_boxes(at)) == 8  # the window lists the server's files only
    files_done(at)
    _ok(at)
    assert files_line(at) == "Files · 8 files · 1 project"


def test_locked_server_offers_the_baseline_file_it_names(sample_dir, monkeypatch):
    """XERSCOPE_BASELINE on a locked server: the separate file is the server's, read without upload."""
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "true")
    at = _run(sample_dir, monkeypatch, baseline=sorted(sample_dir.glob("*.xer"))[0])
    _ok(at)
    assert baseline_box(at).value == BL_FILE and not at.get("file_uploader")
    assert at.button(key="baseline_button").label == f"Baseline · {sorted(sample_dir.glob('*.xer'))[0].name}"
    assert isinstance(at.session_state["baseline"], Baseline)


def test_baseline_line_opens_the_window_on_its_section_and_the_choice_outlives_the_window(app, store):
    """The sidebar's Baseline line opens the same window, Baseline section first; a choice applied
    with Done stays once the window is closed, although its selectors are no longer drawn."""
    _ok(app)
    assert app.button(key="baseline_button").label.startswith("Baseline · ")
    baseline_box(app).set_value(BL_PLANNED)
    titles = [html.body for html in app.get("html") if html.body.startswith('<div class="xd-title">')]
    assert "Baseline" in titles[0] and "Files" in titles[1]
    files_done(app)
    _ok(app)
    assert not app.session_state["files_open"] and not [box for box in app.selectbox if box.key == "draft_bl_choice"]
    app.run()
    assert app.session_state["bl_choice"] == BL_PLANNED and app.session_state["baseline"] == BL_PLANNED
    assert app.button(key="baseline_button").label == "Baseline · planned dates"
    open_files(app)
    titles = [html.body for html in app.get("html") if html.body.startswith('<div class="xd-title">')]
    assert "Files" in titles[0] and "Baseline" in titles[1]
    assert baseline_box(app).value == BL_PLANNED


def _earned_value_metrics(at):
    return [(m.label, m.value) for m in at.metric]


def test_a_baseline_choice_closed_without_done_changes_nothing_and_done_applies_it(app, store):
    """The window's selectors are drafts: closed without Done (Esc, ✕, a click outside run
    _close_window), the baseline, its EV basis and the PV / SPI figures stay as they were."""
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    before = _earned_value_metrics(app)
    in_force = (app.session_state["bl_choice"], app.session_state["ev_basis"])
    assert before and in_force[0] == store.labels[0]
    app.button(key="baseline_button").click().run()
    app.selectbox(key="draft_bl_choice").set_value(BL_PLANNED).run()
    app.selectbox(key="draft_ev_basis").set_value("at_completion_current").run()
    assert app.selectbox(key="draft_bl_choice").value == BL_PLANNED
    assert (app.session_state["bl_choice"], app.session_state["ev_basis"]) == in_force  # a draft only
    app.session_state["files_open"] = False  # what _close_window does on dismissal
    app.run()
    _ok(app)
    assert (app.session_state["bl_choice"], app.session_state["ev_basis"]) == in_force
    assert isinstance(app.session_state["baseline"], Baseline) and _earned_value_metrics(app) == before
    app.button(key="baseline_button").click().run()
    assert app.selectbox(key="draft_bl_choice").value == in_force[0]  # the draft starts from the value in force
    app.selectbox(key="draft_bl_choice").set_value(BL_PLANNED).run()
    files_done(app)
    _ok(app)
    assert app.session_state["bl_choice"] == BL_PLANNED and app.session_state["baseline"] == BL_PLANNED
    assert _earned_value_metrics(app) != before


def test_closing_the_window_without_done_reads_nothing(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    file_boxes(at)[0].check()
    at.run()
    at.session_state["files_open"] = False  # what _close_window does on Esc or a click outside
    at.run()
    _ok(at)
    assert not file_boxes(at) and at.session_state["store"] is None
    assert files_line(at) == "Files · none read"


def test_the_window_reopened_after_esc_shows_the_folder_and_its_files(sample_dir, monkeypatch):
    """Esc leaves the folder field's key in the session state with an empty value (the browser's
    doing, which AppTest does not reproduce: written here by hand): reopened, the window shows the
    folder again, lists its files, and Select all then Done reads them."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    assert at.text_input(key="files_folder").value == str(sample_dir)
    close_window(at)
    at.session_state["files_folder"] = ""
    at.run()
    open_files(at)
    _ok(at)
    assert at.text_input(key="files_folder").value == str(sample_dir)
    count = len(list(sample_dir.glob("*.xer")))
    assert len(file_boxes(at)) == count
    _button(at, "Select all").click()
    at.run()
    files_done(at)
    _ok(at)
    assert files_line(at) == f"Files · {count} files · 1 project"


def test_a_new_session_reuses_nothing_parsed_by_another(sample_dir, monkeypatch):
    """Parsed files live in their session only: once it ends, nothing of them stays in the process."""
    from xerscope.app import state

    calls = []
    real = state.load_snapshot

    def counting(data, **kwargs):
        calls.append(kwargs.get("name"))
        return real(data, **kwargs)

    monkeypatch.setattr(state, "load_snapshot", counting)
    first = _run(sample_dir, monkeypatch)
    _ok(first)
    parsed_once = len(calls)
    assert parsed_once == 8  # the eight demo weeks
    second = _run(sample_dir, monkeypatch)  # another browser session, same files
    _ok(second)
    assert len(calls) == 2 * parsed_once


def test_folder_files_can_be_picked(sample_dir, monkeypatch):
    """No file is read until ticked; only the ticked files enter the series."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    boxes = file_boxes(at)
    assert len(boxes) == 8 and not any(box.value for box in boxes)
    assert "store" not in at.session_state or at.session_state["store"] is None
    assert any("Tick at least one file" in i.value for i in at.info)
    for box in boxes[:3]:
        box.check()
    at.run()
    files_done(at)
    _ok(at)
    assert files_line(at) == "Files · 3 files · 1 project"
    assert len(_selection(at)) == 3  # unticked files are not read at all


def test_uploaded_files_are_read_on_done_and_an_unticked_one_leaves_the_series(sample_dir, monkeypatch):
    """Uploads are read as before, once Done is pressed; reopened, the window lists them, and
    unticking one takes its snapshot out of the series."""
    for name in ("XERSCOPE_DATA", "XERSCOPE_BASELINE", "XERSCOPE_DATA_LOCKED"):
        monkeypatch.delenv(name, raising=False)
    files = sorted(sample_dir.glob("*.xer"))[:3]
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    at.file_uploader(key="files_upload").set_value([(f.name, f.read_bytes(), "text/plain") for f in files]).run()
    _ok(at)
    keep = [box for box in at.checkbox if box.key.startswith("keep:")]
    assert [_shown(box.label) for box in keep] == [f.name for f in files] and all(box.value for box in keep)
    assert at.session_state["store"] is None
    files_done(at)
    _ok(at)
    assert [s.source for s in at.session_state["store"]] == [f.name for f in files]
    open_files(at)
    keep = [box for box in at.checkbox if box.key.startswith("keep:")]
    assert [_shown(box.label) for box in keep] == [f.name for f in files]  # kept although the upload box is empty
    keep[1].uncheck()
    at.run()
    files_done(at)
    _ok(at)
    assert [s.source for s in at.session_state["store"]] == [files[0].name, files[2].name]
    assert files_line(at) == "Files · 2 files · 1 project"


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_select_all_and_clear_buttons_are_explicit_clicks(sample_dir, monkeypatch):
    """Nothing is ticked at first; "Select all" ticks every file of the folder and reads the
    series; "Clear" unticks them all and empties it."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    count = len(list(sample_dir.glob("*.xer")))
    assert len(file_boxes(at)) == count and not any(box.value for box in file_boxes(at))
    assert at.session_state["store"] is None
    _button(at, "Select all").click()
    at.run()
    _ok(at)
    assert all(box.value for box in file_boxes(at)) and len(file_boxes(at)) == count
    files_done(at)
    assert files_line(at) == f"Files · {count} files · 1 project"
    open_files(at)
    _button(at, "Clear").click()
    at.run()
    _ok(at)
    assert not any(box.value for box in file_boxes(at))
    files_done(at)
    assert at.session_state["store"] is None
    assert files_line(at) == "Files · none read"


def test_select_all_ticks_one_file_per_data_date_and_the_list_names_the_double(sample_dir, tmp_path, monkeypatch):
    """Two files of the folder share a status date: the list says which file the second doubles,
    Select all ticks the first by name only, and Done reads the series."""
    files = sorted(sample_dir.glob("*.xer"))
    for f in files[:2]:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "zz-copy.xer").write_bytes(files[0].read_bytes())
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    labels = {box.key.rsplit(":", 1)[-1]: box.label.replace("\u00a0", "") for box in file_boxes(at)}
    assert f"— same date as {files[0].name}" in labels["zz-copy.xer"]
    assert not any("same date as" in labels[f.name] for f in files[:2])
    _button(at, "Select all").click()
    at.run()
    assert {box.key.rsplit(":", 1)[-1]: box.value for box in file_boxes(at)} == {
        files[0].name: True,
        files[1].name: True,
        "zz-copy.xer": False,
    }
    files_done(at)
    _ok(at)
    assert not at.sidebar.error and files_line(at) == "Files · 2 files · 1 project"


def test_select_all_skips_unreadable_files_and_the_error_names_the_file_once(sample_dir, tmp_path, monkeypatch):
    """An unreadable file is listed but Select all leaves it unticked; ticked by hand, its error
    carries the file name once (the XerError already names its source)."""
    files = sorted(sample_dir.glob("*.xer"))
    (tmp_path / files[0].name).write_bytes(files[0].read_bytes())
    (tmp_path / "garbage.xer").write_bytes(bytes(range(256)) * 4)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    _button(at, "Select all").click()
    at.run()
    ticked = {box.key.rsplit(":", 1)[-1]: box.value for box in file_boxes(at)}
    assert ticked == {files[0].name: True, "garbage.xer": False}
    next(box for box in file_boxes(at) if box.key.endswith("garbage.xer")).check()
    files_done(at)
    _ok(at)
    (error,) = [e.value for e in at.sidebar.error]
    assert error.startswith("garbage.xer: ") and error.count("garbage.xer") == 1
    assert files_line(at) == "Files · 1 file · 1 project"


@pytest.fixture
def renamed_project(tmp_path):
    """Week 1 holds project NEW plus a second project OLD; week 2 holds NEW only."""
    tasks = [{"task_code": c} for c in ("A1", "A2", "A3")]
    week1 = xer_text(tasks, data_date="2026-03-02 08:00", project={"proj_short_name": "NEW"})
    (tmp_path / "w1.xer").write_text(with_second_project(week1, "OLD", ["A1", "A2"], "2026-03-02 08:00"))
    (tmp_path / "w2.xer").write_text(xer_text(tasks, data_date="2026-03-09 08:00", project={"proj_short_name": "NEW"}))
    return tmp_path


def _pick_project(at, code: str) -> None:
    """Pick ``code`` for w1.xer, the file that holds two projects (NEW proj_id 1, OLD proj_id 2)."""
    pick_project(at, "w1.xer", {"NEW": "1", "OLD": "2"}[code])


def test_project_choice_applies_to_the_files_that_hold_it(renamed_project, monkeypatch):
    """A project in one file only: the other files keep their own project, none is rejected."""
    at = _run(renamed_project, monkeypatch)
    _ok(at)
    _pick_project(at, "OLD")
    _ok(at)
    assert not at.sidebar.error
    store = at.session_state["store"]
    assert [s.project_code for s in store] == ["OLD", "NEW"]
    assert [len(s.activities) for s in store] == [2, 3]


def test_switching_project_recomputes_cached_tables(renamed_project, monkeypatch):
    """Analyses cached for one project are not served for another."""
    at = _run(renamed_project, monkeypatch)
    at.switch_page("views/export.py").run()
    _ok(at)
    _pick_project(at, "OLD")
    _ok(at)
    exported = [list(v["dim_snapshot"]["project"]) for k, v in at.session_state["_memo"].items() if "export" in k]
    assert ["OLD", "NEW"] in exported


def _selection(at):
    return selection(at)


def test_selection_panel_shows_each_file_its_project_and_why(renamed_project, monkeypatch):
    """w1 holds NEW (3 TASK rows) and OLD (2): NEW wins on TASK rows; w2 holds NEW only."""
    at = _run(renamed_project, monkeypatch)
    _ok(at)
    table = _selection(at).set_index("file")
    assert table.loc["w1.xer", ["project", "selected_by", "projects_in_file"]].tolist() == [
        "NEW",
        "most TASK rows",
        "NEW (3) · OLD (2)",
    ]
    assert table.loc["w2.xer", ["project", "selected_by", "data_date_from"]].tolist() == [
        "NEW",
        "only project",
        "last_recalc_date",
    ]
    _pick_project(at, "OLD")
    _ok(at)
    table = _selection(at).set_index("file")
    assert table.loc["w1.xer", ["project", "selected_by", "activities"]].tolist() == ["OLD", "chosen", 2]
    assert table.loc["w2.xer", "project"] == "NEW"


def _project_rows(at) -> dict[str, str]:
    """The window's row of each file of the series: ``<file> — **<project>** · <picked by>``."""
    rows = [m.value.replace("\\", "") for m in at.markdown if " — **" in m.value]
    return {row.split(" — ")[0]: row.split(" — ", 1)[1] for row in rows}


def test_the_window_lists_the_projects_of_a_file_that_holds_several_and_why_each_file_is_read(
    renamed_project, monkeypatch
):
    at = _run(renamed_project, monkeypatch)
    _ok(at)
    box = project_box(at, "w1.xer")
    assert box.value == "1"
    assert box.options == ["NEW · 02 Mar 2026 · 3 tasks", "OLD · 02 Mar 2026 · 2 tasks"]
    assert project_box(at, "w2.xer") is None  # one project: no list
    assert _project_rows(at) == {"w1.xer": "**NEW** · most TASK rows", "w2.xer": "**NEW** · only project"}
    assert not [box for box in at.sidebar.selectbox if box.label == "Project"]  # no project picker for all files


def test_a_project_picked_in_the_window_applies_on_done_only(renamed_project, monkeypatch):
    at = _run(renamed_project, monkeypatch)
    project_box(at, "w1.xer").set_value("2").run()
    assert [s.project_code for s in at.session_state["store"]] == ["NEW", "NEW"]  # nothing before Done
    close_window(at)  # Esc
    assert [s.project_code for s in at.session_state["store"]] == ["NEW", "NEW"]
    assert files_line(at) == "Files · 2 files · 1 project"
    assert project_box(at, "w1.xer").value == "1"  # the draft starts again from the project read
    pick_project(at, "w1.xer", "2")
    _ok(at)
    assert [s.project_code for s in at.session_state["store"]] == ["OLD", "NEW"]
    assert files_line(at) == "Files · 2 files · :orange[2 projects]"


def test_file_boxes_describe_each_file_before_it_is_read(renamed_project, monkeypatch):
    """Unticked files are described from PROJECT and TASK only: default project, data date,
    projects in the file; none of them is parsed into a snapshot."""
    monkeypatch.setenv("XERSCOPE_DATA", str(renamed_project))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    boxes = {box.key.rsplit(":", 1)[1]: box for box in file_boxes(at)}
    # the project's number of tasks on the label: the project info reads without opening the help
    assert _shown(boxes["w1.xer"].label) == "w1.xer — NEW · 02 Mar 2026 · 3 tasks · 2 projects"
    assert _shown(boxes["w2.xer"].label).startswith("w2.xer — NEW · 09 Mar 2026 · ") and boxes["w2.xer"].label.endswith(
        " tasks"
    )
    assert "NEW (3) · OLD (2)" in boxes["w1.xer"].help and "most TASK rows" in boxes["w1.xer"].help
    assert "from last_recalc_date" in boxes["w2.xer"].help
    assert "_parsed" not in at.session_state or not at.session_state["_parsed"]


def test_unreadable_file_is_named_in_the_picker(tmp_path, monkeypatch):
    (tmp_path / "broken.xer").write_text("ERMHDR\t23.12\t2026-03-02\n%T\tPROJECT\n%F\tproj_id\n%R\t1\n")
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    (box,) = file_boxes(at)
    assert _shown(box.label) == "broken.xer — unreadable" and "TASK table missing" in box.help


@pytest.fixture
def downloads(monkeypatch):
    """Every file the app hands to a download button, by its media id (AppTest keeps them in memory)."""
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

    saved: dict[str, bytes] = {}
    real = MemoryMediaFileStorage.load_and_get_id

    def keep(self, path_or_data, mimetype, kind, filename=None):
        file_id = real(self, path_or_data, mimetype, kind, filename)
        saved[file_id] = self._files_by_id[file_id].content
        return file_id

    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", keep)
    return saved


def _download(at, downloads: dict[str, bytes], label: str) -> bytes:
    button = next(b for b in at.get("download_button") if b.proto.label == label)
    return downloads[button.proto.url.rsplit("/", 1)[-1].split(".")[0]]


def test_flagged_lists_and_xer_leave_the_app_anonymised_only(app, store, downloads):
    """No download names an activity of the loaded files; the lists and the XER extract share the new IDs."""
    import io
    import zipfile

    import pandas as pd

    from xerscope.xer import load_snapshot

    originals = set(store.history["task_code"]) | set(store.history["task_name"])
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()
    _ok(app)
    assert [b.proto.label for b in app.get("download_button")] == ["Download the template"]  # nothing before Prepare
    next(b for b in app.button if b.label == "Prepare anonymized downloads").click().run()
    _ok(app)
    flagged = pd.read_csv(
        io.BytesIO(_download(app, downloads, "All flagged items (CSV) · anonymized")), encoding="utf-8-sig"
    )
    assert not set(flagged.astype(str).to_numpy().ravel()) & originals
    codes = pd.concat([flagged[column].dropna() for column in ("task_code", "pred_code", "succ_code")])
    assert len(codes) and codes.str.fullmatch(r"XA[0-9A-F]{12}").all()

    app.switch_page("views/export.py").run()
    next(b for b in app.button if b.label == "Build anonymized extract").click().run()
    _ok(app)
    with zipfile.ZipFile(io.BytesIO(_download(app, downloads, "Download anonymized XER (.zip)"))) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    assert len(files) == len(store)
    for name, data in files.items():
        text = data.decode("utf-8")
        assert not [value for value in originals if len(value) >= 4 and value in text], name
    latest = load_snapshot(files[max(files)], name="latest.xer")
    assert set(codes) <= set(latest.activities["task_code"])


HELD_OUT_CASE = (
    Path(__file__).parent
    / "reference"
    / "data"
    / "p6-heldout"
    / "validation"
    / "held-out"
    / "H1"
    / "cases"
    / "H1-02.xer"
)


def _debug_zip(at, downloads) -> dict[str, pd.DataFrame]:
    import io
    import zipfile

    at.switch_page("views/debug.py").run()
    _ok(at)
    next(b for b in at.button if b.label == "Build diagnostic").click().run()
    _ok(at)
    assert not at.error, [e.value for e in at.error]
    with zipfile.ZipFile(io.BytesIO(_download(at, downloads, "Download diagnostic (.zip) · anonymized"))) as archive:
        return {name: pd.read_csv(io.BytesIO(archive.read(name)), encoding="utf-8-sig") for name in archive.namelist()}


def _assert_anonymised(tables: dict, store, anonymous) -> None:
    """Nothing of the originals' text in any table; Activity IDs are the extract's codes."""
    names = set(store.history["task_name"]) | set(store.history["task_code"]) | {store.latest.project_name}
    cells = {str(value) for table in tables.values() for value in table.astype(str).to_numpy().ravel()}
    assert anonymous.leaks(cells) == {}
    assert not cells & {name for name in names if len(name) >= 3}
    codes = pd.concat([table["task_code"].dropna() for table in tables.values() if "task_code" in table])
    assert codes.str.fullmatch(r"XA[0-9A-F]{12}").all()


def test_debug_diagnostic_leaves_the_app_anonymised(app, store, downloads):
    from xerscope.app.diagnostic import diagnostic_frames

    tables = _debug_zip(app, downloads)
    assert set(tables) == {f"{name}.csv" for name in diagnostic_frames(store.latest, None, _p6())} | {
        "05_guid_match.csv"
    }
    assert tables["01_options.csv"]["option"].tolist()[0] == "use_expected_finish"
    # counts only: the latest update against the baseline and the previous update, no code or GUID
    assert tables["05_guid_match.csv"]["against"].tolist() == ["baseline", "previous update"]
    _assert_anonymised(tables, store, _session_anonymizer(app))


def test_debug_calendar_detail_downloads_the_three_tables_anonymised(app, store, downloads):
    """Block 13: the calendar zip holds the summary, the weekly periods and the exceptions, no calendar name."""
    import io
    import zipfile

    app.switch_page("views/debug.py").run()
    _ok(app)
    next(b for b in app.button if b.label == "Build calendar detail").click().run()
    _ok(app)
    assert not app.error, [e.value for e in app.error]
    content = _download(app, downloads, "Download calendar detail (.zip) · anonymized")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        tables = {name: pd.read_csv(io.BytesIO(archive.read(name))) for name in archive.namelist()}
    assert set(tables) == {"13_calendar_summary.csv", "13_calendar_week.csv", "13_calendar_exceptions.csv"}
    assert "clndr_name" not in tables["13_calendar_summary.csv"].columns
    calendars = set(store.latest.work_calendars)
    assert set(tables["13_calendar_summary.csv"]["clndr_id"].astype(str)) == calendars
    assert len(tables["13_calendar_week.csv"]) == 7 * len(calendars)
    cells = {str(value) for table in tables.values() for value in table.astype(str).to_numpy().ravel()}
    assert _session_anonymizer(app).leaks(cells) == {}  # no text value of the loaded files


def test_debug_renders_a_held_out_case_with_an_expected_finish(tmp_path, monkeypatch, downloads):
    """H1-02 (corpus witness of ``expected_finish``): the page renders, block 2 lists A1170 with its
    remaining brought to 0, and the diagnostic leaves anonymised."""
    if not HELD_OUT_CASE.exists():
        missing("p6-corpus", P6_CORPUS_HINT)
    (tmp_path / HELD_OUT_CASE.name).write_bytes(HELD_OUT_CASE.read_bytes())
    at = _run(tmp_path, monkeypatch)
    tables = _debug_zip(at, downloads)
    expected = tables["02_expected_finish.csv"]
    assert len(expected) == 1 and bool(expected["remaining_set_to_0"].iloc[0])
    _assert_anonymised(tables, at.session_state["store"], _session_anonymizer(at))


def test_debug_block_6_lists_the_leveled_activities_anonymised(tmp_path, monkeypatch, downloads):
    """One activity moved by leveling: the warning, block 6 and the zip name it, the zip by its
    extract code only."""
    tasks = [
        {"task_code": "LEVELED-1", "early_start_date": "2026-03-02 08:00", "restart_date": "2026-03-09 08:00"},
        {"task_code": "PLAIN-2"},
    ]
    (tmp_path / "w1.xer").write_text(xer_text(tasks))
    at = _run(tmp_path, monkeypatch)
    tables = _debug_zip(at, downloads)
    assert any("1 open tasks have a remaining early start" in c.value for c in at.main.caption)
    leveling = tables["06_leveling.csv"]
    assert len(leveling) == 1 and leveling["task_code"].str.fullmatch(r"XA[0-9A-F]{12}").all()
    _assert_anonymised(tables, at.session_state["store"], _session_anonymizer(at))


def test_debug_page_shows_the_export_version(tmp_path, monkeypatch, downloads):
    """Block 1 lists the ERMHDR version and product with the rule applied; the anonymised zip keeps the row."""
    header = "26.8\t2026-03-02\tProject\tadmin\tPlanner\tdbxDatabaseNoName\tProject Management Cloud\tEUR"
    (tmp_path / "u1.xer").write_text(xer_text([todo("A", **hours(8))], header=header), encoding="utf-8")
    at = _run(tmp_path, monkeypatch)
    tables = _debug_zip(at, downloads)
    row = tables["01_options.csv"].set_index("option").loc["export_version"]
    assert row["raw"] == "26.8 / Project Management Cloud"
    assert row["applied"] == "collapse_early_expected_finish=False"


def test_debug_page_keeps_p6_field_names_and_its_blocks_open(app):
    """Debug columns carry the XER / analysis field names as written, to set beside P6; each block
    is keyed, so a count in its label changing with the update does not redraw it closed."""
    app.switch_page("views/debug.py").run()
    _ok(app)
    blocks = list(app.main.expander)
    assert len(blocks) == 13 and all(block.key and block.key.startswith("debug_") for block in blocks)
    assert app.main.selectbox(key="debug_snap").label == "Update"


def test_raw_labels_are_the_column_names():
    frame = pd.DataFrame({"task_code": ["A1"], "remain_drtn_hr_cnt": [8.0]})
    config = ui.column_config(frame, raw_labels=True)
    assert [config[column]["label"] for column in frame] == ["task_code", "remain_drtn_hr_cnt"]
    assert ui.column_config(frame)["task_code"]["label"] == "Task ID"  # the default stays


def _csv(data: bytes):
    import io

    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")


def _zip(data: bytes) -> dict[str, bytes]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_exports_are_anonymised_by_default_and_plain_when_switched_off(app, store, downloads):
    """The sidebar switch decides every export: on (default) new IDs and names, off the file's own."""
    originals = set(store.history["task_code"]) | set(store.history["task_name"])
    assert app.sidebar.toggle(key="anon_exports").value is True
    app.switch_page("views/gantt.py").run()
    _ok(app)
    assert not [b for b in app.get("download_button") if b.proto.label.startswith("Download CSV")]
    next(b for b in app.button if b.label == "Prepare anonymized downloads").click().run()
    _ok(app)
    gantt = _csv(_download(app, downloads, "Download CSV · anonymized"))
    assert not set(gantt.astype(str).to_numpy().ravel()) & originals
    assert gantt["task_code"].dropna().str.fullmatch(r"XA[0-9A-F]{12}").all()

    app.switch_page("views/export.py").run()
    _ok(app)
    # the Gantt's anonymizer read one update; the Power BI tables cover the series: prepared again
    next(b for b in app.button if b.label == "Prepare anonymized downloads").click().run()
    _ok(app)
    tables = _zip(_download(app, downloads, "Download PARQUET tables (.zip) · anonymized"))
    activity = pd.read_parquet(__import__("io").BytesIO(tables["fact_activity.parquet"]))
    assert not set(activity.astype(str).to_numpy().ravel()) & originals
    assert len(activity) == len(store.history)  # same rows, renamed

    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    _ok(app)
    tables = _zip(_download(app, downloads, "Download PARQUET tables (.zip)"))
    activity = pd.read_parquet(__import__("io").BytesIO(tables["fact_activity.parquet"]))
    assert set(activity["task_code"]) == set(store.history["task_code"])
    app.switch_page("views/gantt.py").run()
    _ok(app)
    assert set(_csv(_download(app, downloads, "Download CSV"))["task_code"]) <= set(store.history["task_code"])


def test_debug_diagnostic_in_plain_when_anonymous_exports_are_off(app, store, downloads):
    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    app.switch_page("views/debug.py").run()
    _ok(app)
    next(b for b in app.button if b.label == "Build diagnostic").click().run()
    _ok(app)
    tables = _zip(_download(app, downloads, "Download diagnostic (.zip)"))
    assert set(tables) >= {"01_options.csv", "04_check_parameters.csv"}


def _session_anonymizer(at):
    """The anonymizer the session built last (one per set of files read)."""
    return list(anonymizers_built(at.session_state).values())[-1]


def test_a_page_download_reads_its_update_only_and_keeps_the_series_codes(app, store, downloads):
    """Preparing the Gantt download reads the update shown, not the series; its codes are those
    of the anonymised XER extract of every file, made later in the same session."""
    app.switch_page("views/gantt.py").run()
    next(b for b in app.button if b.label == "Prepare anonymized downloads").click().run()
    _ok(app)
    shown = app.session_state["gantt_snap"]
    assert list(anonymizers_built(app.session_state)) == [frozenset({store.by_label(shown).source})]
    gantt = _csv(_download(app, downloads, "Download CSV · anonymized"))

    app.switch_page("views/export.py").run()
    next(b for b in app.button if b.label == "Build anonymized extract").click().run()
    _ok(app)
    series = _session_anonymizer(app)
    assert len(anonymizers_built(app.session_state)) == 2  # the update alone, then every file
    new_of = series.codes["A"]
    original = store.by_label(shown).activities.sort_values("task_code")["task_code"]
    shown_codes = set(gantt["task_code"])  # LOE hidden by default: a part of the update
    assert shown_codes and shown_codes <= {new_of[code] for code in original}


def _p6():
    from xerscope.analysis import builtin_standards

    return builtin_standards()["P6"]


def test_audit_downloads_follow_the_anonymous_exports_switch(app, store, downloads):
    """Audit's set downloads (Counted tab): on, new IDs after Prepare and nothing original; off, the file's own."""
    originals = set(store.history["task_code"]) | set(store.history["task_name"])
    app.sidebar.toggle(key="anon_exports").set_value(True).run()
    app.switch_page("views/audit.py").run()
    _ok(app)
    app.get("button_group")[0].set_value("P6").run()
    app.selectbox(key="audit_check:P6").set_value("P6-01").run()
    _ok(app)
    assert not [b for b in app.get("download_button") if b.proto.label == "Download CSV"]
    next(b for b in app.button if b.label == "Prepare anonymized downloads").click().run()
    _ok(app)
    counted = _csv(_download(app, downloads, "Download CSV · anonymized"))
    assert len(counted) and not set(counted.astype(str).to_numpy().ravel()) & originals

    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    _ok(app)
    counted = _csv(_download(app, downloads, "Download CSV"))
    assert set(counted["task_code"]) <= set(store.history["task_code"])


def _memo_runs(at) -> int:
    return len(at.session_state["runs"])


def _probe_script():
    import streamlit as st

    from xerscope.app.state import memo

    runs = st.session_state.setdefault("runs", [])
    memo(("probe",), lambda: runs.append(1))


@pytest.mark.parametrize("change", ["other_file", "none", "planned", "ev_basis"])
def test_memo_recomputes_when_the_baseline_changes(store, change):
    """The cache key carries the baseline's identity: a page need not add it by hand."""
    from xerscope.analysis.baseline import Baseline
    from xerscope.app.state import BL_PLANNED

    first, second = store.labels[:2]
    at = AppTest.from_function(_probe_script, default_timeout=120)
    at.session_state["ev_basis"] = "budgeted_planned"
    at.session_state["baseline"] = Baseline.from_snapshot(store.by_label(first), "budgeted_planned")
    at.run()
    at.run()
    assert _memo_runs(at) == 1  # same baseline: served from the cache
    if change == "other_file":
        at.session_state["baseline"] = Baseline.from_snapshot(store.by_label(second), "budgeted_planned")
    elif change == "none":
        at.session_state["baseline"] = None
    elif change == "planned":
        at.session_state["baseline"] = BL_PLANNED
    else:
        at.session_state["ev_basis"] = "at_completion_current"
        at.session_state["baseline"] = Baseline.from_snapshot(store.by_label(first), "at_completion_current")
    at.run()
    assert _memo_runs(at) == 2


def _check_parameters_rows(at) -> int:
    frame = next(f.value for f in at.dataframe if {"tab", "check", "target", "x_hours"} <= set(f.value.columns))
    return len(frame)


def test_debug_block_4_follows_an_uploaded_standard_with_the_builtin_id(app):
    """A session standard that takes a built-in id replaces it (state.standards): Debug must show it."""
    import dataclasses

    from xerscope.analysis.standards import builtin_standards

    app.switch_page("views/debug.py").run()
    _ok(app)
    before = _check_parameters_rows(app)
    builtin = builtin_standards()["P6"]
    app.session_state["uploaded_standards"] = {"P6": dataclasses.replace(builtin, metrics=builtin.metrics[:-1])}
    app.run()
    _ok(app)
    assert _check_parameters_rows(app) == before - 3  # P6-17 and its two Dangling options


def test_memo_recomputes_for_a_baseline_file_of_other_content(store):
    """Same name, same budget, other bytes (dates moved): not served from the cache."""
    from xerscope.analysis.baseline import Baseline

    baseline = Baseline.from_snapshot(store.by_label(store.labels[0]), "budgeted_planned")
    at = AppTest.from_function(_probe_script, default_timeout=120)
    at.session_state["ev_basis"] = "budgeted_planned"
    at.session_state["baseline"] = baseline
    at.session_state["baseline_digest"] = "a" * 64
    at.run()
    at.run()
    assert _memo_runs(at) == 1
    at.session_state["baseline_digest"] = "b" * 64
    at.run()
    assert _memo_runs(at) == 2


def test_uploading_a_standard_with_a_builtin_id_is_refused(app):
    """A built-in id is not replaceable from the page: the upload is rejected and not kept."""
    from xerscope.analysis.standards import template_text

    app.switch_page("views/health.py").run()
    text = template_text().replace('id = "CUSTOM"', 'id = "P6"', 1)
    app.file_uploader(key="std_upload").set_value(("p6.toml", text.encode(), "application/toml")).run()
    _ok(app)
    assert any("P6" in error.value and "built-in" in _shown(error.value) for error in app.error)
    assert "P6" not in app.session_state["uploaded_standards"] if "uploaded_standards" in app.session_state else True
    assert not app.success


# --- Schedule health: the sets of a check on demand, and all sets as a file ---------------------


def _open_health(at, store, standard_id="DCMA", anonymous=True):
    """Schedule health on ``standard_id``, the first update as baseline; returns (snapshot, results)."""
    from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard

    at.sidebar.toggle(key="anon_exports").set_value(anonymous).run()
    baseline_box(at).set_value(store.labels[0]).run()
    at.switch_page("views/health.py").run()
    at.get("button_group")[0].set_value(standard_id).run()
    _ok(at)
    snapshot = store.by_label(at.session_state["health_snap"])
    context = AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first))
    return snapshot, run_standard(builtin_standards()[standard_id], context)


def _pick(at, standard_id, check_id):
    at.selectbox(key=f"health_sets_check:{standard_id}").set_value(check_id).run()
    _ok(at)


def test_health_lists_no_set_until_a_check_is_picked(app, store):
    _open_health(app, store)
    picker = app.selectbox(key="health_sets_check:DCMA")
    assert picker.label == "Show the sets of" and picker.value is None
    assert picker.options[0].startswith("DCMA-01")
    assert not app.tabs
    assert not [b for b in app.get("download_button") if "CSV" in b.proto.label and "All" not in b.proto.label]


def test_health_picked_check_lists_its_counted_and_checked_sets(app, store):
    """DCMA-03: Counted = the numerator, Counted + Checked not counted = the denominator, as run_standard counts."""
    _, results = _open_health(app, store)
    result = next(r for r in results if r.metric.id == "DCMA-03")
    assert result.numerator and result.denominator > result.numerator
    _pick(app, "DCMA", "DCMA-03")
    counted, checked, excluded = app.tabs
    assert counted.label == f"Counted ({result.numerator})"
    assert len(counted.dataframe[0].value) == result.numerator
    assert len(counted.dataframe[0].value) + len(checked.dataframe[0].value) == result.denominator
    assert excluded.label.startswith("Excluded")
    key = ["pred_code", "succ_code", "type"]  # DCMA-03 counts relationships (lags)
    assert set(map(tuple, counted.dataframe[0].value[key].to_numpy())) == set(
        map(tuple, result.flagged[key].to_numpy())
    )
    app.selectbox(key="health_sets_check:DCMA").set_value(None).run()
    assert not app.tabs  # un-picking clears it


@pytest.mark.parametrize("check_id", ["DCMA-12", "DCMA-13"])
def test_health_check_without_rows_shows_its_note(app, store, check_id):
    _, results = _open_health(app, store)
    result = next(r for r in results if r.metric.id == check_id)
    assert result.checked is None and result.note
    shown = f"**Note** · {ui.md_text(result.note)}"
    before = [m.value for m in app.markdown].count(shown)  # the check's own panel shows its note too
    _pick(app, "DCMA", check_id)
    assert not app.tabs
    assert [m.value for m in app.markdown].count(shown) == before + 1


def _sets_files(at, downloads, suffix=""):
    next(b for b in at.button if b.label == "Prepare all sets").click().run()
    _ok(at)
    long = _csv(_download(at, downloads, f"All sets (CSV){suffix}"))
    archive = _zip(_download(at, downloads, f"All sets (ZIP){suffix}"))
    return long, archive


@pytest.mark.parametrize("standard_id", ["P6", "DCMA", "DECM", "INTEGRITY"])
def test_health_all_sets_file_counts_each_check_as_the_check_does(app, store, downloads, standard_id):
    """Plain export: per check, `counted` rows = numerator, `counted` + `checked` rows = denominator."""
    from xerscope.analysis.audit import split

    snapshot, results = _open_health(app, store, standard_id, anonymous=False)
    long, archive = _sets_files(app, downloads)
    assert list(long.columns[:3]) == ["check_id", "set", "note"]
    assert sorted(archive) == sorted(f"{r.metric.id}.csv" for r in results)
    for result in results:
        rows = long[long["check_id"] == result.metric.id]
        name = f"{standard_id} {result.metric.id}"
        sets = split(result, snapshot)
        if sets is None:
            assert len(rows) == 1 and rows["set"].isna().all(), name
            continue
        counted, checked = (rows["set"] == "counted").sum(), (rows["set"] == "checked").sum()
        assert counted == (result.numerator if result.numerator is not None else len(sets.counted)), name
        if result.denominator is not None:
            assert counted - sets.counted_outside + checked == result.denominator, name
        # one CSV per check holds the same rows
        assert len(_csv(archive[f"{result.metric.id}.csv"])) == len(rows), name


def test_health_screen_and_file_list_the_same_items(app, store, downloads):
    """P6-07 (relationships) and DCMA-03 (activities): each tab equals the file's rows of that set."""
    _open_health(app, store, "P6", anonymous=False)
    long, _ = _sets_files(app, downloads)
    for check_id, key in (("P6-07", ["pred_code", "succ_code", "type"]), ("P6-03", ["task_code"])):
        _pick(app, "P6", check_id)
        for tab, name in zip(app.tabs, ("counted", "checked", "excluded"), strict=True):
            shown = tab.dataframe[0].value if tab.dataframe else None
            rows = long[(long["check_id"] == check_id) & (long["set"] == name)]
            assert (0 if shown is None else len(shown)) == len(rows), (check_id, name)
            if shown is not None:
                assert sorted(map(tuple, shown[key].astype(str).to_numpy())) == sorted(
                    map(tuple, rows[key].astype(str).to_numpy())
                )


def test_health_all_sets_file_anonymised_holds_no_original_value(app, store, downloads):
    """Switch on: nothing before Prepare; then new IDs in the long file, the zip and the notes."""
    snapshot, results = _open_health(app, store, "DCMA")
    assert not [b for b in app.get("download_button") if b.proto.label.startswith("All sets")]
    long, archive = _sets_files(app, downloads, " · anonymized")
    originals = {v for v in set(store.history["task_code"]) | set(store.history["task_name"]) if isinstance(v, str)}
    files = list(store.labels)
    tables = [long, *(_csv(data) for data in archive.values())]
    for table in tables:
        cells = [cell for cell in table.astype(str).to_numpy().ravel() if isinstance(cell, str)]
        assert not set(cells) & originals
        assert not [cell for cell in cells if any(len(code) >= 5 and code in cell for code in originals)]
        assert not [
            cell for cell in cells if any(label.split(" · ")[-1].removesuffix(".xer") in cell for label in files)
        ]
    note = long.loc[long["check_id"] == "DCMA-12", "note"].iloc[0]
    assert "wd on XA" in note  # the activity is named, by its new ID
    summary = _csv(_download(app, downloads, "Summary (CSV) · anonymized"))
    assert "wd on XA" in summary.loc[summary["id"] == "DCMA-12", "note"].iloc[0]
    assert long["task_code"].dropna().str.fullmatch(r"XA[0-9A-F]{12}").all()


def test_health_summary_file_gains_the_notes(app, store, downloads):
    snapshot, results = _open_health(app, store, "DCMA", anonymous=False)
    summary = _csv(_download(app, downloads, "Summary (CSV)"))
    assert list(summary.columns[-2:]) == ["flagged", "note"]
    for result in results:
        got = summary.loc[summary["id"] == result.metric.id, "note"].iloc[0]
        expected = result.note_with_baseline  # a note starting with +/- is CSV-guarded (csv_safe)
        assert (got if isinstance(got, str) else "") == csv_safe(pd.DataFrame({"n": [expected]}))["n"].iloc[0]
    assert "BL finish" in summary.loc[summary["id"] == "DCMA-13", "note"].iloc[0]


def test_debug_costs_block_serialises_without_streamlit_fallback(tmp_path, monkeypatch):
    """TASKRSRC with a cost (rows_with_cost 1) and no PROJCOST row (rows_with_cost "absent"): the
    costs block mixes numbers and text in one column, which Arrow cannot type without a fallback."""
    from streamlit import dataframe_util

    fallbacks = []
    monkeypatch.setattr(dataframe_util._LOGGER, "info", lambda msg, *a, **k: fallbacks.append(msg))
    assign = [dict(task_code="A", rsrc_id="R1", rsrc_type="RT_Labor", target_qty="40", target_cost="5000")]
    (tmp_path / "w1.xer").write_text(xer_text([todo("A")], assign=assign))
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/debug.py").run()
    _ok(at)
    assert not [m for m in fallbacks if "Arrow" in str(m)]


def test_table_column_filters_keep_the_matching_rows(app):
    app.switch_page("views/gantt.py").run()
    _ok(app)

    def task_table():
        return next(d.value for d in app.dataframe if "task_code" in d.value.columns)

    def task_filter():
        # the Gantt task list is drawn without a key: its filters are keyed on the call site
        keys = (t for t in app.text_input if (t.key or "").startswith("filter:gantt:"))
        return next(t for t in keys if t.key.endswith(":task_code"))

    everything = task_table()
    assert len(everything) > 10  # long enough to carry filters
    task_filter().set_value("c3020").run()
    _ok(app)
    assert task_table()["task_code"].tolist() == ["C3020"]
    assert any(caption.value == f"1 of {len(everything):,} rows" for caption in app.caption)
    task_filter().set_value("").run()
    assert len(task_table()) == len(everything)


def test_gantt_panel_shows_the_picked_activity_and_follows_the_filters(app, store):
    app.switch_page("views/gantt.py").run()
    _ok(app)
    assert not any(
        {"data_date", "original_d"} <= set(d.value.columns) for d in app.dataframe
    )  # nothing picked, no panel
    app.session_state["gantt_task"] = "C3020"  # what a click on its row stores
    app.run()
    _ok(app)
    history = next(d.value for d in app.dataframe if {"data_date", "original_d"} <= set(d.value.columns))
    assert len(history) == (store.history["task_code"] == "C3020").sum()  # one row per update holding it
    assert app.selectbox(key="gantt_task_pick").value == "C3020"
    app.text_input[1].set_value("no task has this name").run()  # the Gantt search leaves C3020 out
    _ok(app)
    assert not any({"data_date", "original_d"} <= set(d.value.columns) for d in app.dataframe)
    assert any("C3020" in caption.value and "not drawn" in caption.value for caption in app.caption)


def test_gantt_a_click_in_the_chart_picks_an_activity_drawn_only(app, store):
    """A click stores the row's Activity ID (the chart's callback); the run it causes picks it when
    the chart draws it, and ignores it otherwise, keeping the activity picked before."""
    app.switch_page("views/gantt.py").run()
    app.session_state["gantt_clicked"] = "C3020"  # what the callback stores for a click on its row
    app.run()
    _ok(app)
    assert app.session_state["gantt_task"] == "C3020" and "gantt_clicked" not in app.session_state
    assert app.selectbox(key="gantt_task_pick").value == "C3020"
    app.session_state["gantt_clicked"] = "NOT-DRAWN"
    app.run()
    _ok(app)
    assert app.session_state["gantt_task"] == "C3020"


@pytest.mark.parametrize(
    ("delta", "colour", "expected"),
    [
        ("+0 this week", "inverse", "off"),  # no change: neutral, not red
        ("+0.0 wd", "normal", "off"),
        ("−0 wd", "normal", "off"),
        ("+0.051", "normal", "normal"),  # a small change is still a change
        ("+2 wd vs previous update", "inverse", "inverse"),
        ("-12.5", "normal", "normal"),
        (None, "normal", "normal"),
        (3, "normal", "normal"),
        (0, "normal", "off"),
    ],
)
def test_a_change_of_zero_is_drawn_neutral(delta, colour, expected):
    assert ui.delta_colour(delta, colour) == expected


def test_debug_block_10_compares_a_p6_export_and_keeps_the_activity_list_out_of_the_zip(app, store, downloads):
    """An export built from xerscope's own PV and EV matches it: no activity in gap; block 10 in the
    anonymized zip as four tables with no Activity ID; the activity list on screen only."""
    import io
    import zipfile

    from xerscope.analysis.evm import earned

    app.switch_page("views/debug.py").run()
    values = earned(app.session_state["store"].latest, app.session_state["baseline"])
    export = pd.DataFrame(
        {
            "Activity ID": values.index,
            "Planned Value Labor Units": values["pv_hr"],
            "Earned Value Labor Units": values["ev_hr"],
            "Schedule % Complete": values["schedule_pct"],
        }
    )
    app.file_uploader(key="debug_p6_export").set_value(
        ("p6.csv", export.to_csv(index=False).encode(), "text/csv")
    ).run()
    _ok(app)
    assert any(c.value.startswith("Tasks in gap (PV or EV)") for c in app.caption)
    next(b for b in app.button if b.label == "Build diagnostic").click().run()
    _ok(app)
    with zipfile.ZipFile(io.BytesIO(_download(app, downloads, "Download diagnostic (.zip) · anonymized"))) as archive:
        names = [n for n in archive.namelist() if n.startswith("10_")]
        causes = pd.read_csv(io.BytesIO(archive.read("10_pv_p6_gap_causes.csv")), encoding="utf-8-sig")
        text = "".join(archive.read(n).decode("utf-8-sig") for n in names)
    assert len(names) == 4 and causes.loc[0, "gap_activities"] == 0
    assert not set(store.latest.activities["task_code"]) & {c for line in text.splitlines() for c in line.split(",")}


def test_score_cards_not_computed_show_a_short_value(app):
    """A card cuts a long value with an ellipsis: the state goes in the change line instead."""
    cards = [m for m in app.metric if m.label.endswith(" score")]
    assert len(cards) == 4
    assert all(m.value == "–" and m.delta == "not computed yet" for m in cards)


def test_runtime_block_names_what_the_app_read(app):
    """Debug block 12: the fonts, the config and the package that runs, for a page that looks old."""
    app.switch_page("views/debug.py").run()
    _ok(app)
    table = ui.runtime_table()
    assert list(table["setting"])[:2] == ["Config read", "Working directory (config is read here)"]
    assert any("12 · App runtime" in e.label for e in app.expander)
    assert table.set_index("setting").loc["Config read", "value"] in ("yes", "no — start with `xerscope app`")
    assert table.set_index("setting").loc["Package", "value"] == str(Path(ui.__file__).parents[1])


def test_font_fallback_inlines_both_faces():
    """Without the config (no static folder served), the theme's two fonts come as data: URLs."""
    css = ui.font_fallback_css()
    assert css.count("data:font/woff2;base64,") == 2
    assert all(f'font-family: "{family}"' in css for family in ("Onest", "JetBrains Mono"))


def test_the_update_picked_on_one_page_is_the_update_of_every_page(app, store):
    """One choice of update for the session: picked on Schedule health, the Gantt and Earned value
    open on it; a page never visited starts on it too."""
    app.switch_page("views/health.py").run()
    older = store.labels[0]
    app.selectbox(key="health_snap").set_value(older).run()
    _ok(app)
    app.switch_page("views/gantt.py").run()
    _ok(app)
    assert app.selectbox(key="gantt_snap").value == older
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    assert app.selectbox(key="ev_snap").value == older


def test_a_check_opens_the_gantt_on_its_tasks_and_the_audit_on_itself(app):
    """Schedule health: the tasks a failed check lists open the Gantt filtered on them, on the
    update shown; Audit this check opens the Audit on that standard, check and update."""
    app.switch_page("views/health.py").run()
    _ok(app)
    app.toggle(key="health_expand").set_value(True).run()
    opener = next(b for b in app.button if b.key and b.key.startswith("gantt_P6-"))
    metric_id = opener.key.removeprefix("gantt_")
    opener.click().run()
    _ok(app)
    focus = app.session_state["gantt_focus"]
    assert focus["label"].startswith(metric_id) and focus["codes"]
    assert app.session_state["snap_choice"] == app.session_state["health_snap"]
    app.switch_page("views/gantt.py").run()
    _ok(app)
    drawn = {r["id"] for r in _gantt_data(app)["rows"] if r["kind"] == "task"}
    assert drawn == {f"a:{code}" for code in focus["codes"]}
    app.button(key="gantt_focus_clear").click().run()
    _ok(app)
    assert app.session_state["gantt_focus"] is None
    app.switch_page("views/health.py").run()
    app.toggle(key="health_expand").set_value(True).run()
    app.button(key=f"audit_{metric_id}").click().run()
    _ok(app)
    assert app.session_state["audit_std"] == "P6" and app.session_state["audit_check:P6"] == metric_id


def test_a_table_with_task_ids_offers_to_open_the_gantt(app):
    """A table with Task IDs (here the milestone slips) is selectable: a selected row's task opens
    in the Gantt. AppTest cannot select a row: the offer is checked here, the click in a browser."""
    app.switch_page("views/milestones.py").run()
    _ok(app)
    assert any(c.value.startswith("Select a row to open its task in the Gantt") for c in app.caption)


def test_debug_page_and_runtime_block_are_not_shown_on_a_locked_deployment(sample_dir, monkeypatch):
    """XERSCOPE_DATA_LOCKED (the remote stack): no Debug page unless XERSCOPE_DEBUG_PAGE=1, and even
    then not the block that names the server's folders, package path and versions."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "1")
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        at.switch_page("views/debug.py")
    monkeypatch.setenv("XERSCOPE_DEBUG_PAGE", "1")
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    at.switch_page("views/debug.py").run()
    _ok(at)
    assert not any("12 · App runtime" in e.label for e in at.expander)
    assert len([e for e in at.expander if e.key and e.key.startswith("debug_")]) == 12
    assert any("13 · Calendar detail" in e.label for e in at.expander)  # the calendar block stays on a locked instance


# --- visual defects (Playwright campaign): what AppTest can see of each fix --------------------


def test_audit_lists_every_standard_in_one_full_width_control(app):
    """The segmented control stood in a narrow column and cut its labels: it is on a row of its
    own, the Update and Check pickers under it."""
    app.switch_page("views/audit.py").run()
    _ok(app)
    control = app.get("button_group")[0]
    assert control.proto.label == "Standard"
    names = [o.content for o in control.proto.options]
    assert len(names) == 4 and "P6 Check Schedule" in names and "Integrity" in names


def test_earned_value_vac_delta_starts_with_its_sign_and_indices_read_to_two_decimals(app):
    """st.metric colours a delta by the sign it starts with: "VAC -648 h" read as a gain."""
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    metrics = {m.label: m for m in app.metric}
    assert re.fullmatch(r"[+-][\d,]+ h", metrics["EAC"].delta), metrics["EAC"].delta
    assert "VAC" in metrics["EAC"].proto.help
    assert re.fullmatch(r"\d\.\d\d", metrics["SPI (labor units)"].value)
    assert re.fullmatch(r"[+-]\d\.\d\d", metrics["SPI (labor units)"].delta)
    series = next(d.value for d in app.dataframe if "spi" in d.value.columns)
    assert series["spi"].iloc[0] == "–" and re.fullmatch(r"\d\.\d\d", series["spi"].iloc[-1])
    assert "None" not in series.astype(str).to_numpy()


def test_gantt_table_view_writes_a_dash_for_a_missing_float_and_shrinks_to_its_rows(app):
    app.switch_page("views/gantt.py").run()
    _ok(app)
    table = next(d.value for d in app.dataframe if "total_float_d" in d.value.columns)
    assert "–" in set(table["total_float_d"]) and "None" not in table.astype(str).to_numpy()
    data = _gantt_data(app)
    opened = [r for r in data["rows"] if r["parent"] is None or r["parent"] in data["open"]]
    assert len(opened) < 20 and data["height"] < 680  # a short tree takes less than the cap


def test_charts_hide_the_plotly_mode_bar(app):
    for page in ("views/overview.py", "views/earned_value.py", "views/ppc.py"):
        app.switch_page(page).run()
        _ok(app)
        for chart in app.get("plotly_chart"):
            assert json.loads(chart.proto.config) == {"displayModeBar": False}, page
            assert "hoverlabel" in json.loads(chart.proto.spec)["layout"], page


def test_health_names_each_group_once_and_offers_one_prepare_button(app):
    app.switch_page("views/health.py").run()
    _ok(app)
    titles = [m.value for m in app.markdown if m.value.startswith("##### ")]
    assert titles and len(titles) == len(set(titles)), titles
    assert [b.label for b in app.button].count("Prepare anonymized downloads") == 1


def test_changelog_offset_buttons_are_drawn_as_buttons(app):
    app.switch_page("views/changelog.py").run()
    _ok(app)
    for text in ("Previous", "4 back", "First"):
        assert app.button(key=f"cl_from_{text}").proto.type == "secondary"


def test_milestone_page_title_is_the_navigation_entry(app):
    app.switch_page("views/milestones.py").run()
    _ok(app)
    assert [t.value for t in app.title] == ["Milestone trend"]


def test_score_cards_carry_the_whole_list_of_failed_checks_in_their_help(app):
    app.switch_page("views/health.py").run()  # computes the P6 results
    app.switch_page("views/overview.py").run()
    _ok(app)
    card = next(m for m in app.metric if m.label == "P6 Check Schedule score")
    assert "evaluated" in card.delta and card.delta in card.proto.help.replace("\\", "")


def test_overview_lists_a_period_across_midnight_under_limits(tmp_path, monkeypatch):
    """A calendar period 22:00-06:00 loads (no work counted, as MPXJ) and is named under "Limits"."""
    periods = "(0||0(s|22:00|f|06:00)())(0||1(s|08:00|f|12:00)())"
    night = f"(0||CalendarData()((0||DaysOfWeek()((0||2()({periods}))))))"
    calendar = {"clndr_id": "40", "clndr_name": "", "day_hr_cnt": "4", "clndr_data": night}
    (tmp_path / "w1.xer").write_text(xer_text([todo("A")], calendars=[calendar]))
    at = _run(tmp_path, monkeypatch)
    at.switch_page("views/overview.py").run()
    _ok(at)
    assert any("crosses midnight" in w.value and "may differ from P6" in w.value for w in at.warning), [
        w.value for w in at.warning
    ]
    assert "Limits" in [s.value for s in at.subheader]
