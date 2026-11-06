"""Software audit of the app layer (rules/standards loading, explain, store, session cache, export,
anonymiser, CLI): input validation, division by zero, float comparison, cache bounds, injection
(CWE-22, CWE-78, CWE-1236), determinism. A test marked xfail(strict=True) documents a defect
(AUDIT-APP-nn); the others pin behaviour found correct. Every schedule is built with xerkit."""

from __future__ import annotations

import io
import os
import subprocess
import time
import types
import zipfile
from dataclasses import replace

import pandas as pd
import pytest
from rulekit import STANDARDS, run
from xerkit import DD, done, todo, xer_text

from xerscope import cli
from xerscope.analysis import AnalysisContext, Baseline, run_metric, run_standard
from xerscope.analysis.explain import explain
from xerscope.analysis.rules import RULES
from xerscope.analysis.standards import Standard, discover_standards, load_standard, loads_standard
from xerscope.anonymize import Anonymizer
from xerscope.export import write_tables, zip_tables
from xerscope.store import DuplicateDataDate, SnapshotStore
from xerscope.xer import build_snapshot, parse_text
from xerscope.xer.parser import read_xer

HEAD = '[standard]\nid = "X"\nname = "x"\n'
P6 = STANDARDS["P6"]


def std(body: str) -> Standard:
    return loads_standard(HEAD + body)


def snap_named(tasks, preds=(), source="test.xer", **kw):
    return build_snapshot(parse_text(xer_text(tasks, preds, **kw), source=source))


# --- rules / standards: empty populations and the target comparison -----------------------------


def test_percent_rule_on_empty_population_is_na_everywhere():
    """0 / 0: no NaN, no 0 %, no 100 %: status n/a with the note, in the frame and in explain."""
    s = snap_named([done("A1"), done("A2")])  # default exclude = complete: nothing left
    metric = std('[[metric]]\nid = "M"\nname = "m"\nrule = "missing_logic"\ntarget = "<= 0%"\n').metrics[0]
    r = run_metric(metric, AnalysisContext(s))
    assert (r.status, r.value, r.numerator, r.denominator) == ("n/a", None, 0, 0)
    e = explain(r)
    assert e.formula == "nothing to check" and e.verdict.startswith("Not applicable")
    for standard in STANDARDS.values():  # the built-in % metrics agree: never pass/fail on 0 / 0
        for result in run_standard(standard, AnalysisContext(s)):
            if result.metric.unit == "%" and result.denominator == 0:
                assert result.status == "n/a", (standard.id, result.metric.id)


def test_count_rule_on_empty_population_passes_not_na():
    """A count metric has no denominator: 0 found of nothing checked is 'pass', not n/a (Info: differs
    from the % reading of the same rule)."""
    s = snap_named([done("A1")])
    metric = std('[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\nunit = "count"\ntarget = "<= 0"\n').metrics[0]
    r = run_metric(metric, AnalysisContext(s))
    assert (r.status, r.value, r.denominator) == ("pass", 0.0, 0)


def test_ratio_rule_with_nothing_due_is_na():
    s = snap_named([todo("A1", target_end_date="2026-03-13 17:00")])  # planned finish after the data date
    metric = std('[[metric]]\nid = "M"\nname = "m"\nrule = "bei"\ntarget = ">= 0.95"\n').metrics[0]
    r = run_metric(metric, AnalysisContext(s, baseline=Baseline.planned(s)))  # nothing due: 0 / 0
    assert r.status == "n/a" and r.value is None and r.denominator == 0
    p6 = run(P6, "P6-13", s, baseline=Baseline.planned(s))  # P6's own reading counts every baseline task
    assert (p6.status, p6.numerator, p6.denominator) == ("fail", 0, 1)


def test_target_zero_percent_rounds_to_six_decimals_before_comparing():
    """'<= 0%' against 1e-7 passes (rounded to 6 decimals), against 1e-6 fails: the rounding is the
    float tolerance; no count-based % can fall below 1e-6 % without ~1e8 items."""
    metric = std('[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\ntarget = "<= 0%"\n').metrics[0]
    assert metric.evaluate(1e-7) == "pass"
    assert metric.evaluate(1e-6) == "fail"
    assert metric.evaluate(0.1 + 0.2 - 0.3) == "pass"  # 5.5e-17


# --- standards: TOML validation ----------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-01: metric id and name are not type-checked (int accepted)")
def test_metric_id_and_name_must_be_strings():
    with pytest.raises(ValueError):
        std('[[metric]]\nid = 5\nname = 6\nrule = "constraints"\n')


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-02: params as an array: TypeError, not the ValueError callers catch")
def test_params_of_wrong_shape_raise_value_error():
    with pytest.raises(ValueError):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\nparams = [1, 2]\n')


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-02: top-level 'metric' as a string raises AttributeError")
def test_metric_table_of_wrong_type_raises_value_error():
    with pytest.raises(ValueError):
        loads_standard('metric = "x"\n' + HEAD)


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-03: 2000 nested inline tables: RecursionError escapes discover")
def test_deeply_nested_toml_is_refused_as_a_load_error(tmp_path):
    depth = 2000
    body = '[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\nparams = ' + "{a=" * depth + "1" + "}" * depth
    (tmp_path / "deep.toml").write_text(HEAD + body + "\n", encoding="utf-8")
    found, errors = discover_standards(tmp_path)  # must report the file, not crash the app
    assert len(errors) == 1 and "deep.toml" in errors[0]


def test_empty_and_header_only_files_fail_loudly():
    with pytest.raises(ValueError, match="needs a \\[standard\\] table"):
        loads_standard("")
    with pytest.raises(ValueError, match="no \\[\\[metric\\]\\] defined"):
        loads_standard(HEAD)


def test_non_utf8_bytes_are_a_value_error_and_discover_reports_them(tmp_path):
    """UnicodeDecodeError is a ValueError: the loaders catch it; the message does not name the file
    when given bytes (Info)."""
    (tmp_path / "latin.toml").write_bytes(HEAD.encode() + b'[[metric]]\nid="M"\nname="caf\xe9"\nrule="lag"\n')
    with pytest.raises(ValueError):
        loads_standard((tmp_path / "latin.toml").read_bytes())
    found, errors = discover_standards(tmp_path)
    assert len(errors) == 1 and "P6" in found


def test_ten_megabyte_toml_loads_in_bounded_time():
    big = HEAD + ("# " + "x" * 100 + "\n") * 100_000 + '[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\n'
    assert len(big) > 10_000_000
    start = time.perf_counter()
    assert len(loads_standard(big).metrics) == 1
    assert time.perf_counter() - start < 5


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-04: target 'pass' accepted on a % metric: becomes 'value == 1 %'")
def test_pass_target_requires_pass_fail_unit():
    with pytest.raises(ValueError):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\ntarget = "pass"\n')


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-05: nan accepted as a numeric parameter: every comparison is False")
def test_nan_parameter_is_refused():
    with pytest.raises(ValueError):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\nparams = { value = nan }\n')


def test_negative_target_is_accepted_and_always_fails():
    """'<= -5%' is syntactically valid; every % value misses it (Info: no range check on a target)."""
    metric = std('[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\ntarget = "<= -5%"\n').metrics[0]
    assert metric.threshold == -5.0 and metric.evaluate(0.0) == "fail"


def test_unknown_key_in_standard_header_is_ignored():
    """[standard] extra keys are not checked (Info); [[metric]] extra keys are."""
    head = '[standard]\nid = "X"\nname = "x"\ncolour = "red"\n'
    assert loads_standard(head + '[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\n')
    with pytest.raises(ValueError, match="unknown key"):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\ncolour = "red"\n')


def test_a_rule_that_raises_marks_its_metric_in_error_and_the_others_run(monkeypatch):
    def boom(context, **params):
        raise RuntimeError("boom")

    broken = replace(RULES["lag"], fn=boom)
    monkeypatch.setitem(RULES, "lag", broken)
    standard = std(
        '[[metric]]\nid = "M1"\nname = "m"\nrule = "lag"\ntarget = "<= 0%"\n'
        '[[metric]]\nid = "M2"\nname = "n"\nrule = "constraints"\ntarget = "<= 0%"\n'
    )
    results = run_standard(standard, AnalysisContext(snap_named([todo("A1")])))
    assert [r.status for r in results] == ["error", "pass"]
    assert results[0].note == "RuntimeError: boom"
    assert explain(results[0]).verdict == "The rule raised an error: RuntimeError: boom"


# --- store ---------------------------------------------------------------------------------------


def test_three_identical_files_under_three_names_name_all_three():
    snaps = [snap_named([todo("A1")], source=name) for name in ("c.xer", "a.xer", "b.xer")]
    with pytest.raises(DuplicateDataDate) as caught:
        SnapshotStore(snaps)
    assert str(caught.value).endswith("2026-03-02: a.xer, b.xer, c.xer")  # sorted by data date then name


def test_snapshots_without_data_date_sort_by_name_and_sort_last():
    dated = snap_named([todo("A1")], source="z.xer")
    undated = [
        replace(snap_named([todo("A1")], source=name), data_date=None)
        if "data_date" in dated.__dataclass_fields__
        else None
        for name in ("b.xer", "a.xer")
    ]
    if None in undated:
        pytest.skip("Snapshot.data_date is derived, not a field: cannot build an undated snapshot here")
    assert [s.source for s in SnapshotStore([*undated, dated])] == ["z.xer", "a.xer", "b.xer"]


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-06: SnapshotStore([]) is accepted; summary then has a phantom row")
def test_empty_store_is_refused_or_consistent():
    with pytest.raises(ValueError):
        SnapshotStore([])


# --- app/state: per-session caches -------------------------------------------------------------


@pytest.fixture
def session(monkeypatch):
    """state.py talking to a plain dict instead of st.session_state (no Streamlit runtime)."""
    from xerscope.app import state

    fake = types.SimpleNamespace(session_state={})
    monkeypatch.setattr(state, "st", fake)
    return fake.session_state


def test_memo_is_bounded_and_evicts_least_recently_used(session):
    from xerscope.app import state

    for i in range(300):
        state.memo(("k", i), lambda i=i: i)
    cache = session["_memo"]
    assert len(cache) == state.MEMO_SIZE == 128
    assert state.memo(("k", 0), lambda: "recomputed") == "recomputed"  # evicted
    assert state.memo(("k", 299), lambda: "recomputed") == 299  # kept


def test_parsed_file_cache_is_bounded(session):
    from xerscope.app import state

    for i in range(70):
        state._parse(f"f{i}.xer", xer_text([todo(f"A{i}")]).encode())
    assert len(session["_parsed"]) <= 65


def test_no_process_wide_cache_in_state_module():
    """Two sessions never share: no st.cache_data / cache_resource, no module-level dict that grows."""
    import inspect

    from xerscope.app import state

    source = inspect.getsource(state)
    assert "cache_data" not in source and "cache_resource" not in source
    growing = [
        name
        for name, value in vars(state).items()
        if isinstance(value, (dict, list, set)) and not name.isupper() and not name.startswith("__")
    ]
    assert growing == []


# --- export ------------------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True, reason="AUDIT-APP-07: CWE-1236 CSV injection: a task name starting with =+-@ written as is"
)
def test_csv_export_neutralises_formula_cells(tmp_path):
    s = snap_named([todo("A1", task_name="=1+1"), todo("A2", task_name="@SUM(1)"), todo("A3", task_name="-2+3")])
    write_tables(SnapshotStore([s]), tmp_path, "csv")
    names = pd.read_csv(tmp_path / "fact_activity.csv", dtype=str)["task_name"].tolist()
    assert not any(name[0] in "=+-@" for name in names), names


def test_parquet_export_with_empty_relationship_and_assignment_tables(tmp_path):
    paths = write_tables(SnapshotStore([snap_named([todo("A1")])]), tmp_path, "parquet")
    for path in paths:
        frame = pd.read_parquet(path)
        assert frame.shape[0] == (1 if path.stem in ("dim_snapshot", "fact_activity") else 0)
    with zipfile.ZipFile(io.BytesIO(zip_tables(SnapshotStore([snap_named([todo("A1")])]), "csv"))) as z:
        tables = ("dim_snapshot", "fact_activity", "fact_relationship", "fact_assignment")
        assert sorted(z.namelist()) == sorted(f"{n}.csv" for n in tables)


# --- anonymiser -----------------------------------------------------------------------------------


def test_same_key_gives_the_same_pseudonym_and_another_key_another_one():
    a, b, c = Anonymizer(key=b"k" * 32), Anonymizer(key=b"k" * 32), Anonymizer(key=b"j" * 32)
    assert a.code("A", "A1000") == b.code("A", "A1000") != c.code("A", "A1000")
    assert a.code("A", "A1000") != a.code("A", "A1001")


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-08: 8 hex digits: 100k IDs clash with p~0.7 (comment says 0.03 %)")
def test_hundred_thousand_codes_get_distinct_pseudonyms():
    anonymizer = Anonymizer(key=bytes(32))
    for i in range(100_000):
        anonymizer.code("A", f"T{i}")


def test_what_leaves_the_file_and_what_is_dropped(tmp_path):
    text = xer_text(
        [todo("ZONE-A1", task_name="Secret Plant Alpha")],
        rsrc=("ZONE-A1",),
        resources=({"rsrc_id": "R1", "rsrc_short_name": "JDOE", "rsrc_name": "John Doe", "email_addr": "j@x.io"},),
        wbs=({"wbs_id": "10", "proj_id": "1", "wbs_short_name": "WBS-SECRET", "wbs_name": "Reactor hall"},),
        project={"proj_short_name": "ACME-PLANT"},
        header="23.12\t2026-03-02\tProject\tjsmith\tJohn Smith\tdb_prod",
    )
    text += "%T\tUDFVALUE\n%F\tudf_type_id\tfk_id\tudf_text\n%R\t1\t1\tConfidential memo\n"
    text += "%T\tTASKMEMO\n%F\tmemo_id\ttask_id\ttask_memo\n%R\t1\t1\t<html>budget overrun</html>\n"
    path = tmp_path / "ACME-PLANT_2026-03-02.xer"
    path.write_text(text, encoding="utf-8")
    raw = read_xer(path)
    anonymizer = Anonymizer.from_raws([raw])
    out = anonymizer.xer(raw).decode("utf-8")
    for secret in ("ZONE-A1", "Secret Plant Alpha", "JDOE", "John Doe", "j@x.io", "WBS-SECRET", "Reactor hall",
                   "ACME-PLANT", "jsmith", "John Smith", "db_prod", "Confidential", "budget overrun"):  # fmt: skip
        assert secret not in out, secret
    assert {"UDFVALUE", "TASKMEMO"} <= anonymizer.report.dropped_tables
    assert "RSRC.email_addr" in anonymizer.report.emptied_columns
    assert anonymizer.xer_name(raw, pd.Timestamp(DD)).startswith("XP") and "ACME" not in anonymizer.xer_name(raw, None)
    assert "2026-03-02 08:00" in out  # dates unchanged


# --- CLI -------------------------------------------------------------------------------------------


def test_app_command_runs_streamlit_without_a_shell_and_keeps_odd_paths_one_argument(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda cmd, **kw: calls.append((cmd, kw)) or 0)
    monkeypatch.setenv("TS_AUTHKEY", "tskey-test")
    weird = tmp_path / "my data; rm -rf x"
    weird.mkdir()
    assert cli.main(["app", "--data", str(weird), "--port", "8599"]) == 0
    ((cmd, kw),) = calls
    assert isinstance(cmd, list) and "shell" not in kw and "--server.address" in cmd and "localhost" in cmd
    assert kw["env"]["XERSCOPE_DATA"] == str(weird.resolve())
    assert kw["env"].get("TS_AUTHKEY") == "tskey-test"  # the child inherits the environment (Info, not logged)


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-09: _expand docstring says exit 2, SystemExit(str) exits 1")
def test_check_on_missing_path_exits_two(tmp_path):
    with pytest.raises(SystemExit) as caught:
        cli.main(["check", str(tmp_path / "nope.xer")])
    assert caught.value.code == 2


def test_standard_pointing_to_a_directory_is_refused(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    with pytest.raises(SystemExit, match="unknown standard"):
        cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path)])


def test_standard_through_symlink_and_dotdot_loads(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "s.toml").write_text(HEAD + '[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\n')
    (tmp_path / "sub").mkdir()
    link = tmp_path / "sub" / "link.toml"
    link.symlink_to(tmp_path / "s.toml")
    assert cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(link)]) == 0
    assert cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path / "sub" / ".." / "s.toml")]) == 0
    assert load_standard(link).id == "X"


@pytest.mark.xfail(
    strict=True, reason="AUDIT-APP-10: an invalid --standard file is a ValueError traceback, not a CLI exit"
)
def test_invalid_standard_file_is_a_clean_cli_error(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "bad.toml").write_text(HEAD)
    with pytest.raises(SystemExit):
        cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path / "bad.toml")])


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-10: a missing --baseline file is a FileNotFoundError traceback")
def test_missing_baseline_file_is_a_clean_cli_error(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    with pytest.raises(SystemExit):
        cli.main(["check", str(tmp_path / "a.xer"), "--baseline", str(tmp_path / "nope.xer")])


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-11: --expect with a malformed CSV is a pandas ParserError traceback")
def test_expect_with_malformed_csv_is_a_clean_cli_error(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    bad = tmp_path / "bad.csv"
    bad.write_text('id,found,total\n"P6-01,1,2\nx,y\n')
    with pytest.raises(SystemExit):
        cli.main(["check", str(tmp_path / "a.xer"), "--expect", str(bad)])


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-11: --expect with a non-numeric count is an ArrowInvalid traceback")
def test_expect_with_non_numeric_count_is_a_clean_cli_error(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    bad = tmp_path / "bad.csv"
    bad.write_text("id,found,total\nP6-01,abc,2\n")
    with pytest.raises(SystemExit):
        cli.main(["check", str(tmp_path / "a.xer"), "--expect", str(bad)])


@pytest.mark.xfail(strict=True, reason="AUDIT-APP-12: a metric id with '/' goes unsanitised into a file name (OSError)")
def test_flagged_file_name_survives_a_metric_id_with_a_slash(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "s.toml").write_text(HEAD + '[[metric]]\nid = "sub/M"\nname = "m"\nrule = "missing_logic"\n')
    argv = ["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path / "s.toml"), "--flagged", str(tmp_path / "fl")]
    assert cli.main(argv) == 0
    assert all(p.parent == tmp_path / "fl" for p in (tmp_path / "fl").rglob("*.csv"))


def test_expand_scans_ten_thousand_files_quickly(tmp_path):
    for i in range(10_000):
        (tmp_path / f"w{i:05}.xer").write_bytes(b"")
    start = time.perf_counter()
    found = cli._expand([str(tmp_path)])
    assert len(found) == 10_000 and found == sorted(found)
    assert time.perf_counter() - start < 5


def test_check_exit_codes(tmp_path, capsys):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))  # open ends: P6-01 fails
    assert cli.main(["check", str(tmp_path / "a.xer")]) == 0
    assert cli.main(["check", str(tmp_path / "a.xer"), "--fail-on", "fail"]) == 1
    assert cli.main(["check", str(tmp_path / "a.xer"), "--fail-on", "error"]) == 0
    assert os.environ.get("TS_AUTHKEY", "") not in capsys.readouterr().out or not os.environ.get("TS_AUTHKEY")
