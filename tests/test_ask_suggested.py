"""analysis/ask/suggested.py: the words taught in the Ask field, appended to suggested/ for
review, under the guards a folder written from a web page needs."""

import os
import stat
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from xerscope.analysis.ask import suggested

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="flock: the NAS layout runs on Linux")
NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)


def _entries(folder):
    return tomllib.loads((folder / suggested.FILE).read_text(encoding="utf-8")).get("suggestion", [])


def test_a_correction_records_the_word_the_label_its_column_the_filter_and_the_date(tmp_path):
    assert suggested.record(tmp_path, "commiss", "COM · Commissioning", "wbs", NOW)
    assert suggested.record(tmp_path, "grutier", "CRANE", "resource", NOW)
    assert _entries(tmp_path) == [
        {"word": "commiss", "label": "COM · Commissioning", "column": "PROJWBS.wbs_name", "facet": "wbs",
         "value": "COM", "at": NOW},
        {"word": "grutier", "label": "CRANE", "column": "RSRC.rsrc_short_name", "facet": "resource",
         "value": "CRANE", "at": NOW},
    ]  # fmt: skip
    assert os.listdir(tmp_path) == [suggested.FILE]
    assert stat.S_IMODE((tmp_path / suggested.FILE).stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "word",
    ["", "a" * (suggested.MAX_WORD + 1), "com\nmiss", 'x"]\n[[suggestion]]', "com]", "com[", "bell\x07",
     "nul\x00", "tab\tword", "esc\x1b[31m", 'quo"te', "back\\slash", "a=b", "\u202eevil"],
)  # fmt: skip
def test_a_word_outside_the_allowed_characters_or_length_is_refused(tmp_path, word):
    assert not suggested.record(tmp_path, word, "COM · Commissioning", "wbs", NOW)
    assert not (tmp_path / suggested.FILE).exists()


def test_word_and_label_are_nfkc_normalised(tmp_path):
    assert suggested.record(tmp_path, "ｃｏｍｍｉｓｓ", "COM · Commissioning", "wbs", NOW)  # fullwidth letters
    assert _entries(tmp_path)[0]["word"] == "commiss"
    assert not suggested.record(tmp_path, "com］", "COM · Commissioning", "wbs", NOW)  # fullwidth ] is ]


def test_a_label_too_long_or_an_unknown_source_is_refused(tmp_path):
    assert not suggested.record(tmp_path, "commiss", "C" * (suggested.MAX_LABEL + 1), "wbs", NOW)
    assert not suggested.record(tmp_path, "commiss", "COM · Commissioning", "../../etc", NOW)
    assert not (tmp_path / suggested.FILE).exists()


def test_the_file_name_never_comes_from_the_input(tmp_path):
    """A word shaped like a path is data inside a quoted string, never a file name."""
    inside = tmp_path / "suggested"
    inside.mkdir()
    assert suggested.record(inside, "../../evil", "COM · Commissioning", "wbs", NOW)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == [
        "suggested",
        f"suggested/{suggested.FILE}",
    ]
    assert _entries(inside)[0]["word"] == "../../evil"


def test_a_symlink_in_place_of_the_file_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere.txt"
    target.write_text("kept\n", encoding="utf-8")
    folder = tmp_path / "suggested"
    folder.mkdir()
    (folder / suggested.FILE).symlink_to(target)
    assert not suggested.record(folder, "commiss", "COM · Commissioning", "wbs", NOW)
    assert target.read_text(encoding="utf-8") == "kept\n"


def test_a_full_file_refuses_the_next_entry_and_is_left_as_it_is(tmp_path):
    path = tmp_path / suggested.FILE
    path.write_bytes(b"#" * (suggested.MAX_BYTES - 10) + b"\n")
    before = path.read_bytes()
    assert not suggested.record(tmp_path, "commiss", "COM · Commissioning", "wbs", NOW)
    assert path.read_bytes() == before


def test_concurrent_writes_are_whole_entries_and_stay_under_the_cap(tmp_path):
    """Each write checks the size and appends under one lock: entries never interleave and the
    file never passes MAX_BYTES, however many sessions click at once."""
    one = len(suggested.entry("commiss", "COM · Commissioning", "wbs", NOW).encode())
    path = tmp_path / suggested.FILE
    path.write_bytes(b"#" * (suggested.MAX_BYTES - 10 * one - 2) + b"\n")
    with ThreadPoolExecutor(16) as pool:
        written = list(
            pool.map(lambda i: suggested.record(tmp_path, f"word{i}", "COM · Commissioning", "wbs", NOW), range(64))
        )
    assert sum(written) == 10 and path.stat().st_size <= suggested.MAX_BYTES
    assert len(_entries(tmp_path)) == 10


def test_concurrent_writes_from_processes_all_land(tmp_path):
    import multiprocessing

    with multiprocessing.get_context("spawn").Pool(4) as pool:
        pool.starmap(suggested.record, [(tmp_path, f"word{i}", "COM · Commissioning", "wbs", NOW) for i in range(40)])
    assert sorted(e["word"] for e in _entries(tmp_path)) == sorted(f"word{i}" for i in range(40))


def test_nothing_is_printed_or_logged(tmp_path, capsys, caplog):
    suggested.record(tmp_path, "commiss", "COM · Commissioning", "wbs", NOW)
    suggested.record(tmp_path, "com\nmiss", "COM · Commissioning", "wbs", NOW)
    assert capsys.readouterr() == ("", "") and not caplog.records


def test_purge_drops_what_curated_did_not_take_after_the_retention(tmp_path):
    old, recent = NOW - suggested.RETENTION - timedelta(days=1), NOW - suggested.RETENTION + timedelta(days=1)
    for word, at in (("ancien", old), ("valide", old), ("recent", recent)):
        assert suggested.record(tmp_path, word, "COM · Commissioning", "wbs", at)
    curated = {"valide": ("com",), "com": ("valide",)}  # copied into curated/ by the maintainer
    assert suggested.purge(tmp_path, curated, NOW) == (2, 1)
    assert [e["word"] for e in _entries(tmp_path)] == ["valide", "recent"]
    assert stat.S_IMODE((tmp_path / suggested.FILE).stat().st_mode) == 0o600
    assert os.listdir(tmp_path) == [suggested.FILE]  # no temporary file left
    assert suggested.purge(tmp_path, curated, NOW) == (2, 0)
    assert suggested.purge(tmp_path / "missing", curated, NOW) == (0, 0)


def test_a_write_after_a_purge_lands_in_the_new_file(tmp_path):
    assert suggested.record(tmp_path, "ancien", "COM · Commissioning", "wbs", NOW - timedelta(days=200))
    suggested.purge(tmp_path, {}, NOW)
    assert suggested.record(tmp_path, "nouveau", "COM · Commissioning", "wbs", NOW)
    assert [e["word"] for e in _entries(tmp_path)] == ["nouveau"]
