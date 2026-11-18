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


@pytest.mark.oracle("standard")
def test_the_generic_duration_rule_shows_the_same_funnel_as_p6_large_durations():
    """P6-04 "Large Durations" (Oracle P6 Check Schedule help, pages 101248 and 46282): "Tasks outside the
    duration limit. Counts: flagged / checked. Excludes: completed tasks, level of effort, milestones."
    The population is every task of the file, minus the completed, minus level of effort, minus milestones;
    a task is flagged when its remaining duration is above the limit (352 h in CUSTOM).

    By hand, five tasks (remaining duration in hours): DONE (completed, 0), LOE (level of effort, 400),
    MS (start milestone, 0), LONG (400), SHORT (80).

    - start: 5 tasks.
    - exclude completed: removes DONE, 4 left.
    - exclude level of effort: removes LOE (400 h would have been flagged), 3 left.
    - exclude milestones: removes MS, 2 left (LONG, SHORT).
    - flagged: LONG only (400 > 352; SHORT 80 is not): 1 / 2.

    The generic rule must show the same funnel as the P6 check: same start, same steps in the same order
    with the same labels, left and removed tasks. The ``source`` of a step is not compared: a generic rule
    does not have the exact Oracle sources of P6.
    """
    tasks = [
        done("DONE"),
        todo("LOE", task_type="TT_LOE", **hours(400)),
        todo("MS", **SM),
        todo("LONG", **hours(400)),
        todo("SHORT", **hours(80)),
    ]
    context = AnalysisContext(snap(tasks))
    p6 = run_metric(P6["P6-04"], context)
    generic = run_metric(CUSTOM["EQ-04"], context)

    by_hand = (5, [(["DONE"], 4), (["LOE"], 3), (["MS"], 2)])
    assert (p6.numerator, p6.denominator) == (1, 2)
    assert (generic.numerator, generic.denominator) == (1, 2)

    assert p6.funnel is not None
    assert generic.funnel is not None, "the generic rule gives no funnel"

    def read(funnel):
        return funnel.start, [(sorted(step.removed["task_code"]), step.left) for step in funnel.steps]

    assert read(p6.funnel) == by_hand
    assert read(generic.funnel) == by_hand
    assert [step.label for step in generic.funnel.steps] == [step.label for step in p6.funnel.steps]


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(
    ("control", "numerator", "flagged"),
    [("P6-06", 1, ["BIG"]), ("P6-14", 1, ["NEG"])],
)
def test_the_generic_float_rule_shows_the_same_funnel_as_p6_large_and_negative_float(control, numerator, flagged):
    """P6-06 / EQ-06 (float > 352 h) and P6-14 / EQ-14 (float < 0): the same population steps, on 6 tasks.

    Source: docs/formulas.md section 2.1, which cites the Oracle help for each line. P6-06 is 46284 and
    P6-14 is 46283: "WBS summary, actual-finish and LOE removed", then the float is read against the
    limit (strict ``>`` 352 h, strict ``<`` 0). The schedule has no WBS summary task, so only two removals
    can show, completed first, then level of effort, in the order of that text.

    | task    | what it is                  | float (h) | P6-06 (> 352) | P6-14 (< 0) |
    |---------|-----------------------------|-----------|---------------|-------------|
    | DONE    | completed (actual finish)   | -8        | removed       | removed     |
    | LOE     | level of effort             | 400       | removed       | removed     |
    | BIG     | ordinary                    | 400       | counted       | not counted |
    | EDGE    | ordinary, exactly the limit | 352       | not counted   | not counted |
    | NEG     | ordinary                    | -16       | not counted   | counted     |
    | NOFLOAT | ordinary, no float          | none      | not counted   | not counted |

    Hand count, for both checks: start 6; completed removes DONE, 5 left; LOE removes LOE, 4 left.
    Denominator 4 (BIG, EDGE, NEG, NOFLOAT). Numerator 1: BIG for P6-06, NEG for P6-14. DONE and LOE carry a
    float that would be counted by one of the two checks, so a population that keeps either changes a numerator.
    """
    tasks = [
        done("DONE", total_float_hr_cnt="-8"),
        todo("LOE", task_type="TT_LOE", total_float_hr_cnt="400"),
        todo("BIG", total_float_hr_cnt="400"),
        todo("EDGE", total_float_hr_cnt="352"),
        todo("NEG", total_float_hr_cnt="-16"),
        todo("NOFLOAT", total_float_hr_cnt=""),
    ]
    context = AnalysisContext(snap(tasks))
    p6 = run_metric(P6[control], context)
    generic = run_metric(CUSTOM[EQUIVALENT[control]], context)

    # (1) the counts are the hand count, on both sides
    assert (p6.numerator, p6.denominator) == (numerator, 4)
    assert (generic.numerator, generic.denominator) == (numerator, 4)
    assert codes(p6) == flagged
    assert codes(generic) == flagged

    # (2) both sides show a funnel
    assert p6.funnel is not None, f"{control}: the P6 check shows no funnel"
    assert generic.funnel is not None, f"{EQUIVALENT[control]}: the generic float rule shows no funnel (funnel is None)"

    # (3) start, then per step the codes it removed (sorted) and the rows left
    hand_count = (6, [(["DONE"], 5), (["LOE"], 4)])

    def read(result):
        steps = [(sorted(step.removed["task_code"]), step.left) for step in result.funnel.steps]
        return result.funnel.start, steps

    assert read(p6) == hand_count
    assert read(generic) == hand_count

    # (4) the steps carry the same labels (the source is not compared)
    assert [step.label for step in generic.funnel.steps] == [step.label for step in p6.funnel.steps]


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(
    ("control", "finish_constraint", "flagged"),
    [("P6-02", "CS_MANDFIN", ["HARD"]), ("P6-03", "CS_MEOB", ["SOFT"])],
)
def test_the_generic_constraints_rule_shows_the_same_funnel_as_p6_hard_and_soft_constraints(
    control, finish_constraint, flagged
):
    """P6-02 / EQ-02 (hard constraints) and P6-03 / EQ-03 (soft constraints): the same population steps, on 5 tasks.

    Source: Oracle P6 help 46286 (Hard constraints) and 46285 (Soft constraints), same wording in both:
    "WBS summary activities, activities with an actual finish date, and Level of Effort activities are removed
    from the subset" and "The Actual percentage is calculated as the number of activities found that match the
    check divided by the total number of subset activities checked". Hard: Mandatory Start and Mandatory
    Finish (46286, and Start on / Finish on for 113176 in xerscope); soft: Start on or before / after, Finish
    on or before / after, As Late As Possible. The schedule has no WBS summary task and no started task (the
    rule that start constraints are ignored once started is not under test), so only two removals can show,
    completed first, then level of effort, in the order of that text.

    | task  | what it is                  | constraint                       | P6-02 (hard) | P6-03 (soft) |
    |-------|-----------------------------|----------------------------------|--------------|--------------|
    | DONE  | completed (actual finish)   | MANDFIN (P6-02) / MEOB (P6-03)   | removed      | removed      |
    | LOE   | level of effort             | MANDFIN (P6-02) / MEOB (P6-03)   | removed      | removed      |
    | HARD  | ordinary                    | CS_MANDSTART                     | counted      | not counted  |
    | SOFT  | ordinary                    | CS_MSOA                          | not counted  | counted      |
    | FREE  | ordinary                    | none                             | not counted  | not counted  |

    Hand count, for both checks: start 5; completed removes DONE, 4 left; LOE removes LOE, 3 left.
    Denominator 3 (HARD, SOFT, FREE). Numerator 1: HARD for P6-02, SOFT for P6-03. DONE and LOE carry a
    constraint that the check would count, so a population that keeps either changes a numerator.
    """
    tasks = [
        done("DONE", cstr_type=finish_constraint, cstr_date="2026-02-13 17:00"),
        todo("LOE", task_type="TT_LOE", cstr_type=finish_constraint, cstr_date="2026-03-13 17:00"),
        todo("HARD", cstr_type="CS_MANDSTART", cstr_date="2026-03-02 08:00"),
        todo("SOFT", cstr_type="CS_MSOA", cstr_date="2026-03-02 08:00"),
        todo("FREE"),
    ]
    context = AnalysisContext(snap(tasks))
    p6 = run_metric(P6[control], context)
    generic = run_metric(CUSTOM[EQUIVALENT[control]], context)

    # (1) the counts are the hand count, on both sides
    assert (p6.numerator, p6.denominator) == (1, 3)
    assert (generic.numerator, generic.denominator) == (1, 3)
    assert codes(p6) == flagged
    assert codes(generic) == flagged

    # (2) both sides show a funnel
    assert p6.funnel is not None, f"{control}: the P6 check shows no funnel"
    assert generic.funnel is not None, f"{EQUIVALENT[control]}: the generic constraints rule shows no funnel (None)"

    # (3) start, then per step the codes it removed (sorted) and the rows left
    hand_count = (5, [(["DONE"], 4), (["LOE"], 3)])

    def read(result):
        steps = [(sorted(step.removed["task_code"]), step.left) for step in result.funnel.steps]
        return result.funnel.start, steps

    assert read(p6) == hand_count
    assert read(generic) == hand_count

    # (4) the steps carry the same labels (the source is not compared)
    assert [step.label for step in generic.funnel.steps] == [step.label for step in p6.funnel.steps]


@pytest.mark.oracle("standard")
def test_the_generic_no_resource_rule_shows_the_same_funnel_as_p6_resource_cost():
    """P6-11 "Resource / Cost" / EQ-11: the same population steps, on 6 tasks.

    Source: Oracle P6 help 46279: "Use this section to view activities that do not have an expense or resource
    assigned ... WBS summary activities, milestones, and Level of Effort activities are removed from the subset
    to create the list of activities checked for no resources or expense assignments. The Actual percentage is
    calculated as the number of activities found that match the check divided by the total number of subset
    activities checked." Completed activities are not in the list of removals: they stay in the population.
    The schedule has no WBS summary task, so two removals can show, milestones first, then level of effort,
    in the order of that text.

    | task  | what it is                       | resource / expense | P6-11                  |
    |-------|----------------------------------|--------------------|------------------------|
    | DONE  | completed (actual finish)        | none               | stays in, counted      |
    | MS    | start milestone                  | none               | removed                |
    | LOE   | level of effort                  | none               | removed                |
    | NORES | ordinary                         | none               | stays in, counted      |
    | RES   | ordinary                         | one resource       | stays in, not counted  |
    | COST  | ordinary                         | one expense only   | stays in, not counted  |

    Hand count: start 6; milestones remove MS, 5 left; level of effort removes LOE, 4 left.
    Denominator 4 (DONE, NORES, RES, COST). Numerator 2 (DONE, NORES). MS and LOE have no assignment, so a
    population that keeps either raises the numerator; a population that removes DONE lowers both counts.
    """
    tasks = [
        done("DONE"),
        todo("MS", **SM),
        todo("LOE", task_type="TT_LOE"),
        todo("NORES"),
        todo("RES"),
        todo("COST"),
    ]
    context = AnalysisContext(snap(tasks, rsrc=["RES"], costs=["COST"]))
    p6 = run_metric(P6["P6-11"], context)
    generic = run_metric(CUSTOM["EQ-11"], context)

    # (1) the counts are the hand count, on both sides
    assert (p6.numerator, p6.denominator) == (2, 4)
    assert (generic.numerator, generic.denominator) == (2, 4)
    assert codes(p6) == ["DONE", "NORES"]
    assert codes(generic) == ["DONE", "NORES"]

    # (2) both sides show a funnel
    assert p6.funnel is not None, "P6-11: the P6 check shows no funnel"
    assert generic.funnel is not None, "EQ-11: the generic no_resource rule shows no funnel (None)"

    # (3) start, then per step the codes it removed (sorted) and the rows left
    hand_count = (6, [(["MS"], 5), (["LOE"], 4)])

    def read(result):
        steps = [(sorted(step.removed["task_code"]), step.left) for step in result.funnel.steps]
        return result.funnel.start, steps

    assert read(p6) == hand_count
    assert read(generic) == hand_count

    # (4) the steps carry the same labels (the source is not compared)
    assert [step.label for step in generic.funnel.steps] == [step.label for step in p6.funnel.steps]


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(
    ("control", "numerator", "flagged"),
    [
        ("P6-05", 1, [("A", "C")]),
        ("P6-07", 4, [("B", "C"), ("B", "E"), ("C", "E")]),
        ("P6-08", 4, [("A", "B"), ("A", "C"), ("A", "D2"), ("B", "C")]),
        ("P6-09", 1, [("C", "E")]),
    ],
)
def test_the_generic_link_rules_show_the_same_funnel_as_p6_lags_and_relationship_types(control, numerator, flagged):
    """P6-05 / EQ-05 (lag > 352 h), P6-07 / EQ-07 (FS share), P6-08 / EQ-08 (lag > 0) and P6-09 / EQ-09 (lag < 0):
    the same population steps, on 9 links.

    Source: docs/formulas.md section 2.1, which cites the Oracle help for each line: P6-05 is 46288, P6-07 is
    46287, P6-08 is 46289, P6-09 is 46290: "links between two actual-finished tasks removed". The population is
    the links whose predecessor and successor are not both completed; one task completed on either end stays in.
    Thresholds: strict ``>`` 352 h, strict ``>`` 0 h, strict ``<`` 0 h; P6-07 counts the FS links of the
    population (listed: the others).

    | link   | type | lag (h) | population | P6-05 (> 352) | P6-07 | P6-08 (> 0) | P6-09 (< 0) |
    |--------|------|---------|------------|---------------|-------|-------------|-------------|
    | D1->D2 | FS   | 400     | removed    | removed       | -     | removed     | removed     |
    | D1->D3 | SS   | -8      | removed    | removed       | -     | removed     | removed     |
    | D1->A  | FS   | 0       | in         | no            | FS    | no          | no          |
    | A->B   | FS   | 352     | in         | no (limit)    | FS    | yes         | no          |
    | A->C   | FS   | 353     | in         | yes           | FS    | yes         | no          |
    | B->C   | SS   | 351     | in         | no            | other | yes         | no          |
    | B->E   | FF   | 0       | in         | no            | other | no          | no          |
    | C->E   | SF   | -1      | in         | no            | other | no          | yes         |
    | A->D2  | FS   | 8       | in         | no            | FS    | yes         | no          |

    D1, D2 and D3 are completed; A, B, C and E are not. A->D2 has an open predecessor and a completed
    successor, so it stays in.

    Hand count, for the four checks: start 9 links; both ends complete removes D1->D2 and D1->D3, 7 left.
    Denominator 7. Numerators: P6-05 1 (A->C); P6-07 4 FS of 7 (D1->A, A->B, A->C, A->D2); P6-08 4 (A->B, A->C,
    B->C, A->D2); P6-09 1 (C->E). D1->D2 (400 h) and D1->D3 (-8 h) would be counted by P6-05 / P6-08 and by
    P6-09, and D1->D2 is an FS, so a population that keeps them changes every numerator or denominator.

    The first step of the P6 side, "into a task" (source "model", docs/formulas.md 1.1: a link counts when its
    successor is a task of the file), removes nothing here and leaves 9; its place and label are not in the
    Oracle text above, they were read from the P6 check's own funnel, not worked out by hand.
    """
    tasks = [done("D1"), done("D2"), done("D3"), todo("A"), todo("B"), todo("C"), todo("E")]
    preds = [
        ("D1", "D2", "FS", 400),
        ("D1", "D3", "SS", -8),
        ("D1", "A", "FS", 0),
        ("A", "B", "FS", 352),
        ("A", "C", "FS", 353),
        ("B", "C", "SS", 351),
        ("B", "E", "FF", 0),
        ("C", "E", "SF", -1),
        ("A", "D2", "FS", 8),
    ]
    context = AnalysisContext(snap(tasks, preds))
    p6 = run_metric(P6[control], context)
    generic = run_metric(CUSTOM[EQUIVALENT[control]], context)

    # (1) the counts are the hand count, on both sides
    assert (p6.numerator, p6.denominator) == (numerator, 7)
    assert (generic.numerator, generic.denominator) == (numerator, 7)
    assert links(p6) == flagged
    assert links(generic) == flagged

    # (2) both sides show a funnel
    assert p6.funnel is not None, f"{control}: the P6 check shows no funnel"
    assert generic.funnel is not None, f"{EQUIVALENT[control]}: the generic link rule shows no funnel (None)"

    # (3) start, then per step the links it removed (sorted pairs) and the links left
    hand_count = (9, [([], 9), ([("D1", "D2"), ("D1", "D3")], 7)])

    def read(result):
        steps = [
            (sorted(zip(step.removed["pred_code"], step.removed["succ_code"], strict=True)), step.left)
            for step in result.funnel.steps
        ]
        return result.funnel.start, steps

    assert read(p6) == hand_count
    assert read(generic) == hand_count

    # (4) the steps carry the same labels (the source is not compared)
    assert [step.label for step in generic.funnel.steps] == [step.label for step in p6.funnel.steps]


# the first two steps of every link funnel in the test below, then the steps of the parameters
INTO_A_TASK = ("into a task", [], 7)
SUCCESSOR_NOT_COMPLETE = ("successor not complete", [("A", "DONE")], 6)
SUCCESSOR_NOT_MILESTONE = "successor not milestone"
SUCCESSOR_NOT_LOE = "successor not level of effort"
NO_LOE_END = "no level-of-effort end"


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(
    ("params", "later_steps", "lag", "fs"),
    [
        pytest.param(
            "exclude_loe = false\nexclude = []",
            [],
            (5, 6, [("A", "B"), ("A", "LOE"), ("A", "MS"), ("LOE", "B"), ("MS", "C")]),
            (3, 6, [("A", "LOE"), ("B", "C"), ("MS", "C")]),
            id="no-parameter",
        ),
        pytest.param(
            'exclude_loe = false\nexclude = ["milestones"]',
            [(SUCCESSOR_NOT_MILESTONE, [("A", "MS")], 5)],
            (4, 5, [("A", "B"), ("A", "LOE"), ("LOE", "B"), ("MS", "C")]),
            (2, 5, [("A", "LOE"), ("B", "C"), ("MS", "C")]),
            id="exclude-milestones",
        ),
        pytest.param(
            'exclude_loe = false\nexclude = ["loe"]',
            [(SUCCESSOR_NOT_LOE, [("A", "LOE")], 5)],
            (4, 5, [("A", "B"), ("A", "MS"), ("LOE", "B"), ("MS", "C")]),
            (3, 5, [("B", "C"), ("MS", "C")]),
            id="exclude-loe-key",
        ),
        pytest.param(
            'exclude_loe = false\nexclude = ["loe", "milestones"]',
            [(SUCCESSOR_NOT_LOE, [("A", "LOE")], 5), (SUCCESSOR_NOT_MILESTONE, [("A", "MS")], 4)],
            (3, 4, [("A", "B"), ("LOE", "B"), ("MS", "C")]),
            (2, 4, [("B", "C"), ("MS", "C")]),
            id="exclude-in-the-order-given",
        ),
        pytest.param(
            "exclude_loe = true\nexclude = []",
            [(NO_LOE_END, [("A", "LOE"), ("LOE", "B")], 4)],
            (3, 4, [("A", "B"), ("A", "MS"), ("MS", "C")]),
            (2, 4, [("B", "C"), ("MS", "C")]),
            id="exclude_loe",
        ),
        pytest.param(
            'exclude_loe = true\nexclude = ["milestones", "loe"]',
            [
                (SUCCESSOR_NOT_MILESTONE, [("A", "MS")], 5),
                (SUCCESSOR_NOT_LOE, [("A", "LOE")], 4),
                (NO_LOE_END, [("LOE", "B")], 3),
            ],
            (2, 3, [("A", "B"), ("MS", "C")]),
            (1, 3, [("B", "C"), ("MS", "C")]),
            id="exclude-then-exclude_loe",
        ),
    ],
)
def test_the_generic_link_rules_apply_exclude_and_exclude_loe_to_the_count_and_the_funnel(params, later_steps, lag, fs):
    """Rules ``lag`` (lag > 0 h) and ``relationship_type`` (FS) with ``links = "succ_incomplete"``, run with
    ``exclude`` and ``exclude_loe``: the counts and the funnel move with each parameter.

    Source: DCMA 14-Point Assessment, PAM 200.1 section 4.0, as docs/standards.md and docs/formulas.md
    (DCMA-02/03/04) give it: a link counts when its SUCCESSOR is a retained task; a predecessor that is
    itself excluded does not take the link out (MS->C stays when milestones are excluded). The key names
    and the "level of effort" test are docs/formulas.md section 1.2. ``exclude`` takes out the links whose
    successor is an excluded task, one step per key; ``exclude_loe`` takes out every link with a level of
    effort at either end (it is not a P6 or DCMA text: the contract of the parameter).

    Six tasks: DONE (completed), LOE (level of effort), MS (start milestone), A, B, C (ordinary).

    | link    | type | lag (h) | lag > 0 | FS  | taken out by                                 |
    |---------|------|---------|---------|-----|----------------------------------------------|
    | A->B    | FS   | 8       | yes     | yes | nothing                                      |
    | A->MS   | FS   | 16      | yes     | yes | "milestones" (successor MS)                  |
    | A->LOE  | SS   | 24      | yes     | no  | "loe" (successor LOE); exclude_loe           |
    | LOE->B  | FS   | 40      | yes     | yes | exclude_loe only (predecessor LOE, B kept)   |
    | MS->C   | SS   | 32      | yes     | no  | nothing (predecessor MS, successor C kept)   |
    | B->C    | FF   | 0       | no      | no  | nothing                                      |
    | A->DONE | FS   | 80      | yes     | yes | links = "succ_incomplete" (successor done)   |

    Hand count. Start 7 links; "succ_incomplete" removes A->DONE, 6 left. Then, by parameter (lag counted / links,
    FS counted / links; the ``relationship_type`` rule flags the links that are not FS):

    - no parameter: 6 links; lag 5 (all but B->C); FS 3 (A->B, A->MS, LOE->B).
    - "milestones": removes A->MS, 5 left; lag 4 (A->B, A->LOE, LOE->B, MS->C); FS 2 (A->B, LOE->B).
    - "loe": removes A->LOE, 5 left; lag 4 (all but B->C); FS 3 (A->B, A->MS, LOE->B).
    - ["loe", "milestones"]: removes A->LOE then A->MS, 4 left; lag 3 (A->B, LOE->B, MS->C); FS 2 (A->B, LOE->B).
    - exclude_loe: removes A->LOE and LOE->B, 4 left; lag 3 (A->B, A->MS, MS->C); FS 2 (A->B, A->MS).
    - ["milestones", "loe"] and exclude_loe: removes A->MS, A->LOE, LOE->B, 3 left; lag 2 (A->B, MS->C); FS 1 (A->B).

    A rule that ignores ``exclude`` or ``exclude_loe`` gives the "no parameter" count (6 links) in the other rows.

    Not in the sources above, read from the rule's own funnel, not worked out by hand: the first step "into a
    task" (removes nothing here), the labels of the steps, and the place of the ``exclude_loe`` step after those of
    ``exclude``.
    """
    tasks = [done("DONE"), todo("LOE", task_type="TT_LOE"), todo("MS", **SM), todo("A"), todo("B"), todo("C")]
    preds = [
        ("A", "B", "FS", 8),
        ("A", "MS", "FS", 16),
        ("A", "LOE", "SS", 24),
        ("LOE", "B", "FS", 40),
        ("MS", "C", "SS", 32),
        ("B", "C", "FF", 0),
        ("A", "DONE", "FS", 80),
    ]
    standard = loads_standard(
        f"""
[standard]
id = "LINKS"
name = "Link rules with exclude and exclude_loe"

[[metric]]
id = "LINKS-LAG"
name = "Positive lags"
rule = "lag"
target = "< 5%"
[metric.params]
op = ">"
value = 0
unit = "hours"
links = "succ_incomplete"
{params}

[[metric]]
id = "LINKS-FS"
name = "Relationship types"
rule = "relationship_type"
target = "> 90%"
[metric.params]
type = "FS"
links = "succ_incomplete"
{params}
""",
        "links-exclude.toml",
    )
    context = AnalysisContext(snap(tasks, preds))
    hand_count = (7, [INTO_A_TASK, SUCCESSOR_NOT_COMPLETE, *later_steps])

    def read(result):
        steps = [
            (step.label, sorted(zip(step.removed["pred_code"], step.removed["succ_code"], strict=True)), step.left)
            for step in result.funnel.steps
        ]
        return result.funnel.start, steps

    for metric_id, (numerator, denominator, flagged) in [("LINKS-LAG", lag), ("LINKS-FS", fs)]:
        result = run_metric(standard[metric_id], context)
        assert (result.numerator, result.denominator) == (numerator, denominator), metric_id
        assert links(result) == flagged, metric_id
        assert result.funnel is not None, f"{metric_id}: the rule shows no funnel"
        assert read(result) == hand_count, metric_id
