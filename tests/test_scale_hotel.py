"""A real P6 file at scale: the pinned third-party Hotel Project.xer (4,217 activities, 11 calendars).

The demo series has 29 activities: a cap, a truncation, a quadratic loop or a slow page goes
unseen there. Here every standard (P6, DCMA, DECM, Integrity, the custom template) runs on Hotel,
and every page of the app renders it headless, each within a time bound.

What these tests prove is robustness and speed only: no exception, no rule ending in ``error``, no
error element on a page, each run under its bound. They hold no expected count: the counts of this
file come from P6 itself, in ``test_p6_check_schedule_summary_of_hotel``, once the maintainer has
read Hotel's Check Schedule report in P6 (see its docstring).

Timings measured 2026-11-27 on a 4-CPU Linux container (Python 3.13), one test at a time: loading
1.2 s; every standard 0.3 s (P6) to 2.2 s (Integrity) without baseline, 0.3 to 0.9 s with the planned
dates; pages 0.0 s (Changelog) to 4.9 s (Debug); Schedule health 0.5 to 2.6 s per standard; Audit,
every check of a standard in turn, 1.9 s (Integrity, 8 checks) to 6.7 s (custom, 14 checks). The
bounds are about five times the slowest measure of their kind, for slower CI runners.
"""

import time
from pathlib import Path

import pytest
from conftest import baseline_box, read_folder
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.analysis.standards import load_standard
from xerscope.cli import main
from xerscope.xer import load_snapshot

pytestmark = pytest.mark.slow

HOTEL = "p6viewer/Hotel Project.xer"
APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
TEMPLATE = Path(xerscope.__file__).parent / "standards" / "custom-template.toml"
PAGES = ["overview", "gantt", "tasks", "health", "audit", "changelog", "forensics", "earned_value",
         "milestones", "ppc", "export", "debug"]  # fmt: skip
PLANNED = "Planned dates in each file (target_*)"
# The P6 Check Schedule summary of Hotel, typed by the maintainer from P6 (not in the repository yet).
P6_SUMMARY = Path(__file__).parent / "reference" / "p6-check-schedule" / "Hotel Project.csv"

STANDARD_SECONDS = 12.0  # slowest measured 2.2 s
PAGE_SECONDS = 25.0  # slowest measured 4.9 s (Debug)
HEALTH_SECONDS = 13.0  # slowest measured 2.6 s (Integrity)
AUDIT_SECONDS = 35.0  # slowest measured 6.7 s (14 checks)


def every_standard():
    """The built-in standards and the template a user starts their own from."""
    return {**builtin_standards(), "CUSTOM": load_standard(TEMPLATE)}


@pytest.fixture(scope="module")
def hotel(require_reference):
    return load_snapshot(require_reference(HOTEL))


@pytest.fixture(scope="module")
def require_reference():
    """Module-scoped twin of conftest's fixture: the path of a pinned file, or a skip."""
    from conftest import REFERENCE_HINT, missing

    def get(name: str) -> Path:
        path = Path(__file__).parent / "reference" / "data" / name
        if not path.exists():
            missing("reference", REFERENCE_HINT)
        return path

    return get


@pytest.mark.oracle("property")  # holds on any file: no exception, no error shown, within the bound
@pytest.mark.parametrize("planned", [False, True], ids=["no baseline", "planned dates"])
@pytest.mark.parametrize("standard_id", ["P6", "DCMA", "DECM", "INTEGRITY", "CUSTOM"])
def test_every_check_of_every_standard_runs_on_hotel(hotel, standard_id, planned):
    standard = every_standard()[standard_id]
    baseline = Baseline.planned(hotel) if planned else None
    started = time.perf_counter()
    results = run_standard(standard, AnalysisContext(hotel, None, baseline))
    elapsed = time.perf_counter() - started
    assert [r.metric.id for r in results] == [m.id for m in standard.metrics]
    raised = [(r.metric.id, r.note) for r in results if r.status == "error"]
    assert not raised, raised
    assert elapsed < STANDARD_SECONDS, f"{standard_id}: {elapsed:.1f} s"


@pytest.fixture(scope="module")
def app(require_reference, tmp_path_factory):
    """The app on a folder holding Hotel alone, the custom template in the standards folder."""
    data = tmp_path_factory.mktemp("hotel")
    (data / "Hotel Project.xer").write_bytes(require_reference(HOTEL).read_bytes())
    standards = tmp_path_factory.mktemp("standards")
    (standards / TEMPLATE.name).write_bytes(TEMPLATE.read_bytes())
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(data))
        patch.setenv("XERSCOPE_STANDARDS", str(standards))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        yield read_folder(AppTest.from_file(APP, default_timeout=600).run())


def assert_clean(app, where: str) -> None:
    assert not app.exception, (where, [e.value for e in app.exception])
    assert not app.error, (where, [e.value for e in app.error])


def timed_run(element) -> float:
    started = time.perf_counter()
    element.run()
    return time.perf_counter() - started


@pytest.mark.oracle("property")  # holds on any file: no exception, no error shown, within the bound
def test_hotel_is_read_whole(app):
    assert app.button(key="files_button").label == "Files · 1 file · 1 project"
    assert_clean(app, "load")


@pytest.mark.oracle("property")  # holds on any file: no exception, no error shown, within the bound
@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_hotel(app, page):
    elapsed = timed_run(app.switch_page(f"views/{page}.py"))
    assert_clean(app, page)
    assert elapsed < PAGE_SECONDS, f"{page}: {elapsed:.1f} s"


@pytest.mark.oracle("property")  # holds on any file: no exception, no error shown, within the bound
@pytest.mark.parametrize("standard_id", ["P6", "DCMA", "DECM", "INTEGRITY", "CUSTOM"])
def test_schedule_health_shows_every_standard_on_hotel(app, standard_id):
    baseline_box(app).set_value(PLANNED).run()
    app.switch_page("views/health.py").run()
    elapsed = timed_run(app.get("button_group")[0].set_value(standard_id))
    assert_clean(app, standard_id)
    summary = app.dataframe[0].value
    assert list(summary["id"]) == [m.id for m in every_standard()[standard_id].metrics]
    assert "error" not in set(summary["status"].str.lower()), summary.loc[summary["status"] == "Error", "id"].tolist()
    assert elapsed < HEALTH_SECONDS, f"{standard_id}: {elapsed:.1f} s"


@pytest.mark.oracle("property")  # holds on any file: no exception, no error shown, within the bound
@pytest.mark.parametrize("standard_id", ["P6", "DCMA", "DECM", "INTEGRITY", "CUSTOM"])
def test_audit_opens_every_check_on_hotel(app, standard_id):
    app.switch_page("views/audit.py").run()
    started = time.perf_counter()
    app.get("button_group")[0].set_value(standard_id).run()
    checks = app.selectbox(key=f"audit_check:{standard_id}").options
    for check in checks:
        app.selectbox(key=f"audit_check:{standard_id}").set_value(check).run()
        assert_clean(app, f"{standard_id} {check}")
    elapsed = time.perf_counter() - started
    assert len(checks) == len(every_standard()[standard_id].metrics)
    assert elapsed < AUDIT_SECONDS, f"{standard_id}: {elapsed:.1f} s"


@pytest.mark.oracle("p6")
def test_p6_check_schedule_summary_of_hotel(require_reference):
    """The counts P6 reports for Hotel, the only exact oracle for this file.

    To make the reading: import Hotel Project.xer into P6 Professional (26.8 preferred, else 24),
    keep its data date, do not reschedule, open Tools > Check Schedule with the dialog's default
    options and x = 352 h (the values of standards/p6.toml), run it, and type the summary into
    tests/reference/p6-check-schedule/Hotel Project.csv with the columns ``id,found,total``, one line
    per check P6-01 to P6-17 (P6-10a and P6-10b on lines of their own; a line left empty is not
    compared), and name the P6 version in the commit that adds it. xerscope reads the file with the
    Project Baseline it holds, as Check Schedule does (``--baseline-in-file``).
    """
    if not P6_SUMMARY.exists():
        pytest.skip(f"P6 reading not made yet: {P6_SUMMARY.relative_to(Path(__file__).parent)}")
    hotel = str(require_reference(HOTEL))
    assert main(["check", hotel, "--standard", "P6", "--baseline-in-file", "--expect", str(P6_SUMMARY)]) == 0
