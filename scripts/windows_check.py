"""The Files window in a browser: what it shows is what the server counts.

Starts the app on the demo series (like scripts/accessibility.py) and replays the scenario of the bug
AppTest cannot see, because it has no browser-side widget state: tick three files, Done, Esc on the
Baseline window the app opens by itself (the page then stops with st.stop()), reopen the window, pick
"Separate baseline file", Done. At each step the counter ("3 of 8 ticked") must equal the boxes ticked
in the page, and Done must not unload the series. Clear must disable Done while a series is loaded.
Before that, files uploaded and cancelled by Esc must leave no box in the reopened window and not be read.

    uv sync --locked --group accessibility
    uv run playwright install chromium
    uv run python scripts/windows_check.py

Exit status 0 when every check holds, 1 otherwise; each check prints one line.
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

from accessibility import demo_app, settle

TICKED = 3
UPLOAD_BOXES = "[role=dialog] .st-key-files_list_upload [data-testid=stCheckbox] input"
BOXES = "[role=dialog] .st-key-files_list_folder [data-testid=stCheckbox] input"
COUNTER = re.compile(r"(\d+) of (\d+) ticked")


def counted_and_ticked(page) -> tuple[int, int]:
    """(the number the counter says, the number of boxes ticked in the page) of the open window."""
    caption = page.locator("[role=dialog] [data-testid=stCaptionContainer]", has_text="ticked").first.inner_text()
    ticked = page.locator(BOXES).evaluate_all("boxes => boxes.filter(box => box.checked).length")
    return int(COUNTER.search(caption).group(1)), ticked


def files_line(page) -> str:
    return page.locator(".st-key-files_button").first.inner_text().split("\n")[0]


def uploads_cancelled(page, uploads: list[str], check) -> None:
    """Upload files with nothing loaded, Esc: the reopened window holds no box of them and Done reads nothing.

    The page stops under the window, so the server keeps the upload the browser forgot.
    """
    page.keyboard.press("f")
    settle(page)
    page.locator("[role=dialog] [data-testid=stFileUploader] input[type=file]").set_input_files(uploads)
    settle(page)
    shown = page.locator(UPLOAD_BOXES).count()
    check(f"the two uploaded files are listed ({shown} boxes)", shown == len(uploads))
    page.keyboard.press("Escape")
    settle(page)
    page.keyboard.press("f")
    settle(page)
    ghosts = page.locator(UPLOAD_BOXES).count()
    check(f"window reopened after Esc: no box of the cancelled uploads ({ghosts} left)", ghosts == 0)
    page.get_by_role("button", name="Done").click()
    settle(page)
    check(f"Done reads nothing ({files_line(page)!r})", "none read" in files_line(page))


def replay(page, uploads: list[str]) -> list[tuple[str, bool]]:
    """Run the scenarios; return (what was checked, whether it held)."""
    results = []

    def check(what: str, held: bool) -> None:
        results.append((what, held))
        print(("ok    " if held else "FAIL  ") + what, flush=True)

    uploads_cancelled(page, uploads, check)
    page.keyboard.press("f")
    settle(page)
    for index in range(TICKED):
        page.locator(BOXES).nth(index).locator("xpath=ancestor::label").click()
        settle(page)
    page.get_by_role("button", name="Done").click()
    page.wait_for_selector("[role=dialog]", timeout=120_000)  # the Baseline window, opened by the app
    settle(page)
    page.keyboard.press("Escape")
    settle(page)
    page.locator(".st-key-baseline_button button").first.click()
    settle(page)
    counted, ticked = counted_and_ticked(page)
    check(f"window reopened after Esc: counter {counted} equals the {ticked} boxes ticked", counted == ticked == TICKED)
    page.locator("[role=dialog] [data-testid=stSelectbox]", has_text="Baseline (BL)").first.click()
    page.get_by_role("option", name="Separate baseline file").first.click()
    settle(page)
    counted, ticked = counted_and_ticked(page)
    check(f"after the first click: counter {counted} equals the {ticked} boxes ticked", counted == ticked == TICKED)
    page.get_by_role("button", name="Done").click()
    settle(page)
    check(f"Done keeps the series ({files_line(page)!r})", f"{TICKED} files" in files_line(page))
    page.keyboard.press("f")
    settle(page)
    page.get_by_role("button", name="Clear").click()
    settle(page)
    check("Clear then Done is disabled while a series is loaded", page.get_by_role("button", name="Done").is_disabled())
    return results


def main(argv=None) -> int:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--chromium", help="path of a Chromium executable, when Playwright's own is not installed")
    args = parser.parse_args(argv)
    from xerscope.sample import generate

    with demo_app() as address, sync_playwright() as playwright, tempfile.TemporaryDirectory() as folder:
        generate(folder, weeks=2)
        uploads = sorted(str(path) for path in Path(folder).glob("*.xer"))
        browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
        page = browser.new_context(viewport={"width": 1440, "height": 1400}).new_page()
        page.goto(address)
        page.wait_for_selector("[data-testid=stSidebar]", timeout=60_000)
        settle(page)
        results = replay(page, uploads)
        browser.close()
    return 0 if all(held for _, held in results) else 1


if __name__ == "__main__":
    sys.exit(main())
