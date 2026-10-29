"""Every CLI command, run in-process on the demo series and on a P6 reference file."""

from __future__ import annotations

import pandas as pd
import pytest
from xerkit import todo, xer_text

from xerscope import cli
from xerscope.analysis import builtin_standards


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
