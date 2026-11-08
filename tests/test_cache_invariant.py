"""The per-session caches (``memo``, ``metric_result``, ``hold``) are keyed on every input of what
they hold: whatever the sidebar option a session toggles, after it every page shows what a fresh
session with that option set from the start shows. A key that misses an input (the GUID link once
did, on every check) shows the value of before the toggle."""

from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest
from xerkit import active, todo, xer_text

import xerscope
from xerscope.app.state import BL_PLANNED

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
PAGES = [
    "views/overview.py",
    "views/gantt.py",
    "views/health.py",
    "views/audit.py",
    "views/changelog.py",
    "views/earned_value.py",
    "views/milestones.py",
    "views/ppc.py",
    "views/export.py",
    "views/debug.py",
]
# planned dates apart from the current ones (EV basis), labour hours, a GUID per task
PLAN = {"target_start_date": "2026-03-02 08:00", "target_end_date": "2026-03-20 17:00", "target_work_qty": "80"}
GUID_LINK_REASON = (
    "the baseline identity drops the GUID link when ev_basis=False (audit A1): checks, BEI and scores keep the "
    "unlinked values; fixed on branch fix/ev-chart-cache, commit 'Checks, BEI and Overview scores follow the "
    "GUID link option'"
)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    """Three weekly updates: A progresses, B is renumbered B2 (same GUID) in the third, C is new in
    the second."""
    out = tmp_path_factory.mktemp("cache_invariant")
    a, b = todo("A", guid="g1", **PLAN), todo("B", guid="g2", **PLAN)
    weeks = {
        "w1.xer": ("2026-03-02 08:00", [a, b]),
        "w2.xer": ("2026-03-09 08:00", [active("A", guid="g1", **PLAN), b, todo("C", guid="g3", **PLAN)]),
        "w3.xer": (
            "2026-03-16 08:00",
            [active("A", guid="g1", **PLAN), todo("B2", guid="g2", **PLAN), todo("C", guid="g3", **PLAN)],
        ),
    }
    for name, (data_date, tasks) in weeks.items():
        (out / name).write_text(xer_text(tasks, data_date=data_date))
    return out


def _session(folder, monkeypatch) -> AppTest:
    monkeypatch.setenv("XERSCOPE_DATA", str(folder))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    return read_folder(AppTest.from_file(APP, default_timeout=180).run())


def _window_option(key: str, value):
    """An option of the Baseline window: set on its draft, applied by Done, the window closed."""

    def apply(at):
        at.button(key="baseline_button").click().run()
        draft = f"draft_{key}"
        widget = at.checkbox(key=draft) if isinstance(value, bool) else at.selectbox(key=draft)
        widget.set_value(value).run()
        at.button(key="files_done").click().run()
        at.session_state["files_open"] = False
        return at.run()

    return apply


def _sidebar_option(kind: str, key: str, value):
    def apply(at):
        getattr(at.sidebar, kind)(key=key).set_value(value).run()
        return at

    return apply


OPTIONS = {
    "baseline planned dates": _window_option("bl_choice", BL_PLANNED),
    "EV basis at completion": _window_option("ev_basis", "at_completion_current"),
    "GUID link": _window_option("guid_link", True),
    "costs": _sidebar_option("checkbox", "costs", True),
    "plain exports": _sidebar_option("toggle", "anon_exports", False),
}


def _shown(at) -> dict[str, list]:
    """What each page shows: cards, tables, captions, notices and download labels."""
    seen = {}
    for page in PAGES:
        at.switch_page(page).run()
        assert not at.exception, (page, [e.value for e in at.exception])
        main = at.main
        seen[page] = [
            [(m.label, m.value) for m in main.metric],
            [frame.value.to_csv() for frame in main.dataframe],
            [c.value for c in main.caption],
            [n.value for kind in ("info", "warning", "error", "success") for n in getattr(main, kind)],
            [b.proto.label for b in main.get("download_button")],
        ]
    return seen


@pytest.mark.parametrize(
    "option",
    [
        pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=GUID_LINK_REASON))
        if name == "GUID link"
        else name
        for name in OPTIONS
    ],
)
def test_a_toggled_option_shows_what_a_fresh_session_shows(folder, monkeypatch, option):
    """Read on a second round of the pages in both sessions: a page that shows a result only once
    another page computed it (the Overview scores, after Health) shows it in both."""
    warm = _session(folder, monkeypatch)
    _shown(warm)  # every page computed once with the defaults: the caches hold their values
    _shown(OPTIONS[option](warm))
    shown_after_toggle = _shown(warm)
    fresh = OPTIONS[option](_session(folder, monkeypatch))
    _shown(fresh)
    for page, expected in _shown(fresh).items():
        assert shown_after_toggle[page] == expected, page
