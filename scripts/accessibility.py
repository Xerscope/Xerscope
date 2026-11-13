"""Accessibility of the pages as a browser renders them, against WCAG 2.2 level A and AA.

Starts the app on the demo series, opens it in a headless Chromium and runs axe-core (the rules
tagged WCAG 2.0, 2.1 and 2.2, A and AA) on the files window, on the sidebar's Files line under the
pointer and on every page, in the light and the dark theme, at a desktop and a phone width.

    uv sync --locked --group accessibility
    uv run playwright install chromium
    npm install --no-save axe-core@4.14.0
    uv run python scripts/accessibility.py --axe node_modules/axe-core/axe.min.js --markdown summary.md

axe-core is not a dependency of the repository: the file is read from where npm put it and refused
unless it is the 4.14.0 build (AXE_SHA256). KNOWN holds what that version reports; 4.12.1 does not
report the caption contrast of 4.43:1 that 4.14.0 does.

A finding is a rule and the element it names. KNOWN lists the findings that are Streamlit's own
markup, by rule and by the data-testid of the element or of one of its ancestors. The run fails
on any other finding, on a KNOWN entry no page shows any more (the list must not outlive its
reason), and when axe-core does not report a button without a name planted in the page (a run that
sees nothing proves nothing).

Not seen: what axe-core cannot decide (text over an overlay), the cells of the tables (drawn on a
canvas), the text of the charts, and the states behind a click other than the files window.
"""

import argparse
import contextlib
import hashlib
import os
import signal
import socket
import subprocess  # nosec B404
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

AXE_SHA256 = "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"  # axe-core 4.14.0, axe.min.js
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
PAGES = ["", "gantt", "activity", "health", "audit", "changelog", "earned_value", "milestones", "ppc", "export",
         "debug"]  # fmt: skip
THEMES = ["light", "dark"]
WIDTHS = {"desktop": (1440, 900), "phone": (390, 844)}

# (axe rule, data-testid of the element or of an ancestor): why it is not ours to fix
KNOWN = {
    ("list", "stSidebarNavItems"): "st.navigation with sections: the section titles are div children of the ul",
    ("listitem", "stSidebarNavItems"): "same markup: the li of a page sits under a div, not under the ul",
    ("target-size", "stMultiSelect"): "the button that clears a multiselect is 22.5 px wide (24 px asked)",
}

# The data-testid of the element each finding names and of its ancestors, nearest first. A target
# inside a shadow root is an array of selectors: the first one is its host in the page.
TESTIDS = """targets => targets.map(target => {
  const ids = [];
  for (let e = document.querySelector(Array.isArray(target) ? target[0] : target); e; e = e.parentElement)
    if (e.dataset && e.dataset.testid) ids.push(e.dataset.testid);
  return ids;
})"""


def judge(findings: list[dict], known=KNOWN) -> tuple[list[dict], list[tuple[str, str]]]:
    """(findings that no entry of ``known`` covers, entries of ``known`` that cover no finding)."""
    new, used = [], set()
    for finding in findings:
        entries = {(finding["rule"], testid) for testid in finding["testids"]} & known.keys()
        used |= entries
        if not entries:
            new.append(finding)
    return new, sorted(known.keys() - used)


def markdown(states: int, findings: list[dict], new: list[dict], gone: list[tuple[str, str]], known=KNOWN) -> str:
    lines = ["## Accessibility (axe-core, WCAG 2.2 A and AA)", "", f"{states} states checked.", ""]
    lines += ["### New findings", ""] if new else []
    lines += [f"- `{f['rule']}` on {f['state']}: {f['help']}. `{f['html']}`" for f in new]
    lines += [""] if new else []
    lines += ["### Known findings (Streamlit's own markup)", ""]
    for rule, testid in known:
        count = sum(f["rule"] == rule and testid in f["testids"] for f in findings)
        lines.append(f"- `{rule}` under `{testid}`: {count} elements. {known[rule, testid]}")
    lines += [f"- no page shows it any more, remove it from KNOWN: `{rule}` under `{testid}`" for rule, testid in gone]
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def demo_app():
    """The app on a fresh demo series, on a free local port; yields its address."""
    from xerscope.sample import generate

    with tempfile.TemporaryDirectory() as folder, socket.socket() as probe:
        generate(folder, weeks=8)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        cli = "import sys; from xerscope.cli import main; sys.exit(main())"
        command = [sys.executable, "-c", cli, "app", "--data", folder, "--port", str(port)]
        # its own process group: the command starts Streamlit as a child, which must end with it
        environment = os.environ | {"XERSCOPE_SYNC_LOAD": "1"}
        app = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment,
                               start_new_session=True)  # nosec B603  # fmt: skip
        try:
            address = f"http://127.0.0.1:{port}"
            for _ in range(60):
                with contextlib.suppress(OSError):
                    if urllib.request.urlopen(f"{address}/_stcore/health", timeout=2).status == 200:  # nosec B310
                        break
                time.sleep(1)
            else:
                raise RuntimeError("the app did not start")
            yield address
        finally:
            os.killpg(app.pid, signal.SIGTERM)
            app.wait(timeout=20)


def _settle(page) -> None:
    """Wait for the script run a click started to end, and for its fades (style.css) to finish."""
    page.wait_for_timeout(800)
    state = "document.querySelector('[data-testid=stApp]')?.getAttribute('data-test-script-state') === 'notRunning'"
    page.wait_for_function(state, timeout=120_000)
    page.wait_for_timeout(1200)


def _findings(axe: str, page, state: str) -> list[dict]:
    found = []
    page.evaluate(axe)
    run = "async tags => (await axe.run(document, {runOnly: {type: 'tag', values: tags}})).violations"
    for violation in page.evaluate(run, TAGS):
        testids = page.evaluate(TESTIDS, [node["target"][0] for node in violation["nodes"]])
        found += [
            {
                "state": state,
                "rule": violation["id"],
                "help": violation["help"],
                "html": node["html"][:160],
                "testids": ids,
            }  # fmt: skip
            for node, ids in zip(violation["nodes"], testids, strict=True)
        ]
    return found


def measure(address: str, axe: str) -> tuple[int, list[dict], bool]:
    """(states checked, findings, whether a planted button without a name was reported); ``axe`` is
    the text of axe.min.js."""
    from playwright.sync_api import sync_playwright

    findings, states = [], 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme in THEMES:
            page = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme).new_page()
            page.goto(address)
            page.wait_for_selector("[data-testid=stSidebar]", timeout=60_000)
            _settle(page)
            if theme == THEMES[0]:
                page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button id=planted></button>')")
                planted = any(f["rule"] == "button-name" and "planted" in f["html"] for f in _findings(axe, page, ""))
                page.evaluate("document.getElementById('planted').remove()")
            files_line = page.locator("[data-testid=stSidebar] [data-testid=stBaseButton-tertiary]").first
            files_line.click()
            _settle(page)
            findings += _findings(axe, page, f"files window, {theme}")
            boxes = page.locator("[role=dialog] [data-testid=stCheckbox]")
            for index in range(boxes.count()):
                if ".xer" in boxes.nth(index).inner_text():
                    boxes.nth(index).locator("label").click()
                    _settle(page)
            page.get_by_role("button", name="Done").click()
            _settle(page)
            files_line.hover()
            page.wait_for_timeout(600)
            findings += _findings(axe, page, f"Files line under the pointer, {theme}")
            states += 2
            for name in PAGES:
                page.locator(f"[data-testid=stSidebarNav] a[href$='/{name}']").first.click()
                _settle(page)
                for width, (pixels, height) in WIDTHS.items():
                    page.set_viewport_size({"width": pixels, "height": height})
                    page.wait_for_timeout(700)
                    findings += _findings(axe, page, f"{name or 'overview'}, {theme}, {width}")
                    states += 1
                page.set_viewport_size({"width": 1440, "height": 900})
                page.wait_for_timeout(500)
        browser.close()
    return states, findings, planted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--axe", type=Path, required=True, help="axe.min.js of axe-core 4.14.0")
    parser.add_argument("--markdown", type=Path, help="append a Markdown summary to this file")
    args = parser.parse_args(argv)
    axe = args.axe.read_bytes()
    if hashlib.sha256(axe).hexdigest() != AXE_SHA256:
        print(f"{args.axe} is not the axe.min.js of axe-core 4.14.0 (sha256 {AXE_SHA256})")
        return 1
    with demo_app() as address:
        states, findings, planted = measure(address, axe.decode())
    new, gone = judge(findings)
    if not planted:
        print("axe-core did not report the planted button without a name: the run proves nothing")
    for finding in new:
        print(f"new: {finding['rule']} on {finding['state']}: {finding['help']}. {finding['html']}")
    for rule, testid in gone:
        print(f"gone: {rule} under {testid}: remove it from KNOWN")
    print(f"{states} states, {len(findings)} elements named, {len(new)} new, {len(gone)} known entries gone")
    if args.markdown:
        with args.markdown.open("a", encoding="utf-8") as summary:
            summary.write(markdown(states, findings, new, gone))
    return 0 if planted and not new and not gone else 1


if __name__ == "__main__":
    sys.exit(main())
