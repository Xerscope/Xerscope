"""xerscope against a P6 Professional 26.8 Check Schedule report and F9 log, on a synthetic project.

CHECKSCHED is a made-up project of 14 activities and 18 relationships, built so that every section
of the Check Schedule report lists something. It was imported into P6 Professional 26.8, scheduled
(F9, "Log to file"), checked (Tools > Check Schedule, every check, x = 352 h, no baseline assigned so
the project is its own baseline) and exported again. ``_snapshot`` rebuilds that export: each value
below is the one P6 wrote after F9. The expected counts and lists are those of P6's report and log.
"""

import pandas as pd
import pytest
from xerkit import clndr_data, snap

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric

MON_FRI_0800_1600 = clndr_data(range(2, 7), [("08:00", "16:00")])
CALENDAR = {
    "clndr_id": "16",
    "clndr_name": "Mon-Fri 08:00-16:00",
    "day_hr_cnt": "8",
    "week_hr_cnt": "40",
    "clndr_data": MON_FRI_0800_1600,
}


def _date(short: str | None) -> str:
    """'04-06 08' -> '2026-04-06 08:00'."""
    return "" if short is None else f"2026-{short}:00"


def _activity(code, kind, status, remaining, original, total_float, free_float, actual, early, late, planned, **extra):
    """One TASK row as P6 exported it: hours, then (start, finish) pairs written 'MM-DD HH'."""
    row = {
        "task_code": code,
        "task_type": kind,
        "status_code": status,
        "clndr_id": "16",
        "remain_drtn_hr_cnt": str(remaining),
        "target_drtn_hr_cnt": str(original),
        "total_float_hr_cnt": "" if total_float is None else str(total_float),
        "free_float_hr_cnt": "" if free_float is None else str(free_float),
        "act_start_date": _date(actual[0]),
        "act_end_date": _date(actual[1]),
        "early_start_date": _date(early[0]),
        "early_end_date": _date(early[1]),
        "late_start_date": _date(late[0]),
        "late_end_date": _date(late[1]),
        "target_start_date": _date(planned[0]),
        "target_end_date": _date(planned[1]),
        **extra,
    }
    if status != "TK_Complete":  # P6 writes the remaining dates of open work equal to its early / late dates
        row |= {
            "restart_date": row["early_start_date"],
            "reend_date": row["early_end_date"],
            "rem_late_start_date": row["late_start_date"],
            "rem_late_end_date": row["late_end_date"],
        }
    return row


NONE = (None, None)
ACTIVITIES = [
    _activity("CS1000", "TT_Mile", "TK_NotStart", 0, 0, -16, 0, NONE,
              ("04-06 08", "04-06 08"), ("04-02 08", "04-02 08"), ("04-06 08", "04-06 08"), driving_path_flag="Y"),
    _activity("CS1010", "TT_Task", "TK_Complete", 0, 40, None, None, ("03-02 08", "03-06 16"),
              ("04-06 08", "04-06 08"), ("04-02 08", "04-02 08"), ("03-02 08", "03-06 16"), phys_complete_pct="100"),
    _activity("CS1020", "TT_Task", "TK_Active", 64, 80, 32, 0, ("03-09 08", None),
              ("04-06 08", "04-15 16"), ("04-10 08", "04-21 16"), ("03-09 08", "03-20 16")),
    _activity("CS1030", "TT_Task", "TK_Active", 32, 40, -16, 0, ("03-16 08", None),
              ("06-29 08", "07-02 16"), ("06-25 08", "06-30 16"), ("03-16 08", "03-20 16"), driving_path_flag="Y"),
    _activity("CS1040", "TT_Task", "TK_NotStart", 40, 40, -16, 0, NONE,
              ("06-22 08", "06-26 16"), ("06-18 08", "06-24 16"), ("06-22 08", "06-26 16"), driving_path_flag="Y"),
    _activity("CS1050", "TT_Task", "TK_NotStart", 400, 400, 32, 0, NONE,
              ("04-16 08", "06-24 16"), ("04-22 08", "06-30 16"), ("04-16 08", "06-24 16")),
    _activity("CS1060", "TT_Task", "TK_NotStart", 40, 40, 0, 0, NONE,
              ("06-01 08", "06-05 16"), ("06-01 08", "06-05 16"), ("06-01 08", "06-05 16"),
              cstr_type="CS_MANDSTART", cstr_date="2026-06-01 08:00"),
    _activity("CS1070", "TT_Task", "TK_NotStart", 40, 40, 296, 312, NONE,
              ("05-04 08", "05-08 16"), ("06-24 08", "06-30 16"), ("05-04 08", "05-08 16"),
              cstr_type="CS_MSOA", cstr_date="2026-05-04 08:00"),
    _activity("CS1080", "TT_Task", "TK_NotStart", 40, 40, 32, 48, NONE,
              ("06-18 08", "06-24 16"), ("06-24 08", "06-30 16"), ("06-18 08", "06-24 16")),
    _activity("CS1090", "TT_Task", "TK_NotStart", 40, 40, 392, 0, NONE,
              ("04-16 08", "04-22 16"), ("06-24 08", "06-30 16"), ("04-16 08", "04-22 16")),
    _activity("CS1100", "TT_Task", "TK_NotStart", 8, 8, 424, 440, NONE,
              ("04-16 08", "04-16 16"), ("06-30 08", "06-30 16"), ("04-16 08", "04-16 16")),
    _activity("CS1110", "TT_Task", "TK_NotStart", 40, 40, 392, 408, NONE,
              ("04-16 08", "04-22 16"), ("06-24 08", "06-30 16"), ("04-16 08", "04-22 16")),
    _activity("CS1120", "TT_Task", "TK_Active", 40, 40, 456, 472, ("04-08 08", None),
              ("04-06 08", "04-10 16"), ("06-24 08", "06-30 16"), ("04-08 08", "04-14 16")),
    _activity("CS1999", "TT_FinMile", "TK_NotStart", 0, 0, -16, 0, NONE,
              ("07-02 16", "07-02 16"), ("06-30 16", "06-30 16"), ("07-02 16", "07-02 16"), driving_path_flag="Y"),
]  # fmt: skip
LINKS = [
    ("CS1000", "CS1010", "FS", 0),
    ("CS1010", "CS1020", "FS", 0),
    ("CS1010", "CS1040", "FS", 600),
    ("CS1040", "CS1030", "FS", 0),
    ("CS1020", "CS1050", "FS", 0),
    ("CS1050", "CS1060", "SS", -8),
    ("CS1020", "CS1070", "FS", 0),
    ("CS1050", "CS1080", "FF", 0),
    ("CS1020", "CS1090", "FS", 0),
    ("CS1090", "CS1100", "SS", 0),
    ("CS1020", "CS1110", "FS", 0),
    ("CS1010", "CS1120", "FS", 0),
    ("CS1030", "CS1999", "FS", 0),
    ("CS1060", "CS1999", "FS", 0),
    ("CS1070", "CS1999", "FS", 0),
    ("CS1080", "CS1999", "FS", 0),
    ("CS1100", "CS1999", "FS", 0),
    ("CS1120", "CS1999", "FS", 0),
]
PROJECT = {
    "proj_short_name": "CHECKSCHED",
    "clndr_id": "16",
    "plan_start_date": "2026-03-02 08:00",
    "plan_end_date": "2026-06-30 16:00",  # Must Finish By: the source of the negative float
    "scd_end_date": "2026-07-02 16:00",
    "critical_drtn_hr_cnt": "0",
}
SCHED = {
    "sched_retained_logic": "Y",
    "sched_progress_override": "N",
    "sched_lag_early_start_flag": "Y",
    "sched_use_expect_end_flag": "N",
    "sched_float_type": "FT_FF",
    "sched_calendar_on_relationship_lag": "rcal_Successor",
    "sched_outer_depend_type": "SD_Both",
}

# Check Summary of the report: found / total per line (BEI: completed / baseline activities).
REPORT_COUNTS = {
    "P6-01": (3, 13),  # Logic
    "P6-02": (1, 13),  # Hard Constraints
    "P6-03": (1, 13),  # Soft Constraints
    "P6-04": (1, 11),  # Large Durations
    "P6-05": (1, 18),  # Long Lags
    "P6-06": (4, 13),  # Large Float
    "P6-07": (15, 18),  # Relationship Type
    "P6-08": (1, 18),  # Positive Lags
    "P6-09": (1, 18),  # Negative Lags
    "P6-10a": (0, 13),  # Invalid Progress Before Data Date
    "P6-10b": (1, 13),  # Invalid Progress After Data Date
    "P6-11": (12, 12),  # Resources/Cost
    "P6-12": (2, 11),  # Late Activities
    "P6-13": (1, 12),  # BEI
    "P6-14": (4, 13),  # Negative Float
    "P6-15": (2, 14),  # Out of Sequence
    "P6-16": (1, 14),  # Dangling Start Activities
    "P6-17": (1, 14),  # Dangling Finish Activities
}
# The report's detail lists: Activity IDs, or (predecessor, successor) for relationships.
REPORT_LISTS = {
    "P6-01": {"CS1000", "CS1110", "CS1999"},
    "P6-02": {"CS1060"},
    "P6-03": {"CS1070"},
    "P6-04": {"CS1050"},
    "P6-05": {("CS1010", "CS1040")},
    "P6-06": {"CS1090", "CS1100", "CS1110", "CS1120"},
    "P6-07": {("CS1050", "CS1080"), ("CS1050", "CS1060"), ("CS1090", "CS1100")},
    "P6-08": {("CS1010", "CS1040")},
    "P6-09": {("CS1050", "CS1060")},
    "P6-10a": set(),
    "P6-10b": {"CS1120"},
    "P6-11": {f"CS1{n:02d}0" for n in range(1, 13)},
    "P6-12": {"CS1020", "CS1030"},
    "P6-14": {"CS1000", "CS1030", "CS1040", "CS1999"},
    "P6-15": {("CS1000", "CS1010"), ("CS1040", "CS1030")},
    "P6-16": {"CS1080"},
    "P6-17": {"CS1090"},
}
# Finish Variance (hour) of Late Activities, as the report prints it (negative = late).
REPORT_FINISH_VARIANCE_HOURS = {"CS1020": -144, "CS1030": -592}
# The F9 log: activities per warning or exception.
LOG_LISTS = {
    "INT-02": {"CS1010", "CS1030"},  # Out-of-sequence activities
    "INT-04": set(),  # (no Errors section entries)
    "INT-05": {"CS1000", "CS1110", "CS1999"},  # Activities without predecessors / without successors
    "INT-06": {"CS1120"},  # Activities with Actual Dates > Data Date
    "INT-07": set(),  # Activities with unsatisfied constraints
    "INT-08": set(),  # Activities with unsatisfied relationships
}

STANDARDS = builtin_standards()


@pytest.fixture(scope="module")
def checksched():
    snapshot = snap(
        ACTIVITIES,
        LINKS,
        data_date="2026-04-06 08:00",
        project=PROJECT,
        sched=SCHED,
        calendars=[CALENDAR],
        header="26.8\t2026-11-04",
    )
    return AnalysisContext(snapshot, baseline=Baseline.planned(snapshot))


def _listed(result) -> set:
    flagged = result.flagged
    if "predecessor" in flagged:  # P6-15: one row per activity and predecessor
        return set(zip(flagged["predecessor"], flagged["task_code"], strict=True))
    if "pred_code" in flagged:
        return set(zip(flagged["pred_code"], flagged["succ_code"], strict=True))
    return set(flagged["task_code"]) if "task_code" in flagged else set()


def test_the_p6_standard_has_the_lines_of_the_report():
    assert [metric.id for metric in STANDARDS["P6"].metrics] == list(REPORT_COUNTS)


@pytest.mark.parametrize("metric_id", list(REPORT_COUNTS))
def test_check_schedule_counts_match_the_p6_26_report(checksched, metric_id):
    result = run_metric(STANDARDS["P6"][metric_id], checksched)
    assert (result.numerator, result.denominator) == REPORT_COUNTS[metric_id]


@pytest.mark.parametrize("metric_id", list(REPORT_LISTS))
def test_check_schedule_lists_match_the_p6_26_report(checksched, metric_id):
    result = run_metric(STANDARDS["P6"][metric_id], checksched)
    assert _listed(result) == REPORT_LISTS[metric_id]


def test_late_activities_variance_matches_the_report(checksched):
    result = run_metric(STANDARDS["P6"]["P6-12"], checksched)
    variance_wd = dict(zip(result.flagged["task_code"], result.flagged["finish_variance_wd"], strict=True))
    assert {code: -8 * days for code, days in variance_wd.items()} == REPORT_FINISH_VARIANCE_HOURS


def test_the_recalculation_reproduces_p6s_f9(checksched):
    result = run_metric(STANDARDS["INTEGRITY"]["INT-01"], checksched)
    assert result.numerator == 0 and result.denominator == 13


@pytest.mark.parametrize("metric_id", list(LOG_LISTS))
def test_integrity_lists_match_the_p6_26_scheduling_log(checksched, metric_id):
    result = run_metric(STANDARDS["INTEGRITY"][metric_id], checksched)
    flagged = result.flagged
    listed = set(flagged["task_code"]) if "task_code" in flagged else set()
    if "succ_code" in flagged:  # INT-08 lists relationships; the log lists their successors
        listed = set(flagged["succ_code"])
    assert listed == LOG_LISTS[metric_id]


def test_witness_is_one_project_on_one_calendar(checksched):
    snapshot = checksched.snapshot
    assert len(snapshot.activities) == 14 and len(snapshot.relationships) == 18
    assert set(snapshot.activities["clndr_id"].astype(str)) == {"16"}
    assert snapshot.data_date == pd.Timestamp("2026-04-06 08:00")
