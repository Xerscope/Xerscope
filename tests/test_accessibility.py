"""scripts/accessibility.py: which findings of axe-core fail the run, and when the job runs.

The browser run itself is the workflow accessibility.yml; nothing here opens a browser.
"""

import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from accessibility import KNOWN, judge, main, markdown  # noqa: E402

KNOWN_FOR_TESTS = {("list", "stSidebarNavItems"): "the menu's markup", ("target-size", "stMultiSelect"): "a button"}


def finding(rule, *testids, state="overview, light, desktop"):
    return {"state": state, "rule": rule, "help": f"help of {rule}", "html": "<p>", "testids": list(testids)}


MENU = finding("list", "stSidebarNavItems", "stSidebarNav", "stSidebar")
CLEAR = finding("target-size", "stMultiSelect", "stMain", state="milestones, dark, desktop")


def test_known_findings_alone_pass():
    assert judge([MENU, CLEAR, MENU], KNOWN_FOR_TESTS) == ([], [])


def test_a_known_entry_covers_the_element_under_it_too():
    """The entry names an ancestor: a li three levels under the menu's ul is the same finding."""
    deep = finding("list", "stSidebarNavLink", "stSidebarNavLinkContainer", "stSidebarNavItems")
    assert judge([deep, CLEAR], KNOWN_FOR_TESTS) == ([], [])


def test_a_known_rule_elsewhere_is_a_new_finding():
    """The same rule on a page's own list is ours: an entry is a rule and a place, not a rule."""
    ours = finding("list", "stMarkdownContainer", "stMain")
    assert judge([MENU, CLEAR, ours], KNOWN_FOR_TESTS) == ([ours], [])


def test_another_rule_in_a_known_place_is_a_new_finding():
    nameless = finding("button-name", "stMultiSelect", "stMain")
    assert judge([MENU, CLEAR, nameless], KNOWN_FOR_TESTS) == ([nameless], [])


def test_a_known_entry_no_page_shows_is_reported():
    """Streamlit fixed its menu: the entry must leave the list, or it would hide a later defect there."""
    assert judge([CLEAR], KNOWN_FOR_TESTS) == ([], [("list", "stSidebarNavItems")])


def test_summary_counts_the_known_findings_and_lists_the_others():
    ours = finding("color-contrast", "stCaptionContainer", "stSidebar", state="gantt, light, phone")
    text = markdown(48, [MENU, MENU, ours], [ours], [("target-size", "stMultiSelect")], KNOWN_FOR_TESTS)
    assert "48 states checked." in text
    assert "- `color-contrast` on gantt, light, phone: help of color-contrast. `<p>`" in text
    assert "- `list` under `stSidebarNavItems`: 2 elements. the menu's markup" in text
    assert "- `target-size` under `stMultiSelect`: 0 elements. a button" in text
    assert "- no page shows it any more, remove it from KNOWN: `target-size` under `stMultiSelect`" in text


def test_exit_code(monkeypatch, tmp_path):
    """0 only when the file is the expected axe-core build, the planted button was reported, nothing is
    new and every known entry was seen."""
    import accessibility

    axe = tmp_path / "axe.min.js"
    axe.write_bytes(b"axe")
    monkeypatch.setattr(accessibility, "AXE_SHA256", hashlib.sha256(b"axe").hexdigest())

    class App:
        def __enter__(self):
            return "http://127.0.0.1:0"

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(accessibility, "demo_app", App)
    seen = [finding(rule, testid) for rule, testid in KNOWN]
    for measured, code in [
        ((48, seen, True), 0),
        ((48, seen, False), 1),  # the planted button was not reported
        ((48, [*seen, finding("button-name", "stMain")], True), 1),  # a new finding
        ((48, seen[1:], True), 1),  # a known entry no page shows
    ]:
        monkeypatch.setattr(accessibility, "measure", lambda address, axe, measured=measured: measured)
        assert main(["--axe", str(axe)]) == code, measured
    axe.write_bytes(b"another build")  # KNOWN holds what one version reports: any other file is refused
    assert main(["--axe", str(axe)]) == 1


def test_the_accessibility_job_runs_weekly_or_by_hand_with_its_own_dependencies():
    """accessibility.yml never runs on a pull request or a push, and is no job of tests.yml (every job there
    gates the publish, tests/test_docker.py). The browser driver is in its own dependency group, so the
    `uv sync --locked` of the test jobs does not install it."""
    workflow = (ROOT / ".github" / "workflows" / "accessibility.yml").read_text(encoding="utf-8")
    on = workflow[workflow.index("\non:") : workflow.index("\nconcurrency:")]
    assert re.findall(r"^  (\w+):", on, re.M) == ["workflow_dispatch", "schedule"]
    assert re.search(r"^  schedule:\n    - cron: \"\d+ \d+ \* \* 1\"", on, re.M)
    steps = workflow[workflow.index("\njobs:") :]
    assert re.search(r"^    timeout-minutes: \d+", steps, re.M)
    order = ["uv sync --locked --group accessibility", "playwright install --with-deps chromium",
             "npm install --no-save --ignore-scripts axe-core@4.14.0", "scripts/accessibility.py --axe"]  # fmt: skip
    assert [steps.index(step) for step in order] == sorted(steps.index(step) for step in order)
    assert "accessibility" not in (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]
    assert [name.split("==")[0] for name in groups["accessibility"]] == ["playwright"]
    assert "==" in groups["accessibility"][0]  # the Chromium build installed comes with the version
    assert not any("playwright" in name for name in groups["dev"])
