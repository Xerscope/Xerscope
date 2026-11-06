"""Anonymised XER and tables: nothing of the original comes out, every result stays the same.

Same results = on the demo series and on the pinned third-party P6 exports, the anonymised
file gives the same activity dates, floats, durations and progress (matched through the new
Activity IDs), the same CPM differences against the stored dates, and the same status,
counts and flagged items for every check of every built-in standard.
"""

import hashlib
import hmac
import io
import re
import secrets
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from conftest import REFERENCE_HINT, missing
from xerkit import DD, done, todo, xer_text

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.analysis.cpm import compare_with_stored
from xerscope.analysis.evm import evm_series
from xerscope.analysis.progress import ppc_series
from xerscope.anonymize import Anonymizer, LeakError
from xerscope.store import SnapshotStore
from xerscope.xer import build_snapshot, load_snapshot
from xerscope.xer.parser import parse_bytes, parse_text, read_xer

STANDARDS = builtin_standards()
REFERENCE = Path(__file__).parent / "reference" / "data"
REFERENCE_FILES = [
    "pv/20-kW-residential-pv-p6.xer",  # P6 25.12
    "p6viewer/TERMINAL BUILDING-AIRPORT.xer",  # P6 5.0, resources, activity codes
    "xereditor/sample.xer",  # P6 20.12
    "p6-heldout/validation/held-out/H16/import/H16-all.xer",  # P6 23.12, 12 projects
]
SAME_COLUMNS = ["status", "start", "finish", "total_float_hr_cnt", "free_float_hr_cnt", "remain_drtn_hr_cnt",
                "target_drtn_hr_cnt", "pct_complete", "labor_budget_hr", "labor_actual_hr", "is_critical"]  # fmt: skip


def anonymised(raws):
    anonymizer = Anonymizer.from_raws(raws)
    return anonymizer, [load_snapshot(anonymizer.xer(raw), name=f"anon{i}.xer") for i, raw in enumerate(raws)]


def check_rows(results, anonymizer=None):
    rows = []
    for result in results:
        flagged = result.flagged
        if anonymizer is not None and not flagged.empty:
            flagged = anonymizer.frame(flagged)
        links = zip(flagged.get("pred_code", []), flagged.get("succ_code", []), strict=True)
        codes = sorted(f"{pred}->{succ}" for pred, succ in links) or sorted(map(str, flagged.get("task_code", [])))
        rows.append((result.metric.id, result.status, result.numerator, result.denominator, codes))
    return rows


def assert_same_snapshot(anonymizer, original, copy):
    mapped = original.activities.assign(task_code=original.activities["task_code"].map(anonymizer.codes["A"]))
    left = mapped.set_index("task_code")[SAME_COLUMNS].sort_index()
    right = copy.activities.set_index("task_code")[SAME_COLUMNS].sort_index()
    pd.testing.assert_frame_equal(left, right, check_index_type=False)
    assert (original.data_date, original.finish_date) == (copy.data_date, copy.finish_date)
    assert len(compare_with_stored(original)) == len(compare_with_stored(copy))


def assert_same_checks(anonymizer, original, copy, store=None, copy_store=None, baseline=None, copy_baseline=None):
    for standard in STANDARDS.values():
        before = run_standard(standard, AnalysisContext(original, store, baseline))
        after = run_standard(standard, AnalysisContext(copy, copy_store, copy_baseline))
        assert check_rows(before, anonymizer) == check_rows(after), standard.id


def test_demo_series_gives_the_same_results(sample_dir):
    paths = sorted(sample_dir.glob("*.xer"))
    raws = [read_xer(path) for path in paths]
    anonymizer, copies = anonymised(raws)
    store, copy_store = SnapshotStore.from_paths(paths), SnapshotStore(copies)
    baseline, copy_baseline = Baseline.from_snapshot(store.first), Baseline.from_snapshot(copy_store.first)
    for original, copy in zip(store, copy_store, strict=True):
        assert_same_snapshot(anonymizer, original, copy)
        assert_same_checks(anonymizer, original, copy, store, copy_store, baseline, copy_baseline)
    numbers = ["pv_hr", "ev_hr", "ac_hr", "eac_hr", "spi"]
    pd.testing.assert_frame_equal(evm_series(store, baseline)[numbers], evm_series(copy_store, copy_baseline)[numbers])
    pd.testing.assert_series_equal(ppc_series(store)["ppc"], ppc_series(copy_store)["ppc"])


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_p6_exports_give_the_same_results(name):
    path = REFERENCE / name
    if not path.exists():
        missing("reference", REFERENCE_HINT)
    raw = read_xer(path)
    anonymizer, (copy,) = anonymised([raw])
    original = load_snapshot(path)
    assert len(copy.warnings) == len(original.warnings)
    assert_same_snapshot(anonymizer, original, copy)
    assert_same_checks(anonymizer, original, copy)


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_no_text_value_of_the_original_is_left(name):
    """Searched as substrings of the whole file, not only as whole fields."""
    path = REFERENCE / name
    if not path.exists():
        missing("reference", REFERENCE_HINT)
    raw = read_xer(path)
    anonymizer = Anonymizer.from_raws([raw])
    text = anonymizer.xer(raw).decode("cp1252" if raw.encoding.startswith("cp1252") else "utf-8")
    names = set(raw.table("TASK")["task_name"]) | set(raw.table("PROJWBS")["wbs_name"]) | set(raw.header[3:6])
    assert [value for value in names if len(value) >= 4 and value in text and value != "dbxDatabaseNoName"] == []
    generated = {"Activity", "WBS", "Resource", "Role", "Calendar", "Project", "ANON"}  # words of the new labels
    assert not [value for value in anonymizer.secrets_ if len(value) >= 6 and value in text and value not in generated]


def _file(
    tasks,
    preds=(),
    header="ERMHDR\t23.12\t2026-03-02\tProject\tjdoe\tJane Doe\tACME_PROD\tProject Management\tEUR",
    **kw,
):
    lines = xer_text(tasks, preds, **kw).splitlines()
    return "\n".join([header, *lines[1:]]) + "\n"


def test_header_loses_user_and_database():
    raw = parse_text(_file([todo("A1")]), source="Site Nord - planning.xer")
    out = Anonymizer.from_raws([raw]).xer(raw).decode()
    assert out.splitlines()[0].split("\t") == [
        "ERMHDR", "23.12", "2026-03-02", "Project", "ANON", "ANON", "dbxDatabaseNoName", "Project Management", "EUR",
    ]  # fmt: skip
    assert "jdoe" not in out and "Jane Doe" not in out and "ACME_PROD" not in out and "Site Nord" not in out


def test_codes_follow_the_activity_across_files_whatever_their_order():
    week_1 = parse_text(_file([todo("FDN-020"), todo("FDN-010")]), source="w1.xer")
    week_2 = parse_text(_file([todo("FDN-010"), todo("ROOF-1")], data_date="2026-03-09 08:00"), source="w2.xer")
    key = bytes(32)
    forward = Anonymizer.from_raws([week_1, week_2], key=key)
    backward = Anonymizer.from_raws([week_2, week_1], key=key)
    assert forward.codes["A"] == backward.codes["A"]
    assert set(forward.codes["A"]) == {"FDN-010", "FDN-020", "ROOF-1"}
    assert all(re.fullmatch(r"XA[0-9A-F]{12}", code) for code in forward.codes["A"].values())
    assert len(set(forward.codes["A"].values())) == 3
    names = parse_bytes(forward.xer(week_2)).table("TASK")[["task_code", "task_name"]].values.tolist()
    roof, fdn = forward.codes["A"]["ROOF-1"], forward.codes["A"]["FDN-010"]
    assert names == [[fdn, f"Activity {fdn}"], [roof, f"Activity {roof}"]]


def test_one_update_read_alone_gets_the_codes_of_the_whole_series():
    """Same session key: a download made from one file names an activity as one made from all."""
    week_1 = parse_text(_file([todo("FDN-020"), todo("FDN-010")]), source="w1.xer")
    week_2 = parse_text(_file([todo("FDN-010"), todo("ROOF-1")], data_date="2026-03-09 08:00"), source="w2.xer")
    key = secrets.token_bytes(32)
    series, alone = Anonymizer.from_raws([week_1, week_2], key=key), Anonymizer.from_raws([week_2], key=key)
    assert alone.codes["A"] == {code: series.codes["A"][code] for code in ("FDN-010", "ROOF-1")}
    other_session = Anonymizer.from_raws([week_2])
    assert set(other_session.codes["A"].values()).isdisjoint(alone.codes["A"].values())


def test_two_ids_on_one_new_code_are_refused(monkeypatch):
    from xerscope import anonymize

    monkeypatch.setitem(anonymize.WIDTH, "A", 1)  # 16 possible codes for 40 activities
    raw = parse_text(_file([todo(f"A{n}") for n in range(40)]), source="w.xer")
    with pytest.raises(anonymize.CodeClash):
        Anonymizer.from_raws([raw])


# Under this key the first draw of E1010 is XA69C305070C59: its hex digits spell the Activity ID C3050.
SPELLING_KEY = (488).to_bytes(32, "big")


def test_a_code_spelling_an_original_id_is_drawn_again():
    first = hmac.new(SPELLING_KEY, b"A:E1010", hashlib.sha256).hexdigest().upper()[:12]
    assert first == "69C305070C59"
    raw = parse_text(_file([todo("E1010"), todo("C3050")]), source="w.xer")
    anonymizer = Anonymizer.from_raws([raw], key=SPELLING_KEY)
    text = anonymizer.xer(raw).decode()
    assert "C3050" not in text and "E1010" not in text
    new = anonymizer.codes["A"]["E1010"]
    assert re.fullmatch(r"XA[0-9A-F]{12}", new) and new != "XA69C305070C59"


def test_an_original_code_inside_a_field_is_refused():
    raw = parse_text(_file([todo("E1010"), todo("C3050")]), source="w.xer")
    anonymizer = Anonymizer.from_raws([raw])
    origin = anonymizer.secrets_["C3050"]  # TASK.task_code or TASK.task_name (xerkit names it by its code)
    assert anonymizer.leaks(["XA69C305070C59", "Activity C3050"]) == {origin: 2}
    anonymizer.codes["A"]["E1010"] = "XA69C305070C59"  # as the first draw under SPELLING_KEY
    with pytest.raises(LeakError, match=origin):
        anonymizer.xer(raw)


def _original_codes_left(anonymizer, raw):
    """Original codes found inside the fields of the anonymised file that xerscope writes (kept
    fields are the original's own: enumerations, dates)."""
    out = parse_bytes(anonymizer.xer(raw))
    fields = {value for frame in out.tables.values() for value in frame.to_numpy().ravel()} - anonymizer.kept
    return [code for code in anonymizer.original_codes for value in fields if code in value]


def test_no_new_code_holds_an_original_value_whatever_the_key(sample_dir):
    """Demo series, 3,000 keys: six of them gave, on the first draw, a code spelling an original."""
    raws = [read_xer(path) for path in sorted(sample_dir.glob("*.xer"))]
    found = Anonymizer.from_raws(raws)
    for seed in range(3000):
        anonymizer = Anonymizer(key=seed.to_bytes(32, "big"), secrets_=found.secrets_)
        for kind, mapping in found.codes.items():
            for original in mapping:
                anonymizer.code(kind, original)
        for kind, mapping in anonymizer.codes.items():
            assert len(set(mapping.values())) == len(mapping), (seed, kind)
            for new in mapping.values():
                assert not anonymizer._holds_original(new), (seed, new)
    for seed in (488, 521, 1562):
        anonymizer = Anonymizer.from_raws(raws, key=seed.to_bytes(32, "big"))
        assert all(_original_codes_left(anonymizer, raw) == [] for raw in raws), seed


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_no_original_code_is_left_whatever_the_key(name):
    path = REFERENCE / name
    if not path.exists():
        missing("reference", REFERENCE_HINT)
    raw = read_xer(path)
    for seed in range(5):
        anonymizer = Anonymizer.from_raws([raw], key=seed.to_bytes(32, "big"))
        assert _original_codes_left(anonymizer, raw) == [], seed
        for mapping in anonymizer.codes.values():
            assert len(set(mapping.values())) == len(mapping)


def test_unknown_tables_and_columns_are_left_out_and_named():
    text = _file([todo("A1", wbs_id="")]).replace(
        "%E\n", "%T\tTASKMEMO\n%F\tmemo_id\ttask_memo\n%R\t1\tCall Jane re. crane\n%E\n"
    )
    raw = parse_text(text, source="x.xer")
    raw.tables["TASK"]["new_p6_column"] = "Crane hire by Smith Ltd"
    anonymizer = Anonymizer.from_raws([raw])
    out = parse_bytes(anonymizer.xer(raw))
    assert "TASKMEMO" not in out.tables and anonymizer.report.dropped_tables == {"TASKMEMO"}
    assert "TASK.new_p6_column" in anonymizer.report.emptied_columns
    assert "Call Jane" not in anonymizer.xer(raw).decode() and "Smith" not in anonymizer.xer(raw).decode()


def test_costs_are_zeroed_and_the_expense_kept():
    raw = parse_text(_file([todo("A1")], costs=["A1"]), source="x.xer")
    raw.tables["PROJCOST"]["target_cost"] = "1250.50"
    out = parse_bytes(Anonymizer.from_raws([raw]).xer(raw)).table("PROJCOST")
    assert out["target_cost"].tolist() == ["0"]


def test_diagnostic_costs_block_is_zeroed_as_the_extract_is():
    """The "Costs in the file" block of an anonymous download holds no amount: it reads as the
    anonymised XER does, every cost 0, row counts and "absent" kept."""
    from xerscope.app.diagnostic import costs_table

    text = _file(
        [todo("A1")],
        assign=[{"task_code": "A1", "rsrc_id": "900", "target_cost": "1250.50", "cost_per_qty": "25.75"}],
        costs=[{"task_code": "A1", "target_cost": "300.25"}],
    )
    raw = parse_text(text, source="x.xer")
    anonymizer = Anonymizer.from_raws([raw])
    plain = costs_table(build_snapshot(raw))
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames({"07_costs": plain}))) as archive:
        data = archive.read("07_costs.csv").decode("utf-8-sig")
    shown = pd.read_csv(io.StringIO(data))
    assert not {"1250.5", "25.75", "300.25"} & set(data.replace("\n", ",").split(","))
    extract = costs_table(build_snapshot(parse_bytes(anonymizer.xer(raw))))
    pd.testing.assert_frame_equal(shown.astype(object).fillna(""), extract.astype(object).fillna(""))
    assert shown["target_cost_total"].tolist() == [0.0, 0.0]


def test_diagnostic_ev_settings_block_renames_the_wbs_and_keeps_the_enumerations():
    from xerscope.analysis import builtin_standards
    from xerscope.app.diagnostic import diagnostic_frames

    p6 = builtin_standards()["P6"]

    wbs = [
        {
            "wbs_id": "10",
            "proj_id": "1",
            "wbs_short_name": "SECRETWBS",
            "wbs_name": "Secret works",
            "proj_node_flag": "N",
            "parent_wbs_id": "",
            "seq_num": "1",
            "ev_compute_type": "EC_Cmp_pct",
            "ev_etc_compute_type": "EE_PF_1",
            "ev_etc_user_value": "1",
        }
    ]
    raw = parse_text(_file([todo("A1", wbs_id="10")], wbs=wbs), source="x.xer")
    anonymizer = Anonymizer.from_raws([raw])
    plain = diagnostic_frames(build_snapshot(raw), None, p6, anonymous=True)  # as the Debug page builds the zip
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames(plain))) as archive:
        data = {name: archive.read(name).decode("utf-8-sig") for name in archive.namelist()}
    assert "SECRETWBS" not in "".join(data.values())
    shown = pd.read_csv(io.StringIO(data["08_ev_settings.csv"]))
    extract = diagnostic_frames(build_snapshot(parse_bytes(anonymizer.xer(raw))), None, p6)["08_ev_settings"]
    assert shown["wbs_code"].tolist() == extract["wbs_code"].tolist() != [""]
    assert shown["ev_etc_compute_type"].tolist() == ["EE_PF_1"] and shown["etc_technique"].tolist() == ["PF = 1"]


def test_calendar_data_with_unknown_words_is_refused():
    raw = parse_text(_file([todo("A1")]), source="x.xer")
    calendars = raw.tables["CALENDAR"]
    calendars["clndr_data"] = "(0||CalendarData()(Christmas at ACME))"
    with pytest.raises(LeakError, match="clndr_data"):
        Anonymizer.from_raws([raw]).xer(raw)


def test_a_table_with_original_text_is_refused():
    raw = parse_text(_file([todo("PUMP-7", task_name="Pump house")]), source="x.xer")
    anonymizer = Anonymizer.from_raws([raw])
    flagged = pd.DataFrame({"task_code": ["PUMP-7"], "task_name": ["Pump house"], "reason": ["Pump house"]})
    with pytest.raises(LeakError, match="TASK.task_name"):
        anonymizer.frame(flagged)  # "reason" is kept as written: here it carries a name


def test_flagged_csv_matches_check_on_the_anonymised_file():
    """What the app hands out for a check equals what xerscope finds in the anonymised file."""
    tasks = [done("A1"), todo("B2", early_start_date="2026-02-23 08:00"), todo("C3")]
    raw = parse_text(_file(tasks, [("A1", "B2", "PR_FS", 0)], data_date=DD), source="x.xer")
    anonymizer = Anonymizer.from_raws([raw])
    original, copy = load_snapshot(_file(tasks, [("A1", "B2", "PR_FS", 0)]).encode(), name="o.xer"), None
    copy = load_snapshot(anonymizer.xer(raw), name="a.xer")
    for standard in STANDARDS.values():
        for before, after in zip(
            run_standard(standard, AnalysisContext(original)),
            run_standard(standard, AnalysisContext(copy)),
            strict=True,
        ):
            if before.flagged.empty:
                continue
            shown = anonymizer.frame(before.flagged).reset_index(drop=True)
            expected = after.flagged.reset_index(drop=True)
            columns = [c for c in ("task_code", "task_name", "pred_code", "succ_code", "status") if c in shown.columns]
            pd.testing.assert_frame_equal(shown[columns], expected[columns], check_dtype=False)


def test_a_note_names_activities_and_files_by_their_new_names_only():
    """The notes of the rules hold an Activity ID or a file name; both are renamed, the rest is kept."""
    raw = parse_text(_file([todo("PUMP-7"), todo("PUMP-70")]), source="Plant-Alpha_2026-03-02.xer")
    anonymizer = Anonymizer.from_raws([raw])
    new = anonymizer.codes["A"]
    notes = pd.DataFrame(
        {
            "note": [
                "+600 wd on PUMP-7: forecast finish 2027-03-10 -> 2028-10-30",
                "29 of 29 activities matched in BL 2026-03-02 · Plant-Alpha_2026-03-02.xer",
                "no Must Finish By date",
                "",
            ]
        }
    )
    out = anonymizer.frame(notes)["note"].tolist()
    assert out[0] == f"+600 wd on {new['PUMP-7']}: forecast finish 2027-03-10 -> 2028-10-30"
    assert out[1] == "29 of 29 activities matched in BL 2026-03-02 · file.xer"
    assert out[2:] == ["no Must Finish By date", ""]
    assert "PUMP-70" not in "".join(out)


def test_the_sets_table_columns_come_out_with_new_codes():
    """pred_/succ_ WBS codes follow the WBS mapping, their status is kept, nothing else of the file is."""
    raw = parse_text(_file([todo("A1")]), source="x.xer")
    anonymizer = Anonymizer.from_raws([raw])
    wbs = "PLANT.CIVIL"
    anonymizer.wbs_paths[wbs] = "XW1.XW2"
    frame = pd.DataFrame(
        {
            "check_id": ["P6-07"],
            "set": ["counted"],
            "pred_code": ["A1"],
            "pred_wbs_code": [wbs],
            "pred_status": ["TK_NotStart"],
            "succ_status": ["TK_Active"],
        }
    )
    out = anonymizer.frame(frame)
    assert out["pred_code"][0] == anonymizer.codes["A"]["A1"]
    assert out["pred_wbs_code"][0] == "XW1.XW2"
    assert out[["check_id", "set", "pred_status", "succ_status"]].iloc[0].tolist() == [
        "P6-07",
        "counted",
        "TK_NotStart",
        "TK_Active",
    ]


def test_cost_amounts_of_the_earned_value_series_are_zero_in_anonymous_exports():
    """BAC 16500, PV 6600, EV 8000 are financial data: the anonymous CSV carries 0 for them and
    none of the raw amounts; the ratio stays (8000 / 6600 = 1.2121)."""
    week = {"early_start_date": "2026-03-02 08:00", "early_end_date": "2026-03-06 17:00"}
    assign = [{"task_code": "A", "rsrc_id": "R1", "rsrc_type": "RT_Labor", "target_qty": "100", "target_cost": "16500"}]
    text = xer_text([todo("A", **week)], assign=assign)
    baseline = Baseline.from_snapshot(build_snapshot(parse_text(text, source="b.xer")))
    update = build_snapshot(
        parse_text(xer_text([todo("A", **week, remain_drtn_hr_cnt="48", status_code="TK_Active",
                                  act_start_date="2026-03-02 08:00")], data_date="2026-03-04 08:00"), source="u.xer")
    )  # fmt: skip
    series = evm_series(SnapshotStore([update]), baseline)
    assert series.loc[0, "bac_cost"] == 16500 and series.loc[0, "pv_cost"] == pytest.approx(6600)
    assert series.loc[0, "ev_cost"] > 0
    anonymizer = Anonymizer.from_raws([parse_text(text, source="b.xer")])
    out = pd.read_csv(io.BytesIO(anonymizer.csv(series)))
    assert out[["bac_cost", "pv_cost", "ev_cost"]].iloc[0].tolist() == [0, 0, 0]
    assert out.loc[0, "spi_cost"] == pytest.approx(series.loc[0, "spi_cost"])
    raw_text = anonymizer.csv(series).decode("utf-8-sig")
    assert not re.search(r"16500|6600|8000", raw_text)


def test_diagnostic_block_09_holds_no_name_or_code():
    """Table names, counts and hour totals only: the anonymous zip is written, and no activity code or name of the
    file is in it."""
    from xerscope.analysis import Baseline, builtin_standards
    from xerscope.app.diagnostic import diagnostic_frames

    tasks = [todo("SECRETCODE1", task_name="Secret name", early_start_date="2026-03-02 08:00",
                  early_end_date="2026-03-06 17:00", target_work_qty="40")]  # fmt: skip
    raw = parse_text(_file(tasks, assign=[{"task_code": "SECRETCODE1", "rsrc_id": "900", "target_qty": "40"}]), "x.xer")
    snapshot = build_snapshot(raw)
    frames = diagnostic_frames(snapshot, Baseline.planned(snapshot), builtin_standards()["P6"], anonymous=True)
    block = {name: frame for name, frame in frames.items() if name.startswith("09_")}
    assert len(block) == 4 and not block["09_pv_labor_check"].empty
    with zipfile.ZipFile(io.BytesIO(Anonymizer.from_raws([raw]).zip_frames(block))) as archive:
        text = "".join(archive.read(name).decode("utf-8-sig") for name in archive.namelist())
    assert "SECRETCODE1" not in text and "Secret name" not in text and "TASKRSRC" in text


def test_diagnostic_block_09_is_written_when_the_file_defines_user_fields():
    """UDFTYPE.table_name holds P6 table names ("TASK"), the same words block 09 lists: an enumeration,
    not a secret of the file. The user's label stays out."""
    from xerscope.analysis import Baseline, builtin_standards
    from xerscope.app.diagnostic import diagnostic_frames

    tasks = [todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00", target_work_qty="40")]
    udftype = "\n".join(
        [
            "%T\tUDFTYPE",
            "%F\tudf_type_id\ttable_name\tudf_type_name\tudf_type_label\tlogical_data_type\tsuper_flag",
            "%R\t5001\tTASK\tSecret Field\tSecret label\tFT_TEXT\tN",
        ]
    )
    raw = parse_text(_file(tasks).replace("%T\tTASK\n", udftype + "\n%T\tTASK\n", 1), "x.xer")
    snapshot = build_snapshot(raw)
    frames = diagnostic_frames(snapshot, Baseline.planned(snapshot), builtin_standards()["P6"], anonymous=True)
    block = {name: frame for name, frame in frames.items() if name.startswith("09_")}
    with zipfile.ZipFile(io.BytesIO(Anonymizer.from_raws([raw]).zip_frames(block))) as archive:
        text = "".join(archive.read(name).decode("utf-8-sig") for name in archive.namelist())
    assert "UDFTYPE" in text and "TASK" in text
    assert "Secret label" not in text and "Secret Field" not in text


def test_csv_exports_write_hours_to_four_decimals():
    """Floats are written with CSV_FLOAT_FORMAT: a BAC summed from P6's minute-based hours (12345.999999)
    reads 12346.0000 and a gap of 1e-13 reads 0.0000, in the plain download, the anonymised CSV and the
    diagnostic zip alike. Dates and text are untouched."""
    from xerscope.anonymize import csv_bytes

    frame = pd.DataFrame({"data_date": ["2026-03-02 17:00:00"], "bac_hr": [12345.999999], "gap_hr": [6.9e-13]})
    plain = csv_bytes(frame).decode("utf-8-sig")
    assert plain.splitlines()[1] == "2026-03-02 17:00:00,12346.0000,0.0000"
    # the anonymised writers empty a text column they do not know (the date here): the numbers stay
    anonymizer = Anonymizer.from_raws([parse_text(_file([todo("A")]), "x.xer")])
    assert anonymizer.csv(frame).decode("utf-8-sig").splitlines()[1].endswith(",12346.0000,0.0000")
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames({"09_pv_labor_check": frame}))) as archive:
        text = archive.read("09_pv_labor_check.csv").decode("utf-8-sig")
    assert "12346.0000,0.0000" in text
