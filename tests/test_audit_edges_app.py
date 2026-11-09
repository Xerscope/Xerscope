"""Software audit of the app layer (rules/standards loading, explain, store, session cache, export,
anonymiser, CLI): input validation, division by zero, float comparison, cache bounds, injection
(CWE-22, CWE-78, CWE-1236), determinism. A test marked xfail(strict=True) documents an open defect
(AUDIT-APP-nn); a test whose docstring names a finding pins its fix; the others pin behaviour found
correct. Every schedule is built with xerkit."""

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


def test_metric_id_and_name_must_be_strings():
    """AUDIT-APP-01: the text keys are type-checked; the message names the file, the metric and the key."""
    with pytest.raises(ValueError, match=r"uploaded\.toml: metric #1 \(5\): id must be a string, got 5"):
        std('[[metric]]\nid = 5\nname = 6\nrule = "constraints"\n')
    with pytest.raises(ValueError, match="name must be a string, got 6"):
        std('[[metric]]\nid = "M"\nname = 6\nrule = "constraints"\n')
    with pytest.raises(ValueError, match="description must be a string"):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\ndescription = 1\n')
    with pytest.raises(ValueError, match=r"\[standard\] name must be a string, got 1"):
        loads_standard('[standard]\nid = "X"\nname = 1\n[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\n')


def test_metric_id_is_a_file_name_safe_token():
    """AUDIT-APP-12: the id goes into the `--flagged` file name and the memo keys."""
    for bad in ("sub/M", "a b", "x\\y", "", "../M"):
        with pytest.raises(ValueError, match="letters, digits, '.', '_' and '-' only"):
            std(f'[[metric]]\nid = "{bad}"\nname = "m"\nrule = "constraints"\n'.replace("\\", "\\\\"))
    assert std('[[metric]]\nid = "P6-01.a_b"\nname = "m"\nrule = "constraints"\n').metrics[0].id == "P6-01.a_b"


def test_params_of_wrong_shape_raise_value_error():
    """AUDIT-APP-02: params as an array is a ValueError (the handlers catch it), not a TypeError."""
    with pytest.raises(ValueError, match=r"metric #1 \(M\): params must be a table"):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\nparams = [1, 2]\n')


def test_metric_table_of_wrong_type_raises_value_error():
    """AUDIT-APP-02: 'metric' as a string, or a [[metric]] entry that is not a table."""
    with pytest.raises(ValueError, match=r"uploaded\.toml: 'metric' must be an array of tables"):
        loads_standard('metric = "x"\n' + HEAD)
    with pytest.raises(ValueError, match=r"metric #2: expected a \[\[metric\]\] table, got 7"):
        loads_standard('metric = [{id = "M", name = "m", rule = "constraints"}, 7]\n' + HEAD)


def test_deeply_nested_toml_is_refused_as_a_load_error(tmp_path):
    """AUDIT-APP-03: 2000 nested inline tables are a load error naming the file, not a RecursionError."""
    depth = 2000
    body = '[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\nparams = ' + "{a=" * depth + "1" + "}" * depth
    (tmp_path / "deep.toml").write_text(HEAD + body + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="deep.toml: TOML too deeply nested"):
        load_standard(tmp_path / "deep.toml")
    found, errors = discover_standards(tmp_path)  # must report the file, not crash the app
    assert len(errors) == 1 and "deep.toml" in errors[0] and "P6" in found


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


def test_pass_target_requires_pass_fail_unit():
    """AUDIT-APP-04: 'pass' only on a pass/fail rule, and a pass/fail rule takes no number."""
    with pytest.raises(ValueError, match="target 'pass' needs unit 'pass/fail', the metric unit is '%'"):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\ntarget = "pass"\n')
    with pytest.raises(ValueError, match="a pass/fail metric takes 'pass' or 'info'"):
        std('[[metric]]\nid = "M"\nname = "m"\nrule = "dcma_12_critical_path_test"\ntarget = "== 1"\n')
    metric = std('[[metric]]\nid = "M"\nname = "m"\nrule = "dcma_12_critical_path_test"\ntarget = "pass"\n').metrics[0]
    assert (metric.comparator, metric.threshold, metric.threshold_label) == ("==", 1.0, "pass")
    assert std('[[metric]]\nid = "M"\nname = "m"\nrule = "dcma_12_critical_path_test"\n').metrics[0].comparator is None


def test_nan_parameter_is_refused():
    """AUDIT-APP-05: nan or inf as a numeric parameter would make every comparison False (a silent pass)."""
    for value in ("nan", "inf", "-inf"):
        with pytest.raises(ValueError, match=f"lag.value: expected a finite number, got {value}"):
            std(f'[[metric]]\nid = "M"\nname = "m"\nrule = "lag"\nparams = {{ value = {value} }}\n')


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


def test_empty_store_is_refused_or_consistent():
    """AUDIT-APP-06: a store holds at least one snapshot (summary had a phantom row, .first an IndexError)."""
    with pytest.raises(ValueError, match="no snapshot"):
        SnapshotStore([])
    with pytest.raises(ValueError, match="no snapshot"):
        SnapshotStore(iter(()))


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


# a tab or a carriage return cannot sit in a (tab-separated, line-based) XER field: csv_safe's own test covers them
FORMULA_NAMES = {"A1": "=1+1", "A2": "@SUM(1)", "A3": "-2+3", "A4": "+1", "A5": "=cmd|' /C calc'!A0"}


def formula_snapshot():
    return snap_named([todo(code, task_name=name) for code, name in FORMULA_NAMES.items()])


def read_names(data: bytes) -> dict[str, str]:
    frame = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    return dict(zip(frame["task_code"], frame["task_name"], strict=True))


def assert_neutralised(names: dict[str, str]) -> None:
    """Every formula-looking name leaves with a leading apostrophe (OWASP), nothing else changes."""
    assert names == {code: "'" + name for code, name in FORMULA_NAMES.items()}, names


def test_csv_export_neutralises_formula_cells(tmp_path):
    """AUDIT-APP-07 (CWE-1236): the Power BI CSVs; the Parquet tables keep the text as is."""
    store = SnapshotStore([formula_snapshot()])
    write_tables(store, tmp_path, "csv")
    assert_neutralised(read_names((tmp_path / "fact_activity.csv").read_bytes()))
    csv_frame = pd.read_csv(tmp_path / "fact_activity.csv")
    assert csv_frame["remaining_d"].dtype == float  # numeric columns are written as numbers
    write_tables(store, tmp_path, "parquet")
    parquet_names = pd.read_parquet(tmp_path / "fact_activity.parquet").set_index("task_code")["task_name"]
    assert parquet_names.to_dict() == FORMULA_NAMES
    with zipfile.ZipFile(io.BytesIO(zip_tables(store, "csv"))) as z:
        assert_neutralised(read_names(z.read("fact_activity.csv")))


def test_cli_csv_writers_neutralise_formula_cells(tmp_path):
    """AUDIT-APP-07: `check --flagged` and `--out`, `recalc --out` go through the same guard."""
    (tmp_path / "a.xer").write_text(xer_text([todo(code, task_name=name) for code, name in FORMULA_NAMES.items()]))
    flagged = tmp_path / "fl"
    out_csv = tmp_path / "o.csv"
    assert cli.main(["check", str(tmp_path / "a.xer"), "--flagged", str(flagged), "--out", str(out_csv)]) == 0
    open_ends = pd.read_csv(flagged / "a_P6-01.csv", dtype=str, keep_default_na=False)  # every task is an open end
    assert_neutralised(dict(zip(open_ends["task_code"], open_ends["task_name"], strict=True)))
    assert out_csv.read_bytes().startswith(b"\xef\xbb\xbf")  # the BOM stays
    assert cli.main(["recalc", str(tmp_path / "a.xer"), "--out", str(tmp_path / "r.csv")]) == 0
    recalc = pd.read_csv(tmp_path / "r.csv", dtype=str, keep_default_na=False)
    assert_neutralised(dict(zip(recalc["task_code"], recalc["task_name"], strict=True)))


def test_anonymised_csv_neutralises_formula_cells():
    """AUDIT-APP-07: the anonymiser renames the codes and the names (a name of the file in a note is
    a leak, refused before); a kept text column (here the note of a check result) goes through the
    guard too."""
    snapshot = formula_snapshot()
    anonymizer = Anonymizer.from_raws([parse_text(xer_text([todo(c, task_name=n) for c, n in FORMULA_NAMES.items()]))])
    notes = ["=note", "+note", "-note", "@note", "plain note"]
    table = snapshot.activities[["task_code", "task_name"]].assign(note=notes)
    out = pd.read_csv(io.BytesIO(anonymizer.csv(table)), dtype=str, keep_default_na=False)
    assert out["task_code"].str.fullmatch(r"XA[0-9A-F]{12}").all()
    assert out["note"].tolist() == ["'=note", "'+note", "'-note", "'@note", "plain note"]
    frames = {"t": pd.DataFrame({"task_code": list(FORMULA_NAMES), "note": notes})}
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames(frames))) as z:
        zipped = pd.read_csv(io.BytesIO(z.read("t.csv")), dtype=str, keep_default_na=False)
    assert zipped["note"].tolist() == ["'=note", "'+note", "'-note", "'@note", "plain note"]


def test_csv_safe_touches_text_cells_only():
    from xerscope.csv_safe import csv_safe

    frame = pd.DataFrame(
        {
            "text": ["=1", "+1", "-1", "@a", "\tb", "\rc", "plain", "a=b", None],
            "number": [-1, -2.5, 0, 1, 2, 3, 4, 5, 6],
            "date": pd.date_range("2026-03-02", periods=9),
            "mixed": ["-x", 1, None, pd.Timestamp("2026-03-02"), "=", "", " -", "ok", 2.5],
        }
    )
    out = csv_safe(frame)
    assert out["text"].tolist()[:8] == ["'=1", "'+1", "'-1", "'@a", "'\tb", "'\rc", "plain", "a=b"]
    assert pd.isna(out["text"].iloc[8])
    assert out["number"].tolist() == frame["number"].tolist() and out["number"].dtype == float
    assert out["date"].equals(frame["date"])
    assert out["mixed"].tolist()[:2] == ["'-x", 1] and out["mixed"].tolist()[4:] == ["'=", "", " -", "ok", 2.5]
    assert frame["text"].iloc[0] == "=1"  # the caller's frame is untouched


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


def test_hundred_thousand_codes_get_distinct_pseudonyms():
    """AUDIT-APP-08: 12 hex digits for activities (p(clash) ~ 2e-5 at 100k), 8 for the other kinds
    (p ~ 1e-2 at 10k); under five keys here, none clashes. A clash is still refused (CodeClash)."""
    from xerscope.anonymize import WIDTH

    assert WIDTH == {"A": 12, "W": 8, "P": 8, "R": 8, "L": 8, "O": 8}
    for key in (bytes(32), b"k" * 32, (1).to_bytes(32, "big"), (2).to_bytes(32, "big"), (3).to_bytes(32, "big")):
        anonymizer = Anonymizer(key=key)
        codes = {anonymizer.code("A", f"T{i}") for i in range(100_000)}
        assert len(codes) == 100_000 and all(len(code) == 14 for code in codes)
        wbs = {anonymizer.code("W", f"W{i}") for i in range(10_000)}
        assert len(wbs) == 10_000 and all(len(code) == 10 for code in wbs)


def test_what_leaves_the_file_and_what_is_dropped(tmp_path):
    text = xer_text(
        [todo("ZONE-A1", task_name="Secret Plant Alpha")],
        rsrc=("ZONE-A1",),
        resources=({"rsrc_id": "R1", "rsrc_short_name": "JDOE", "rsrc_name": "John Doe", "email_addr": "j@x.io"},),
        wbs=({"wbs_id": "10", "proj_id": "1", "wbs_short_name": "WBS-SECRET", "wbs_name": "Reactor hall"},),
        project={"proj_short_name": "ACME-PLANT"},
        header="23.12\t2026-03-02\tProject\tjsmith\tJohn Smith\tdb_prod",
    )
    extra = "%T\tUDFVALUE\n%F\tudf_type_id\tfk_id\tudf_text\n%R\t1\t1\tConfidential memo\n"
    extra += "%T\tTASKMEMO\n%F\tmemo_id\ttask_id\ttask_memo\n%R\t1\t1\t<html>budget overrun</html>\n"
    text = text.replace("%E", extra + "%E")  # before the end line: nothing after %E is read
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


def test_check_on_missing_path_exits_two(tmp_path, capsys):
    """AUDIT-APP-09: a usage error is `xerscope: <message>` on stderr and exit 2 (1 is --fail-on)."""
    with pytest.raises(SystemExit) as caught:
        cli.main(["check", str(tmp_path / "nope.xer")])
    assert caught.value.code == 2
    out, err = capsys.readouterr()
    assert err == f"xerscope: {tmp_path / 'nope.xer'}: no such file or folder\n" and out == ""
    assert "exit 2" in cli._expand.__doc__


def test_standard_pointing_to_a_directory_is_refused(tmp_path, capsys):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    with pytest.raises(SystemExit) as caught:
        cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path)])
    assert caught.value.code == 2 and "unknown standard" in capsys.readouterr().err


def test_standard_through_symlink_and_dotdot_loads(tmp_path):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "s.toml").write_text(HEAD + '[[metric]]\nid = "M"\nname = "m"\nrule = "constraints"\n')
    (tmp_path / "sub").mkdir()
    link = tmp_path / "sub" / "link.toml"
    link.symlink_to(tmp_path / "s.toml")
    assert cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(link)]) == 0
    assert cli.main(["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path / "sub" / ".." / "s.toml")]) == 0
    assert load_standard(link).id == "X"


def clean_exit(capsys, argv: list[str]) -> str:
    """Runs the CLI, asserts exit 2 with one `xerscope: ...` line on stderr, returns that line."""
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("xerscope: ") and err.count("\n") == 1 and "Traceback" not in err, err
    return err


def test_invalid_standard_file_is_a_clean_cli_error(tmp_path, capsys):
    """AUDIT-APP-10: an invalid --standard file is a message naming the file, not a ValueError traceback."""
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "bad.toml").write_text(HEAD)
    err = clean_exit(capsys, ["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path / "bad.toml")])
    assert err == "xerscope: bad.toml: no [[metric]] defined\n"


def test_missing_baseline_file_is_a_clean_cli_error(tmp_path, capsys):
    """AUDIT-APP-10: a missing --baseline file is a message, not a FileNotFoundError traceback."""
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    err = clean_exit(capsys, ["check", str(tmp_path / "a.xer"), "--baseline", str(tmp_path / "nope.xer")])
    assert "nope.xer" in err


def test_a_broken_xer_is_a_clean_cli_error(tmp_path, capsys):
    (tmp_path / "a.xer").write_text("not an XER\n")
    err = clean_exit(capsys, ["info", str(tmp_path / "a.xer")])
    assert "a.xer" in err


def test_expect_with_malformed_csv_is_a_clean_cli_error(tmp_path, capsys):
    """AUDIT-APP-11: --expect with a malformed CSV names the file, no pandas ParserError traceback."""
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    bad = tmp_path / "bad.csv"
    bad.write_text('id,found,total\n"P6-01,1,2\nx,y\n')
    err = clean_exit(capsys, ["check", str(tmp_path / "a.xer"), "--expect", str(bad)])
    assert err.startswith(f"xerscope: {bad}: not a readable CSV: ")


def test_expect_with_non_numeric_count_is_a_clean_cli_error(tmp_path, capsys):
    """AUDIT-APP-11: --expect with a non-numeric count names the file, no ArrowInvalid traceback."""
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    bad = tmp_path / "bad.csv"
    bad.write_text("id,found,total\nP6-01,abc,2\n")
    err = clean_exit(capsys, ["check", str(tmp_path / "a.xer"), "--expect", str(bad)])
    assert err.startswith(f"xerscope: {bad}: found and total must be whole numbers: ")


def test_expect_without_the_columns_exits_two(tmp_path, capsys):
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "bad.csv").write_text("id,n\nP6-01,1\n")
    err = clean_exit(capsys, ["check", str(tmp_path / "a.xer"), "--expect", str(tmp_path / "bad.csv")])
    assert err == f"xerscope: {tmp_path / 'bad.csv'}: columns found, total missing\n"


def test_flagged_file_name_survives_a_metric_id_with_a_slash(tmp_path, capsys):
    """AUDIT-APP-12: a metric id with '/' is refused on load (the id names the --flagged file), so
    nothing is written outside the --flagged folder and the message names the file and the key."""
    (tmp_path / "a.xer").write_text(xer_text([todo("A1")]))
    (tmp_path / "s.toml").write_text(HEAD + '[[metric]]\nid = "sub/M"\nname = "m"\nrule = "missing_logic"\n')
    argv = ["check", str(tmp_path / "a.xer"), "--standard", str(tmp_path / "s.toml"), "--flagged", str(tmp_path / "fl")]
    err = clean_exit(capsys, argv)
    assert err == "xerscope: s.toml: metric #1 (sub/M): id 'sub/M': letters, digits, '.', '_' and '-' only\n"
    assert not (tmp_path / "fl").exists() and list(tmp_path.rglob("*.csv")) == []


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
