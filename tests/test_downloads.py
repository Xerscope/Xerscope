"""The download adapter of the app: the sidebar switch, the files read, the refusal on a leak.

Run on a plain dict standing in for the Streamlit session: no page is rendered.
"""

import csv
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from xerkit import todo, xer_text

from xerscope.anonymize import LeakError
from xerscope.app.state import anonymizer, anonymizers_built, downloads_ready, fetch, held, hold

NAMES = {"A": "Pump house", "B": "Boiler room"}


def _session(**more) -> dict:
    items = [
        (f"{name}.xer", xer_text([todo(code, task_name=NAMES[code])]).encode("utf-8"))
        for name, code in (("a", "A"), ("b", "B"))
    ]
    return {"signature": "s1", "items": items, **more}


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"task_code": ["A"], "task_name": [NAMES["A"]]})


def _never_plain() -> bytes:
    raise AssertionError("the plain build must not run with anonymous exports on")


def test_switch_off_gives_the_plain_bytes_and_builds_no_anonymizer():
    session = _session(anon_exports=False)
    out = fetch(session, lambda: b"plain", lambda anonymous: b"anon", ["a.xer"])
    assert out is not None
    assert (out.data, out.refused, out.anonymised) == (b"plain", "", False)
    assert anonymizers_built(session) == {}


def test_switch_on_is_the_default_and_never_runs_the_plain_build():
    session = _session()
    assert fetch(session, _never_plain, lambda anonymous: b"anon", ["a.xer"]) is None  # not prepared yet
    out = fetch(session, _never_plain, lambda anonymous: anonymous.csv(_frame()), ["a.xer"], prepare=True)
    assert out is not None and out.anonymised and not out.refused
    cells = {cell for row in csv.reader(io.StringIO(out.data.decode("utf-8-sig"))) for cell in row}
    # whole cells: a substring test fails whenever a drawn code ends with the original one ("XA…A")
    assert "A" not in cells and NAMES["A"] not in cells
    assert any(cell.startswith("XA") for cell in cells)


def test_the_anonymizer_reads_only_the_sources_and_one_for_more_files_serves_fewer():
    session = _session()
    assert not downloads_ready(["a.xer"], session)
    anonymizer(prepare=True, sources=["a.xer"], session=session)
    assert list(anonymizers_built(session)) == [frozenset({"a.xer"})]
    assert downloads_ready(["a.xer"], session) and not downloads_ready(["b.xer"], session)
    anonymizer(prepare=True, session=session)
    assert len(anonymizers_built(session)) == 2
    assert downloads_ready(["b.xer"], session)


def test_a_leak_is_a_refusal_not_bytes():
    session = _session()
    leaking = pd.DataFrame({"task_code": ["A"], "task_name": [NAMES["A"]], "reason": [NAMES["A"]]})
    out = fetch(session, _never_plain, lambda anonymous: anonymous.csv(leaking), ["a.xer"], prepare=True)
    assert out is not None and out.data is None and out.anonymised
    assert "TASK.task_name" in out.refused

    def leak(anonymous):
        raise LeakError("clndr_data")

    again = fetch(session, _never_plain, leak, ["a.xer"])
    assert again is not None and again.data is None and again.refused == "clndr_data"


def test_the_anonymised_choice_can_be_forced_whatever_the_switch():
    session = _session(anon_exports=False)
    out = fetch(session, None, lambda anonymous: b"anon", prepare=True, anonymous=True)
    assert out is not None and out.data == b"anon" and out.anonymised


def test_a_held_download_is_for_the_loaded_files_and_what_it_was_built_for():
    session = _session()
    out = fetch(session, _never_plain, lambda anonymous: b"x", ["a.xer"], prepare=True)
    hold(session, "slot", ("a.xer", True), out)
    assert held(session, "slot", ("a.xer", True)) == out
    assert held(session, "slot", ("a.xer", False)) is None
    session["signature"] = "s2"
    assert held(session, "slot", ("a.xer", True)) is None


@pytest.mark.parametrize("switch", [True, False])
def test_only_the_switch_decides(switch):
    session = _session(anon_exports=switch)
    out = fetch(session, lambda: b"plain", lambda anonymous: b"anon", prepare=True)
    assert out.anonymised is switch
    assert out.data == (b"anon" if switch else b"plain")


def _members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _typed_frame() -> pd.DataFrame:
    """A code, a date with minutes, float noise and a float of more than 4 decimals."""
    return pd.DataFrame(
        {
            "task_code": ["A", "B"],
            "data_date": pd.to_datetime(["2026-03-06 17:00", "2026-03-09 08:30"]),
            "bac_hr": [12345.999999, 1 / 3],
            "gap_hr": [6.9e-13, None],
        }
    )


def test_every_csv_path_writes_the_same_bytes(tmp_path):
    """The page CSV, the zipped CSV (All sets ZIP, Debug, Power BI) and the CLI file of one frame are
    the same bytes; the anonymised CSV, the anonymised zip of the pages and the anonymised Debug zip
    too, and differ from the plain ones by the codes only."""
    from xerscope.cli import _write_csv
    from xerscope.export import csv_bytes, zip_frames

    frame = _typed_frame()
    plain = csv_bytes(frame)
    assert plain.decode("utf-8-sig").splitlines()[1:] == [
        "A,2026-03-06 17:00,12346.0000,0.0000",
        "B,2026-03-09 08:30,0.3333,",
    ]
    assert _members(zip_frames({"t": frame}, "csv")) == {"t.csv": plain}
    _write_csv(frame, tmp_path / "t.csv")
    assert (tmp_path / "t.csv").read_bytes() == plain

    anonymous = anonymizer(prepare=True, session=_session())
    anonymised = anonymous.csv(frame)
    assert _members(zip_frames({"t": anonymous.frame(frame)}, "csv")) == {"t.csv": anonymised}
    assert _members(anonymous.zip_frames({"t": frame})) == {"t.csv": anonymised}

    def without_codes(data: bytes) -> list[list[str]]:
        return [row[1:] for row in csv.reader(io.StringIO(data.decode("utf-8-sig")))]

    assert anonymised != plain and without_codes(anonymised) == without_codes(plain)


def test_csv_bytes_is_the_only_csv_writer():
    """A second ``to_csv`` would write its own decimals and dates: every CSV goes through csv_bytes."""
    import xerscope

    found = [
        f"{path.name}:{number}"
        for path in sorted(Path(xerscope.__file__).parent.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ".to_csv(" in line
    ]
    assert len(found) == 1 and found[0].startswith("export.py:"), found
