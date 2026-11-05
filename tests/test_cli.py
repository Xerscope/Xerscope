"""Every CLI command, run in-process on the demo series and on a P6 reference file."""

from __future__ import annotations

import pandas as pd
import pytest
from xerkit import todo, xer_text

from xerscope import cli
from xerscope.analysis import builtin_standards, compare_counts


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


def test_check_rejects_unknown_standard(sample_dir):
    with pytest.raises(SystemExit, match="unknown standard"):
        cli.main(["check", str(sample_dir), "--standard", "nope"])


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


def test_paths_with_nothing_to_read_stop_with_a_message(tmp_path):
    with pytest.raises(SystemExit, match="no .xer file"):
        cli.main(["check", str(tmp_path)])
    with pytest.raises(SystemExit, match="no such file"):
        cli.main(["info", str(tmp_path / "missing.xer")])


def test_same_data_date_twice_stops_with_the_files(sample_dir, tmp_path):
    first = sorted(sample_dir.glob("*.xer"))[0]
    folder = tmp_path / "exports"
    folder.mkdir()
    for name in (first.name, "zz-copy.xer"):
        (folder / name).write_bytes(first.read_bytes())
    with pytest.raises(SystemExit, match=f"several files per status date.*{first.name}, zz-copy.xer"):
        cli.main(["export", str(folder), "--out", str(tmp_path / "bi")])


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
    with pytest.raises(SystemExit, match="pv_hr"):
        cli.main(
            [
                "pv-compare",
                str(tmp_path / "w.xer"),
                "--baseline",
                str(tmp_path / "bl.xer"),
                "--p6",
                str(tmp_path / "p6.csv"),
            ]
        )
    text = run(
        capsys, "pv-compare", tmp_path / "w.xer", "--planned-baseline", "--p6", tmp_path / "p6.csv",
        "--column", "pv_hr=PV", "--out", tmp_path / "cmp",
    )  # fmt: skip
    assert "activities in gap" in text
