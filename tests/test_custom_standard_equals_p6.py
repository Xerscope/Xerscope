"""A custom standard of generic rules, set like each P6 Check Schedule check, against that check.

What this file proves, check by check: the generic rule of ``analysis/rules.py`` with the parameters
``CUSTOM`` gives (read off the code of ``analysis/p6/check_schedule.py``) returns what the P6 check
returns, on the same snapshot: status, numerator, denominator, value, the flagged tasks (or links) and
the rows of the population behind the denominator. The expected values are the P6 check's own output,
not numbers written here. Cases: the 8 files of the demo series (baseline = first file) and schedules
built with ``xerkit`` for completed tasks, level of effort, milestones, links from another project of the
file (predecessor and successor), positive, negative and long lags, every constraint (primary, secondary,
on a started task), negative and large float, tasks with no resource, expense-only tasks, a baseline
(with a task absent from it, on-time, late and working-time-late finishes) and none.

A pair that differs fails; nothing is adjusted or marked expected-failure.

P6 checks with no generic equivalent (no parameter reproduces the population):

- P6-13 BEI: the denominator is every baseline task (check_schedule.py p6_13_bei), where ``bei`` counts only
  the baseline tasks due by the status date (``due_from = "baseline"``) or the schedule's own due tasks
  (``"snapshot"``); no parameter lifts the due-date filter.
- P6-15 Out of Sequence: the test reads the status of the predecessor (open FS predecessor, SS predecessor
  not started); no generic rule reads the other end of a link.
- P6-16 Dangling Start: the denominator is every task of the file while the numerator leaves out completed
  tasks, milestones and (option) started tasks; ``dangling`` applies ``exclude`` and drops started tasks
  from numerator and denominator alike, and has no way to keep a task out of the numerator only.
- P6-17 Dangling Finish: same denominator against numerator split, and ``ignore_soft_constraints`` /
  ``ignore_hard_constraints`` have no parameter in ``dangling``.
"""

import pytest
from rulekit import codes, links
from xerkit import FM, SECONDARY_CONSTRAINTS, SM, active, done, hours, snap, todo, with_second_project, xer_text

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric
from xerscope.analysis.standards import loads_standard
from xerscope.xer import build_snapshot, parse_text

P6 = builtin_standards()["P6"]

CUSTOM = loads_standard(
    """
[standard]
id = "EQP6"
name = "Generic rules set like the P6 Check Schedule"

[[metric]]
id = "EQ-01"
name = "Logic"
rule = "missing_logic"
target = "< 5%"
[metric.params]
exclude = ["complete"]
pred_exempt = ["started"]
succ_exempt = []
external_passes = true
dangling = false

[[metric]]
id = "EQ-02"
name = "Hard constraints"
rule = "constraints"
target = "< 1%"
[metric.params]
types = ["CS_MANDSTART", "CS_MSO", "CS_MANDFIN", "CS_MEO"]
exclude = ["complete", "loe"]
ignore_start_when_started = true

[[metric]]
id = "EQ-03"
name = "Soft constraints"
rule = "constraints"
target = "< 5%"
[metric.params]
types = ["CS_MSOB", "CS_MSOA", "CS_MEOB", "CS_MEOA", "CS_ALAP"]
exclude = ["complete", "loe"]
ignore_start_when_started = true

[[metric]]
id = "EQ-04"
name = "Large durations"
rule = "duration"
target = "< 5%"
[metric.params]
field = "remaining"
op = ">"
value = 352
unit = "hours"
exclude = ["complete", "loe", "milestones"]

[[metric]]
id = "EQ-05"
name = "Long lags"
rule = "lag"
target = "< 5%"
[metric.params]
op = ">"
value = 352
unit = "hours"
links = "not_both_complete"
exclude_loe = false
exclude = []

[[metric]]
id = "EQ-06"
name = "Large float"
rule = "float"
target = "< 1%"
params = { op = ">", value = 352, unit = "hours", exclude = ["complete", "loe"] }

[[metric]]
id = "EQ-07"
name = "Relationship types"
rule = "relationship_type"
target = "> 90%"
params = { type = "FS", links = "not_both_complete", exclude_loe = false, exclude = [] }

[[metric]]
id = "EQ-08"
name = "Positive lags"
rule = "lag"
target = "< 5%"
[metric.params]
op = ">"
value = 0
unit = "hours"
links = "not_both_complete"
exclude_loe = false
exclude = []

[[metric]]
id = "EQ-09"
name = "Negative lags"
rule = "lag"
target = "< 1%"
[metric.params]
op = "<"
value = 0
unit = "hours"
links = "not_both_complete"
exclude_loe = false
exclude = []

[[metric]]
id = "EQ-10a"
name = "Invalid progress before the status date"
rule = "invalid_dates"
target = "< 1%"
[metric.params]
kind = "forecast"
exclude = ["loe", "complete_before_data_date"]
denominator = "population"
include_data_date = false
in_progress = "start"

[[metric]]
id = "EQ-10b"
name = "Invalid progress after the status date"
rule = "invalid_dates"
target = "< 1%"
[metric.params]
kind = "actual"
exclude = ["loe", "complete_before_data_date"]
denominator = "population"
include_data_date = false

[[metric]]
id = "EQ-11"
name = "Resource / cost"
rule = "no_resource"
target = "< 1%"
params = { exclude = ["milestones", "loe"], expenses_count = true }

[[metric]]
id = "EQ-12"
name = "Late activities"
rule = "late_vs_baseline"
target = "< 5%"
params = { exclude = ["complete", "milestones", "loe"], tolerance_hours = 0, no_baseline = "planned" }

[[metric]]
id = "EQ-14"
name = "Negative float"
rule = "float"
target = "< 1%"
params = { op = "<", value = 0, unit = "hours", exclude = ["complete", "loe"] }
""",
    "eq-p6.toml",
)

# P6 check -> the custom metric set like it
EQUIVALENT = {
    "P6-01": "EQ-01",
    "P6-02": "EQ-02",
    "P6-03": "EQ-03",
    "P6-04": "EQ-04",
    "P6-05": "EQ-05",
    "P6-06": "EQ-06",
    "P6-07": "EQ-07",
    "P6-08": "EQ-08",
    "P6-09": "EQ-09",
    "P6-10a": "EQ-10a",
    "P6-10b": "EQ-10b",
    "P6-11": "EQ-11",
    "P6-12": "EQ-12",
    "P6-14": "EQ-14",
}

# --- schedules built for the notions -------------------------------------------------------------

BASELINE_END = "2026-03-13 17:00"
BASELINE_ENDS = {
    "T02": "2026-03-12 17:00",  # forecast a day after its baseline finish
    "T03": "2026-03-13 16:00",  # one working hour late
    "T04": "2026-03-16 17:00",  # forecast before its baseline finish
    "T17": "2026-03-13 16:00",  # 10 h calendar: one working hour late
    "T18": "2026-03-12 16:00",  # 7-day calendar: one working day late
}
NOT_IN_BASELINE = ("T19", "T20", "NS_PAST")


def _mixed_tasks() -> list[dict]:
    """One task per notion the checks read; the comment names it."""
    return [
        done("DONE_OLD"),  # finished before the status date
        done("DONE_LATE", act_end_date="2026-03-05 17:00"),  # actual finish after the status date
        done("DONE_CSTR", cstr_type="CS_MANDFIN", cstr_date="2026-02-13 17:00"),  # completed, hard constraint
        active("ACT", restart_date="2026-02-25 08:00"),  # remaining early start before the status date
        active("ACT_OK", restart_date="2026-03-03 08:00"),
        active("ACT_FUT", act_start_date="2026-03-04 08:00", cstr_type="CS_MSO", cstr_date="2026-03-04 08:00"),
        todo("NS_PAST", early_start_date="2026-02-24 08:00"),  # not started, forecast start before the status date
        todo(
            "LOE", task_type="TT_LOE", total_float_hr_cnt="400", cstr_type="CS_MANDSTART", cstr_date="2026-03-02 08:00"
        ),
        todo("SM", **SM),  # start milestone
        todo("FM", total_float_hr_cnt="-8", **FM),  # finish milestone, negative float
        todo("T01"),
        todo("T02", total_float_hr_cnt="400", **hours(400)),  # large float and duration
        todo("T03", total_float_hr_cnt="352", **hours(352)),  # exactly at the limit: not above it
        todo("T04", total_float_hr_cnt="-16", **hours(353)),  # negative float, one hour above the limit
        todo("T05", cstr_type="CS_MANDSTART", cstr_date="2026-03-02 08:00"),
        todo("T06", cstr_type="CS_MSO", cstr_date="2026-03-02 08:00"),
        todo("T07", cstr_type="CS_MANDFIN", cstr_date="2026-03-13 17:00"),
        todo("T08", cstr_type="CS_MEO", cstr_date="2026-03-13 17:00"),
        todo("T09", cstr_type="CS_MSOA", cstr_date="2026-03-02 08:00"),
        todo("T10", cstr_type="CS_MSOB", cstr_date="2026-03-02 08:00"),
        todo("T11", cstr_type="CS_MEOA", cstr_date="2026-03-13 17:00"),
        todo("T12", cstr_type="CS_MEOB", cstr_date="2026-03-13 17:00"),
        todo("T13", cstr_type="CS_ALAP"),
        todo("T14", **SECONDARY_CONSTRAINTS),  # primary and secondary, both soft
        todo("T15", cstr_type2="CS_MANDFIN", cstr_date2="2026-03-13 17:00"),  # only the secondary is hard
        active(
            "T16", cstr_type="CS_MSO", cstr_date="2026-02-23 08:00", cstr_type2="CS_MEO", cstr_date2="2026-03-13 17:00"
        ),
        todo("T17", clndr_id="C10", early_end_date="2026-03-13 18:00"),
        todo("T18", clndr_id="C7D", early_end_date="2026-03-13 16:00"),
        todo("T19", total_float_hr_cnt="", target_end_date="2026-03-10 17:00"),  # no float; no baseline: planned finish
        todo("T20", target_end_date=""),  # no baseline, no planned finish
    ]


MIXED_LINKS = [
    ("DONE_OLD", "DONE_CSTR", "FS", 0),  # between two completed tasks
    ("DONE_OLD", "T01", "FS", 400),  # long lag out of a completed task
    ("T01", "T02", "FS", 8),  # positive lag
    ("T02", "T03", "FS", -8),  # lead
    ("T03", "T04", "SS", 0),
    ("T04", "T05", "FF", 16),
    ("T05", "T06", "SF", 0),
    ("T06", "DONE_LATE", "FS", 0),  # open task into a completed one
    ("ACT", "T07", "FS", 0),
    ("T07", "T08", "FS", 353),  # one hour above the long-lag limit
    ("T08", "T09", "FS", 352),  # at the limit
    ("SM", "T10", "FS", 0),
    ("T11", "FM", "FS", 0),
    ("LOE", "T12", "FS", 0),
    ("T12", "LOE", "FF", 0),
    ("T13", "T14", "SS", 4),
    ("T14", "T15", "FS", 0),
    ("T15", "T16", "FF", -4),
    ("T16", "T17", "FS", 0),
    ("T17", "T18", "SS", 0),
    ("T18", "T19", "SF", 8),
    ("ACT_OK", "ACT_FUT", "FS", 0),
    ("NS_PAST", "ACT_OK", "FS", 0),
    ("100", "T13", "FS", 8, "2"),  # predecessor in another project of the file
    ("100", "T19", "SS", 0, "2"),
    ("999", "T14", "FS", 8, "2"),  # predecessor in a project that is not in the file: dropped
]


def _inject_external_successor(text: str, pred_task_id: str, succ_task_id: str) -> str:
    """A TASKPRED row of project 2 whose predecessor is a task of project 1 (xerkit writes only project 1 rows)."""
    lines = text.splitlines()
    header = lines.index("%T\tTASKPRED") + 1
    columns = lines[header].split("\t")[1:]
    row = {
        "task_pred_id": "900",
        "task_id": succ_task_id,
        "pred_task_id": pred_task_id,
        "proj_id": "2",
        "pred_proj_id": "1",
        "pred_type": "PR_FS",
        "lag_hr_cnt": "0",
    }
    end = header + 1
    while lines[end].startswith("%R"):
        end += 1
    lines.insert(end, "%R\t" + "\t".join(row.get(column, "") for column in columns))
    return "\n".join(lines) + "\n"


def _mixed_snapshot():
    """The notions above, a project 2 task Y1 (id 100) feeding T13 and T19, and T01 feeding Y1 (external successor)."""
    ids = {task["task_code"]: str(index) for index, task in enumerate(_mixed_tasks(), start=1)}
    resourced = ["T01", "T02", "T04", "T05", "T07", "DONE_OLD", "ACT", "ACT_OK", "T18"]
    text = xer_text(_mixed_tasks(), MIXED_LINKS, rsrc=resourced, costs=["T03", "T06"])  # T03, T06: expense only
    text = with_second_project(text, "P2", ["Y1"], "2026-03-02 08:00")
    text = _inject_external_successor(text, ids["T01"], "100")
    return build_snapshot(parse_text(text, source="mixed.xer"), project_code="T")


def _baseline_of_mixed() -> Baseline:
    tasks = [
        todo(task["task_code"], early_end_date=BASELINE_ENDS.get(task["task_code"], BASELINE_END))
        for task in _mixed_tasks()
        if task["task_code"] not in NOT_IN_BASELINE
    ]
    return Baseline.from_snapshot(snap(tasks))


LOGIC_TASKS = [
    done("D0"),
    active("S1"),
    todo("M0", task_type="TT_Mile", target_drtn_hr_cnt="0"),
    todo("A"),
    todo("B"),
    todo("C"),
    todo("F", task_type="TT_FinMile", target_drtn_hr_cnt="0"),
    todo("E"),
]
LOGIC_LINKS = [
    ("D0", "A", "FS", 0),
    ("A", "B", "SS", 8),
    ("B", "F", "FS", 0),
    ("M0", "C", "FS", 0),
    ("S1", "B", "FS", 0),
    ("X9", "E", "FS", 0, "2"),  # E: external predecessor, no successor
]

CASES = [f"demo-{index}" for index in range(8)] + ["mixed", "mixed-no-baseline", "logic", "no-links"]


def build_case(name: str, store):
    """(snapshot, baseline) of a case; the demo files read the first file as baseline, as rulekit.run_on_store."""
    if name.startswith("demo-"):
        index = int(name.removeprefix("demo-"))
        return store[index], Baseline.from_snapshot(store.first)
    if name == "mixed":
        return _mixed_snapshot(), _baseline_of_mixed()
    if name == "mixed-no-baseline":
        return _mixed_snapshot(), None
    if name == "logic":
        return snap(LOGIC_TASKS, LOGIC_LINKS), None
    if name == "no-links":
        return snap([todo("A"), todo("B", **hours(400))]), Baseline.from_snapshot(snap([todo("A"), todo("B")]))
    raise KeyError(name)


# --- the comparison --------------------------------------------------------------------------------


def _rows(frame) -> list:
    """Task codes of a frame of tasks, or (predecessor, successor) pairs of a frame of links."""
    if frame is None or frame.empty:
        return []
    if "task_code" in frame:
        return sorted(frame["task_code"])
    return sorted(zip(frame["pred_code"], frame["succ_code"], strict=True))


def _read(result) -> dict:
    return {
        "status": result.status,
        "numerator": result.numerator,
        "denominator": result.denominator,
        "value": result.value,
        "flagged": codes(result) or links(result),
        "population": _rows(result.checked),
    }


def test_the_equivalence_table_names_every_p6_check_but_four():
    """18 lines in p6.toml: the 14 of the table here and the 4 of the module docstring."""
    ids = [metric.id for metric in P6.metrics]
    assert sorted(set(ids) - set(EQUIVALENT)) == ["P6-13", "P6-15", "P6-16", "P6-17"]
    assert len(ids) == 18


@pytest.mark.oracle("property")
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("control", list(EQUIVALENT))
def test_the_generic_rule_set_like_the_p6_check_gives_its_result(control, case, store):
    snapshot, baseline = build_case(case, store)
    context = AnalysisContext(snapshot, baseline=baseline)
    expected = _read(run_metric(P6[control], context))
    got = _read(run_metric(CUSTOM[EQUIVALENT[control]], context))
    assert got == expected
