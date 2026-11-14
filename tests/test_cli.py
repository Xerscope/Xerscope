"""Every CLI command, run in-process on the demo series and on a P6 reference file."""

from __future__ import annotations

import re

import asklex
import pandas as pd
import pytest
from xerkit import ROOT_WBS, todo, xer_text

from xerscope import cli
from xerscope.analysis import builtin_standards, compare_counts, query


def stops(*argv) -> bool:
    """True when the command stops on its input with exit code 2 (cli.INPUT_ERROR)."""
    with pytest.raises(SystemExit) as stop:
        cli.main(list(argv))
    return stop.value.code == cli.INPUT_ERROR


def run(capsys, *argv) -> str:
    assert cli.main([str(a) for a in argv]) == 0
    return capsys.readouterr().out


def test_info(capsys, sample_dir):
    out = run(capsys, "info", sample_dir)
    assert "PRJ-ALPHA_2026-08-31.xer" in out and "forecast_finish" in out


@pytest.mark.parametrize("std", list(builtin_standards()))
def test_check_every_standard(capsys, sample_dir, tmp_path, std):
    dest = tmp_path / "out.csv"
    out = run(capsys, "check", sample_dir, "--standard", std, "--planned-baseline", "--out", dest)
    df = pd.read_csv(dest, keep_default_na=False)  # "n/a" is a status, not a missing value
    assert len(df) == len(builtin_standards()[std].metrics) * 8  # every metric on every week
    assert set(df["status"]) <= {"pass", "fail", "info", "n/a"}  # no rule raised
    assert "baseline planned dates" in out


def test_check_flagged_and_expect(capsys, sample_dir, tmp_path):
    """--flagged writes the items behind each count; --expect compares counts typed from a P6
    Check Schedule summary and fails the command on a difference."""
    first = sorted(sample_dir.glob("*.xer"))[0]
    dest = tmp_path / "out.csv"
    run(capsys, "check", first, "--standard", "P6", "--flagged", tmp_path / "flagged", "--out", dest)
    df = pd.read_csv(dest, keep_default_na=False)
    listed = {p.stem.rsplit("_", 1)[1] for p in (tmp_path / "flagged").glob("*.csv")}
    assert listed == {r.id for r in df.itertuples() if r.found not in ("", "<NA>", "0")}
    row = df[df["id"] == "P6-01"].iloc[0]
    good = tmp_path / "expect.csv"
    good.write_text(f"id,found,total\nP6-01,{row['found']},{row['total']}\n")
    assert "all counts match" in run(capsys, "check", first, "--standard", "P6", "--expect", good)
    bad = tmp_path / "wrong.csv"
    bad.write_text(f"id,found,total\nP6-01,{int(row['found']) + 1},{row['total']}\n")
    assert cli.main(["check", str(first), "--standard", "P6", "--expect", str(bad)]) == 1
    assert "1 difference(s)" in capsys.readouterr().err


def test_compare_counts_leaves_untyped_lines_out():
    got = pd.DataFrame({"id": ["A", "B", "C"], "check": ["a", "b", "c"], "found": [1, 2, None], "total": [9, 9, None]})
    got[["found", "total"]] = got[["found", "total"]].astype("Int64")
    typed = pd.DataFrame({"id": ["A", "B", "C", "D"], "found": [1, 3, None, 0], "total": [9, 9, None, 5]})
    r = compare_counts(got, typed)
    assert list(r["id"]) == ["A", "B", "D"]  # C: nothing typed, not part of the report
    assert list(r["match"]) == [True, False, False]  # B: found differs; D: no such check


def test_check_with_baseline_file(capsys, sample_dir):
    first = sorted(sample_dir.glob("*.xer"))[0]
    out = run(capsys, "check", sample_dir, "--standard", "P6", "--baseline", first)
    assert f"baseline BL 2026-08-31 · {first.name}" in out


def test_check_reads_the_p6_project_baseline_of_each_file(capsys, tmp_path):
    """a.xer holds its P6 Project Baseline, b.xer none. By hand (file_projects.two_projects): A1 and A2
    forecast 03-13 against a baseline finish 03-06, 2 late of 2 (P6-12); 0 of the 2 baseline activities
    complete (P6-13). Without the option P6-12 / P6-13 are n/a; b.xer falls back on --planned-baseline."""
    from file_projects import two_projects

    (tmp_path / "a.xer").write_text(two_projects(data_date="2026-03-02 08:00"))
    (tmp_path / "b.xer").write_text(two_projects(pointer="", data_date="2026-03-09 08:00", with_baseline=False))
    dest = tmp_path / "out.csv"

    def rows():
        frame = pd.read_csv(dest, keep_default_na=False)
        frame = frame[frame["id"].isin(["P6-12", "P6-13"])].set_index(["file", "id"])
        return {key: (row.status, row.found, row.total) for key, row in frame.iterrows()}

    run(capsys, "check", tmp_path, "--standard", "P6", "--out", dest)
    assert {status for status, _, _ in rows().values()} == {"n/a"}
    out = run(capsys, "check", tmp_path, "--standard", "P6", "--baseline-in-file", "--planned-baseline", "--out", dest)
    assert "a.xer · data date 2026-03-02 · baseline BL (P6 Project Baseline in a.xer)" in out
    assert "b.xer · data date 2026-03-09 · baseline planned dates (target_*) of" in out
    got = rows()
    assert got[("a.xer", "P6-12")][1:] == (2, 2) and got[("a.xer", "P6-13")][1:] == (0, 2)


def test_check_baseline_in_file_refuses_two_files_of_one_name(capsys, tmp_path):
    for folder in ("w1", "w2"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "a.xer").write_text(xer_text([todo("A1")]))
    assert stops("check", str(tmp_path / "w1"), str(tmp_path / "w2"), "--baseline-in-file")
    assert "distinct file names" in capsys.readouterr().err


def test_check_rejects_unknown_standard(capsys, sample_dir):
    assert stops("check", str(sample_dir), "--standard", "nope")
    assert "unknown standard" in capsys.readouterr().err


def test_standards_list_rules_and_template(capsys, tmp_path):
    assert "P6-14" in run(capsys, "standards")
    assert "missing_logic" in run(capsys, "standards", "--rules")
    dest = tmp_path / "mine.toml"
    run(capsys, "standards", "--template", dest)
    assert "[standard]" in dest.read_text(encoding="utf-8")
    assert "[standard]" in run(capsys, "standards", "--template")


def test_recalc_reproduces_p6_and_writes_csv(capsys, tmp_path, require_reference):
    path = require_reference("p6viewer/TERMINAL BUILDING-AIRPORT.xer")
    dest = tmp_path / "recalc.csv"
    out = run(capsys, "recalc", path, "--out", dest)
    assert "66 / 66      identical" in out and "248 / 248 stored dates identical" in out
    assert len(pd.read_csv(dest)) == 66


def test_recalc_and_check_survive_a_file_without_data_date(capsys, tmp_path):
    path = tmp_path / "nodate.xer"
    path.write_text(xer_text([todo("A")], project={"last_recalc_date": "", "plan_start_date": ""}))
    assert "recalculated finish" in run(capsys, "recalc", path)
    assert "P6 Check Schedule" in run(capsys, "check", path)


def test_changelog(capsys, sample_dir, tmp_path):
    a, b = sorted(sample_dir.glob("*.xer"))[:2]
    dest = tmp_path / "log.csv"
    out = run(capsys, "changelog", a, b, "--out", dest)
    assert "category" in out and len(pd.read_csv(dest)) > 0


def test_export_csv(capsys, sample_dir, tmp_path):
    out = run(capsys, "export", sample_dir, "--out", tmp_path / "bi", "--format", "csv")
    assert "fact_activity" in out
    assert (tmp_path / "bi" / "dim_snapshot.csv").is_file()


def test_sample(capsys, tmp_path):
    out = run(capsys, "sample", "--out", tmp_path / "demo", "--weeks", 2)
    assert len(list((tmp_path / "demo").glob("*.xer"))) == 2 and ".xer" in out


def test_app_stays_on_localhost_and_uses_the_packaged_theme(monkeypatch, sample_dir):
    seen = {}

    def fake_call(cmd, env, cwd):
        seen.update(cmd=cmd, env=env, cwd=cwd)
        return 0

    monkeypatch.setattr(cli.subprocess, "call", fake_call)
    assert cli.main(["app", "--data", str(sample_dir)]) == 0
    cmd = seen["cmd"]
    assert cmd[cmd.index("--server.address") + 1] == "localhost"
    assert (seen["cwd"] / ".streamlit" / "config.toml").is_file()
    assert seen["env"]["XERSCOPE_DATA"] == str(sample_dir.resolve())


def test_check_exit_code_follows_fail_on(capsys, sample_dir):
    assert cli.main(["check", str(sample_dir), "--standard", "P6"]) == 0  # reports only, by default
    assert cli.main(["check", str(sample_dir), "--standard", "P6", "--fail-on", "fail"]) == 1  # the demo misses some
    assert cli.main(["check", str(sample_dir), "--standard", "P6", "--fail-on", "error"]) == 0  # every rule ran
    capsys.readouterr()


def test_paths_with_nothing_to_read_stop_with_a_message(capsys, tmp_path):
    assert stops("check", str(tmp_path))
    assert "no .xer file" in capsys.readouterr().err
    assert stops("info", str(tmp_path / "missing.xer"))
    assert "no such file" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        ("empty file", "not an XER file"),
        ("cut short", "no %E end line"),
        ("task_id twice", "table TASK has duplicate task_id"),
    ],
)
@pytest.mark.parametrize("command", ["info", "check", "recalc", "export"])
def test_an_unusable_file_stops_with_one_line_and_exit_2(capsys, tmp_path, command, damage, message):
    """An unusable .xer printed a Python traceback and exited 1, the code --fail-on and --expect
    use for a finding: a script could not tell a bad file from a schedule that misses the
    standard. Now: one line on stderr naming the file, exit 2."""
    text = xer_text([todo("A1"), todo("A2")])
    if damage == "empty file":
        text = ""
    elif damage == "cut short":
        text = text[: text.index("%E")]
    else:
        text = text.replace("%R\t2\t1\t", "%R\t1\t1\t", 1)
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "bad.xer").write_text(text)
    # export reads a folder of weekly files; the others take the file itself
    target = [str(folder), "--out", str(tmp_path / "bi")] if command == "export" else [str(folder / "bad.xer")]
    assert stops(command, *target)
    err = capsys.readouterr().err
    assert err.startswith("xerscope: bad.xer: ") and message in err and "Traceback" not in err


def test_a_missing_baseline_file_stops_with_exit_2(capsys, sample_dir, tmp_path):
    assert stops("check", str(sample_dir), "--baseline", str(tmp_path / "absent.xer"))
    assert "absent.xer" in capsys.readouterr().err


def test_same_data_date_twice_stops_with_the_files(capsys, sample_dir, tmp_path):
    first = sorted(sample_dir.glob("*.xer"))[0]
    folder = tmp_path / "exports"
    folder.mkdir()
    for name in (first.name, "zz-copy.xer"):
        (folder / name).write_bytes(first.read_bytes())
    assert stops("export", str(folder), "--out", str(tmp_path / "bi"))
    assert re.search(f"several files per status date.*{first.name}, zz-copy.xer", capsys.readouterr().err)


def test_pv_compare_writes_the_five_tables_from_the_disk(capsys, tmp_path):
    """Block 10 without the app: the update, a baseline file and a P6 Activities CSV on the disk.
    Fixture of tests/test_pv_p6.py: xerscope PV 76 h (A 40, E 12, F 16, G 8), P6 PV 103 h over its six
    rows; H is in the update but not in the baseline, D in neither file."""
    from test_pv_p6 import BASELINE, UPDATE, WED

    (tmp_path / "bl.xer").write_text(xer_text(BASELINE))
    (tmp_path / "w.xer").write_text(xer_text(UPDATE, data_date=WED))
    headers = (
        "Activity ID,Planned Value Labor Units,Earned Value Labor Units,Schedule % Complete,BL Project Labor Units"
    )
    rows = [
        "A,50,62.5,40%,125", "C,16,0,40%,40", "D,8,0,20%,40", "F,16,0,40%,40", "G,8,0,40%,20", "H,5,0,40%,10",
    ]  # fmt: skip
    (tmp_path / "p6.csv").write_text("\n".join([headers, *rows]) + "\n")
    out = tmp_path / "cmp"
    text = run(
        capsys, "pv-compare", tmp_path / "w.xer", "--baseline", tmp_path / "bl.xer", "--p6", tmp_path / "p6.csv",
        "--out", out, "--p6-total", "110",
    )  # fmt: skip
    assert "activities in gap" in text and "P6 total - export rows" in text
    names = sorted(p.name for p in out.iterdir())
    assert names == [
        "10_pv_p6_activities_in_gap.csv", "10_pv_p6_by_calendar.csv", "10_pv_p6_by_schedule_pct.csv",
        "10_pv_p6_gap_causes.csv", "10_pv_p6_totals.csv",
    ]  # fmt: skip
    totals = pd.read_csv(out / "10_pv_p6_totals.csv").set_index("group")
    assert totals.loc["all", ["pv_xerscope_hr", "pv_p6_hr"]].tolist() == [76.0, 103.0]
    assert totals.loc["P6 total - export rows", "pv_p6_hr"] == 7.0
    in_gap = pd.read_csv(out / "10_pv_p6_activities_in_gap.csv")
    assert "A" in set(in_gap["task_code"]) and "F" not in set(in_gap["task_code"])


def test_pv_compare_names_the_missing_column_and_accepts_a_mapping(capsys, tmp_path):
    from test_pv_p6 import BASELINE, UPDATE, WED

    (tmp_path / "bl.xer").write_text(xer_text(BASELINE))
    (tmp_path / "w.xer").write_text(xer_text(UPDATE, data_date=WED))
    (tmp_path / "p6.csv").write_text("Activity ID,PV,Earned Value Labor Units,Schedule % Complete\nA,50,62.5,40%\n")
    assert stops(
        "pv-compare", str(tmp_path / "w.xer"), "--baseline", str(tmp_path / "bl.xer"),
        "--p6", str(tmp_path / "p6.csv"),
    )  # fmt: skip
    assert "pv_hr" in capsys.readouterr().err
    text = run(
        capsys, "pv-compare", tmp_path / "w.xer", "--planned-baseline", "--p6", tmp_path / "p6.csv",
        "--column", "pv_hr=PV", "--out", tmp_path / "cmp",
    )  # fmt: skip
    assert "activities in gap" in text


def test_ask_bench(capsys, sample_dir, tmp_path):
    asklex.write(tmp_path)  # the sentences say trade words in both languages: a company's lexicon
    out = run(
        capsys, "ask-bench", sample_dir, "--cases", "tests/ask/dev.toml", "--cases", "tests/ask/heldout.toml",
        "--lexicon", tmp_path,
    )  # fmt: skip
    assert "dev.toml: 32 sentences" in out and "keywords  exact 100%" in out
    assert "heldout.toml: 20 sentences" in out and "missed:" not in out  # every held-out sentence right


def test_ask_bench_anonymised_shows_no_original_name(capsys, sample_dir, tmp_path):
    asklex.write(tmp_path)
    out = run(capsys, "ask-bench", sample_dir, "--cases", "tests/ask/dev.toml", "--anonymize", "--lexicon", tmp_path)
    assert "anonymised copy XP" in out and "set aside:" in out and "sentences scored" in out
    assert "exact 100%" in out and "15 sentences scored" in out  # the sentences naming things by code or full name
    for secret in ("Civil works", "CIV", "Site crew", "CREW", "PRJ-ALPHA", "Ingénierie", "earthworks"):
        assert secret not in out, secret


def test_lexicon_command(capsys, tmp_path):
    out = run(capsys, "lexicon")
    assert out.strip() == "0 group(s), 0 word(s)"  # no lexicon ships with the package
    asklex.write(tmp_path)
    out = run(capsys, "lexicon", str(tmp_path))
    assert "meca, mecanique, mechanical" in out and "group(s)" in out
    out = run(capsys, "lexicon", str(tmp_path), "--word", "Mécanique")
    assert out.startswith("mecanique: ") and "mechanical" in out
    (tmp_path / "bad.toml").write_text("[[group]\n", encoding="utf-8")
    assert cli.main(["lexicon", str(tmp_path)]) == 1
    assert "error: bad.toml" in capsys.readouterr().out


def _without_table(text: str, name: str) -> str:
    """An XER text less one table (its %T, %F and %R lines)."""
    lines, kept, skipping = text.split("\n"), [], False
    for line in lines:
        if line.startswith("%T\t"):
            skipping = line == f"%T\t{name}"
        elif not line.startswith(("%F", "%R")):
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


def test_lexicon_build_skips_each_refused_export_and_names_it_in_the_report_only(capsys, tmp_path, monkeypatch):
    """Each export is checked before the generation: read without error, TASK and PROJWBS
    present, a project to select, at most LEXICON_MAX_BYTES. A refused one is skipped, the others
    are read; report.txt names it with a fixed reason, never its text nor an exception's
    message; the output counts it, never names it (the file name is often the project's)."""
    good = xer_text([todo("A1", task_name="Fondation pile"), todo("A2", task_name="Fondations")], wbs=ROOT_WBS)
    source = tmp_path / "xer"
    source.mkdir()
    (source / "a.xer").write_text(good)
    (source / "b-secretname.xer").write_text("qwfpsecret, not an export")
    (source / "c.xer").write_text(_without_table(good, "TASK"))
    (source / "d.xer").write_text(_without_table(good, "PROJWBS"))
    (source / "e.xer").write_text(_without_table(good, "PROJECT"))
    (source / "f.xer").write_text(good.removesuffix("%E\n"))
    monkeypatch.setattr(cli, "LEXICON_MAX_BYTES", len(good.encode()) + 10, raising=False)
    (source / "g.xer").write_text(good + " " * 20)
    for folder in ("generated", "suggested"):
        (tmp_path / folder).mkdir()
    out = run(capsys, "lexicon", "build", source, "--out", tmp_path)
    assert "TASK.task_name: 1 group(s), 1 new" in out and "6 file(s) skipped" in out
    assert "1 group(s) from 1 file(s) written" in out
    assert not re.search(r"[a-g](-secretname)?\.xer|secret", out)
    report = (tmp_path / "generated" / "report.txt").read_text(encoding="utf-8")
    assert report.split("skipped (not read):\n", 1)[1].splitlines()[:6] == [
        "b-secretname.xer: unreadable",
        "c.xer: missing table TASK",
        "d.xer: missing table PROJWBS",
        "e.xer: no project",
        "f.xer: incomplete",
        "g.xer: too large",
    ]
    assert "qwfpsecret" not in report and "TASK.task_name: fondation, fondations" in report


def _lexicon_source(tmp_path):
    """Three exports whose groups and pairs to review each join words of two files."""
    names = [
        ["Fondation pile", "Instalation pompe", "Gybsum partition"],
        ["Fondations radier", "Mec. support", "Screed floor"],
        ["Installation pompe", "Mechanical test", "Screen wall", "Gypsum board", "Screeds L2"],
    ]
    source = tmp_path / "xer"
    source.mkdir()
    for number, file_names in enumerate(names):
        tasks = [todo(f"A{number}{i}", task_name=name) for i, name in enumerate(file_names)]
        (source / f"{number}.xer").write_text(xer_text(tasks, wbs=ROOT_WBS))
    for folder in ("generated", "suggested"):
        (tmp_path / folder).mkdir()
    return source


def test_lexicon_build_holds_one_export_in_memory_at_a_time(capsys, tmp_path, monkeypatch):
    """A parsed 40 MB export holds about 0.75 GB (docs/deploy.md §7): the build keeps each
    export's words only, so no snapshot outlives the next export read (lexicon-init's 2 GB cap)."""
    import weakref

    source, read, alive = _lexicon_source(tmp_path), cli._lexicon_export, []
    refs: list[weakref.ref] = []

    def tracked(path):
        alive.append(sum(ref() is not None for ref in refs))  # snapshots still held, before this read
        snapshot = read(path)
        refs.append(weakref.ref(snapshot))
        return snapshot

    monkeypatch.setattr(cli, "_lexicon_export", tracked)
    run(capsys, "lexicon", "build", source, "--out", tmp_path)
    assert alive == [0, 0, 0]


def test_lexicon_build_writes_the_groups_and_pairs_of_every_export_together(capsys, tmp_path):
    """Read one export at a time, the build writes what the files give read together: groups and
    pairs to review that join words of two files."""
    source = _lexicon_source(tmp_path)
    snapshots = [cli._lexicon_export(path) for path in sorted(source.glob("*.xer"))]
    groups, near = query.variants(snapshots), query.near_spellings(snapshots)
    assert groups == {"TASK.task_name": [["fondation", "fondations"], ["mec", "mechanical"], ["screed", "screeds"]]}
    assert near == {"TASK.task_name": [("gybsum", "gypsum"), ("instalation", "installation"), ("screed", "screen")]}
    run(capsys, "lexicon", "build", source, "--out", tmp_path)
    generated = tmp_path / "generated"
    assert (generated / "variants.toml").read_text(encoding="utf-8") == query.variants_toml(groups)
    report = (generated / "report.txt").read_text(encoding="utf-8")
    to_review = report.split("to review (one letter apart, not used):\n", 1)[1].splitlines()
    assert to_review == [f"TASK.task_name: {a}, {b}" for a, b in near["TASK.task_name"]]
    assert "3 file(s) read, 0 skipped" in report


def test_lexicon_build_with_no_valid_export_leaves_generated_as_it_was(capsys, tmp_path):
    """No export passes the check (or none at all): generated/ is left untouched, the exit code
    is 1 and the output names no file."""
    source = tmp_path / "xer"
    source.mkdir()
    for folder in ("generated", "suggested"):
        (tmp_path / folder).mkdir()
    before = {"variants.toml": "# kept\n", "report.txt": "kept\n"}
    for name, text in before.items():
        (tmp_path / "generated" / name).write_text(text, encoding="utf-8")
    for files in ({}, {"b-secretname.xer": "qwfpsecret"}):
        for name, text in files.items():
            (source / name).write_text(text)
        assert cli.main(["lexicon", "build", str(source), "--out", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "no valid XER file" in out and "generated/ left as it is" in out
        assert "secret" not in out and ".xer" not in out
        assert {p.name: p.read_text(encoding="utf-8") for p in (tmp_path / "generated").iterdir()} == before


def test_ask_bench_self_coverage(capsys, sample_dir):
    out = run(capsys, "ask-bench", sample_dir, "--self")
    assert "labels of the file\n" in out and "labels covered: " in out and "= 100%" in out
    assert "not reached" not in out


def test_lexicon_build_rewrites_generated_and_purges_suggested(capsys, sample_dir, tmp_path):
    """`lexicon build SOURCE --out ROOT`: ROOT/generated/variants.toml and report.txt, each
    replaced whole (temporary file, then rename) and 0600; the suggestions not copied into
    curated/ after 90 days are purged; the output prints counts, never a word."""
    import stat
    from datetime import UTC, datetime, timedelta

    from xerscope.analysis.ask import suggested

    for folder in ("generated", "curated", "suggested"):
        (tmp_path / folder).mkdir()
    # the recent one first: a record purges what is expired at its own date
    suggested.record(tmp_path / "suggested", "recent", "COM · Commissioning", "wbs", datetime.now(UTC))
    suggested.record(
        tmp_path / "suggested", "ancien", "COM · Commissioning", "wbs", datetime.now(UTC) - timedelta(days=91)
    )
    out = run(capsys, "lexicon", "build", sample_dir, "--out", tmp_path)
    assert "group(s) from 8 file(s) written, 0 new" in out and "suggestions: 1 kept, 1 purged" in out
    assert "ancien" not in out and "recent" not in out
    generated = tmp_path / "generated"
    assert sorted(p.name for p in generated.iterdir()) == ["report.txt", "variants.toml"]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in generated.iterdir())
    assert (generated / "variants.toml").read_text(encoding="utf-8").startswith("# Variants generated from the files")
    assert "new since the last run" in (generated / "report.txt").read_text(encoding="utf-8")
    assert [p.name for p in (tmp_path / "suggested").iterdir()] == ["suggestions.toml"]
    assert cli.main(["lexicon", "build", str(sample_dir)]) == 2  # --out required


def test_lexicon_build_reports_the_groups_new_since_the_last_run(capsys, tmp_path):
    source = tmp_path / "xer"
    source.mkdir()
    (source / "a.xer").write_text(
        xer_text([todo("A1", task_name="Fondation pile"), todo("A2", task_name="Fondations")], wbs=ROOT_WBS)
    )
    (tmp_path / "generated").mkdir()
    (tmp_path / "suggested").mkdir()
    (tmp_path / "generated" / "variants.toml").write_text("", encoding="utf-8")
    out = run(capsys, "lexicon", "build", source, "--out", tmp_path)
    assert "TASK.task_name: 1 group(s), 1 new" in out and "fondation" not in out
    report = (tmp_path / "generated" / "report.txt").read_text(encoding="utf-8")
    assert "TASK.task_name: fondation, fondations" in report
    out = run(capsys, "lexicon", "build", source, "--out", tmp_path)
    assert "TASK.task_name: 1 group(s), 0 new" in out
