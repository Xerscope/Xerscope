"""Which baseline each page reads (docs/architecture.md, the context banner).

Health, Audit and the Gantt read the P6 Project Baseline assigned in the update's file when it holds one,
whatever the window chose for the series: P6 Check Schedule and the DCMA 14-Point Assessment define their
items on it. Earned value reads the origin of the series, the first update's baseline, which does not move
from one update to the next; its "P6 view" switch reads the update's own baseline instead, P6's Planned
Value of the week. The four weeks' window reads the plan in force each week in both positions.

The series: two updates, each holding its own baseline copy, A1 of 40 h on calendar C8 (Monday to Friday,
8 h). a.xer, status date 2026-03-02 08:00, baseline A1 03-02 08:00 to 03-06 17:00; b.xer, status date
2026-03-09 08:00, baseline A1 03-02 08:00 to 03-20 17:00. Hand values at b's status date: against a's
baseline the task is past its finish, PV = 40 h, 100 %; against b's, 5 of 15 working days elapsed,
PV = 40 × 5 / 15 = 13.3 h, 33.3 %.
"""

from pathlib import Path

import pytest
from conftest import baseline_box, read_folder
from streamlit.testing.v1 import AppTest
from test_file_baseline import _series_and_export
from xerkit import xer_text

import xerscope
from xerscope.analysis import Baseline
from xerscope.analysis.evm import earned_schedule, ev_point
from xerscope.app import ui
from xerscope.app.session import BL_EACH
from xerscope.store import SnapshotStore
from xerscope.xer import load_snapshot

pytestmark = pytest.mark.oracle("standard")

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
CHECK_PAGES = ("views/health.py", "views/audit.py", "views/gantt.py")
PERCENT_SCHEDULED = "Percent scheduled"
START = "2026-03-02 08:00"


def _update_with_baseline(data_date: str, baseline_finish: str, baseline_code: str) -> str:
    """One file: project 1 (UPD, A1 of 40 h) names project 2, its baseline copy: A1 of 40 h to ``baseline_finish``."""
    analysed = {"proj_short_name": "UPD", "sum_base_proj_id": "2", "orig_proj_id": "", "last_baseline_update_date": ""}
    copy = {
        "proj_id": "2",
        "proj_short_name": baseline_code,
        "last_recalc_date": START,
        "plan_start_date": START,
        "clndr_id": "C8",
        "orig_proj_id": "1",
    }
    tasks = [
        {"task_code": "A1", "target_work_qty": "40"},
        {
            "task_code": "A1",
            "task_id": "101",
            "proj_id": "2",
            "target_work_qty": "40",
            "early_end_date": baseline_finish,
        },
    ]
    lines = xer_text(tasks, project=analysed, data_date=data_date).splitlines()
    fields = lines[lines.index("%T\tPROJECT") + 1].split("\t")[1:]
    lines.insert(lines.index("%T\tPROJECT") + 3, "%R\t" + "\t".join(copy.get(field, "") for field in fields))
    return "\n".join(lines) + "\n"


def _app(folder, monkeypatch) -> AppTest:
    monkeypatch.setenv("XERSCOPE_DATA", str(folder))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    return read_folder(AppTest.from_file(APP, default_timeout=120).run())


@pytest.fixture
def two_baselines(tmp_path, monkeypatch) -> AppTest:
    (tmp_path / "a.xer").write_text(_update_with_baseline("2026-03-02 08:00", "2026-03-06 17:00", "BL1"))
    (tmp_path / "b.xer").write_text(_update_with_baseline("2026-03-09 08:00", "2026-03-20 17:00", "BL2"))
    return _app(tmp_path, monkeypatch)


def _on_second_update(at: AppTest, page: str) -> AppTest:
    at = at.switch_page(page).run()
    picker = next(box for box in at.selectbox if box.key.endswith("_snap"))
    picker.select(next(option for option in picker.options if option.startswith("2026-03-09")))
    at.run()
    assert not at.exception, [error.value for error in at.exception]
    return at


def _banner_label(at: AppTest) -> str:
    return at.button(key="context_banner").label.replace("\\", "")


def _baseline_used(at: AppTest) -> str:
    lines = at.button(key="context_banner").help.replace("\\", "").split("  \n")
    return next(line for line in lines if line.startswith("Baseline used for 2026-03-09: ")).split(": ", 1)[1]


def _metric(at: AppTest, label: str) -> str:
    return next(metric for metric in at.metric if metric.label == label).value


def _pv_pct_against(folder, update_name: str, baseline_name: str) -> str:
    """Percent scheduled of update ``update_name`` against the baseline copy held by ``baseline_name``."""
    update = load_snapshot(folder / update_name)
    baseline = Baseline.from_snapshot(load_snapshot(folder / baseline_name, project_id="2"))
    return f"{ev_point(update, baseline).as_row()['pv_pct']:.1f} %"


@pytest.mark.parametrize("page", CHECK_PAGES)
def test_health_audit_and_gantt_read_the_baseline_assigned_in_the_update_under_a_series_choice(
    two_baselines, tmp_path, page
):
    at = two_baselines
    first_update = next(option for option in baseline_box(at).options if option.startswith("2026-03-02"))
    baseline_box(at).select(first_update)
    at = _on_second_update(at, page)
    assert " · BL in file (assigned in this update) · " in _banner_label(at)
    assert _baseline_used(at).startswith("P6 Project Baseline in the file (BL2, ")


def test_earned_value_reads_the_origin_then_the_update_s_own_baseline_in_the_p6_view(two_baselines, tmp_path):
    """Against a's baseline (the origin) b is fully scheduled; against its own, a third. The switch moves the
    figure and the cache follows it: switched back, the figure is the one read first."""
    at = two_baselines
    assert baseline_box(at).value == BL_EACH  # both files hold their baseline: the per-file mode by default
    at = _on_second_update(at, "views/earned_value.py")
    assert " · BL series (origin of the series) · " in _banner_label(at)
    assert (
        _baseline_used(at)
        == "origin of the series (a.xer): P6 Project Baseline in the file (BL1, last update not recorded)"
    )
    against_origin = _metric(at, PERCENT_SCHEDULED)
    assert against_origin == _pv_pct_against(tmp_path, "b.xer", "a.xer") == "100.0 %"
    window_against_origin = [caption.value for caption in at.caption if caption.value.startswith("Last 4 weeks")]

    at.toggle(key="ev_p6_view").set_value(True).run()
    assert not at.exception, [error.value for error in at.exception]
    assert " · BL in file (P6 view: this update's baseline) · " in _banner_label(at)
    assert _baseline_used(at).startswith("P6 Project Baseline in the file (BL2, ")
    assert _metric(at, PERCENT_SCHEDULED) == _pv_pct_against(tmp_path, "b.xer", "b.xer") == "33.3 %"
    # the weekly window reads the plan in force each week in both positions: one entry, the same text
    assert [
        caption.value for caption in at.caption if caption.value.startswith("Last 4 weeks")
    ] == window_against_origin
    assert sum(1 for key in at.session_state["_memo"] if "evm_weekly" in key) == 1

    at.toggle(key="ev_p6_view").set_value(False).run()
    assert _metric(at, PERCENT_SCHEDULED) == against_origin


def test_the_switch_changes_nothing_under_a_series_choice(two_baselines):
    """With one baseline chosen for the series, the origin and the update's own are that choice."""
    at = two_baselines
    first_update = next(option for option in baseline_box(at).options if option.startswith("2026-03-02"))
    baseline_box(at).select(first_update)
    at = _on_second_update(at, "views/earned_value.py")
    before = _metric(at, PERCENT_SCHEDULED)
    assert " · BL update 2026-03-02 (origin of the series) · " in _banner_label(at)
    at.toggle(key="ev_p6_view").set_value(True).run()
    assert _metric(at, PERCENT_SCHEDULED) == before
    assert " · BL update 2026-03-02 (P6 view: this update's baseline) · " in _banner_label(at)


def test_a_probable_origin_keeps_the_warning_on_the_earned_value_page(tmp_path, monkeypatch):
    """a's baseline is probable (held by the versions around its project); d's own is exact. Earned value on
    d reads the origin, a's, so the warning every page gives a probable baseline stays."""
    _series_and_export(tmp_path)
    at = _app(tmp_path, monkeypatch)
    baseline_box(at, "bl_choice").select(BL_EACH)
    baseline_box(at, "bl_folder_file").select("export.xml")
    at = at.run().switch_page("views/earned_value.py").run()
    picker = next(box for box in at.selectbox if box.key == "ev_snap")
    picker.select(next(option for option in picker.options if option.startswith("2026-03-23")))
    at.run()
    assert not at.exception, [error.value for error in at.exception]
    warnings = [warning.value.replace("\\", "") for warning in at.main.warning]
    assert any(
        warning.startswith("Baseline of this update: origin of the series (a.xer): probable: ") for warning in warnings
    )
    at.toggle(key="ev_p6_view").set_value(True).run()
    assert not any("probable" in warning.value for warning in at.main.warning)


def test_on_the_demo_the_earned_value_page_reads_the_first_update_as_origin(sample_dir, monkeypatch):
    """The demo's sidebar holds the first update as the series' baseline: the page's cumulative figures are
    ``ev_point`` and ``earned_schedule`` of the update shown against ``Baseline.from_snapshot(store[0])``."""
    store = SnapshotStore.from_folder(sample_dir)
    origin = Baseline.from_snapshot(store[0])
    point, schedule = ev_point(store.latest, origin).as_row(), earned_schedule(store.latest, origin)
    at = _app(sample_dir, monkeypatch).switch_page("views/earned_value.py").run()
    assert not at.exception, [error.value for error in at.exception]
    assert _metric(at, "Percent complete") == f"{point['ev_pct']:.1f} %"
    assert _metric(at, PERCENT_SCHEDULED) == f"{point['pv_pct']:.1f} %"
    assert _metric(at, "Plan reached") == ui.fmt_date(schedule.es_date)
    updates = next(frame for frame in at.dataframe if "pv_hr" in frame.value.columns).value
    assert len(updates) == len(store)
