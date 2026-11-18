"""The rules ``invalid_dates``, ``late_vs_baseline`` and ``bei`` show their population step by step.

``RuleOutput.funnel`` of each rule: one step per key of ``exclude`` in the order given, labelled as ``EXCLUSIONS``
(analysis/populations.py) labels it, so no label is written here; ``funnel.rows`` is the population ``checked``.
``bei`` adds a last step, "due by the status date", whose rows left are the denominator.

The counts (flagged / checked) are written by hand in each test and are the ones the rules gave before they
returned a funnel: only ``funnel is not None`` can fail. The cases where the funnel stays ``None`` (``started``
denominator, ``due_from = "baseline"``, no status date) are written down as well, so they do not change by
accident.

Status date of every small schedule: Monday 2026-03-02 08:00 (tests/xerkit.py), 8 h days, Monday to Friday.
"""

import pytest
from rulekit import codes
from xerkit import SM, active, done, snap, todo

from xerscope.analysis import AnalysisContext, Baseline, rules
from xerscope.analysis.populations import EXCLUSIONS

DUE_BY_THE_STATUS_DATE = "due by the status date"
WITHOUT_STATUS_DATE = {"last_recalc_date": "", "plan_start_date": ""}


def _step(key, removed, left):
    """A funnel step as a reader sees it: the label of EXCLUSIONS[key], the task codes removed, the rows left."""
    return EXCLUSIONS[key].label, removed, left


def _read(funnel):
    """(start, [(label, task codes removed, rows left)]): the funnel as a reader sees it."""
    steps = [(step.label, sorted(step.removed["task_code"]), step.left) for step in funnel.steps]
    return funnel.start, steps


def _population(frame) -> list[str]:
    """Task codes in the order of the frame (the order of the file, not sorted)."""
    return list(frame["task_code"])


# --- invalid_dates ---------------------------------------------------------------------------------

INVALID_DATES_TASKS = [
    done("DONE_BEFORE"),  # finished 2026-02-13, before the status date: left out by complete_before_data_date
    todo("LOE", task_type="TT_LOE", early_start_date="2026-02-27 08:00"),  # level of effort: left out by loe
    done("DONE_AFTER", act_end_date="2026-03-04 17:00"),  # actual finish after the status date: invalid
    todo("EARLY", early_start_date="2026-02-27 08:00"),  # not started, start forecast before the status date
    active("RUN_LATE", restart_date="2026-02-26 08:00", reend_date="2026-02-27 17:00"),  # remaining finish before
    active("RUN_OK", restart_date="2026-02-27 08:00", reend_date="2026-03-05 17:00"),  # remaining finish after
    todo("ON_STATUS_DATE"),  # start exactly on the status date: not before it (include_data_date is off)
    todo("FINE", early_start_date="2026-03-03 08:00"),
]
INVALID_DATES_CASES = [
    pytest.param(
        ("loe", "complete_before_data_date"),
        [_step("loe", ["LOE"], 7), _step("complete_before_data_date", ["DONE_BEFORE"], 6)],
        (3, 6),
        ["DONE_AFTER", "EARLY", "RUN_LATE"],
        id="default",
    ),
    pytest.param(
        ("complete_before_data_date", "loe"),
        [_step("complete_before_data_date", ["DONE_BEFORE"], 7), _step("loe", ["LOE"], 6)],
        (3, 6),
        ["DONE_AFTER", "EARLY", "RUN_LATE"],
        id="reversed",
    ),
    pytest.param(
        ("loe",),
        [_step("loe", ["LOE"], 7)],
        (3, 7),
        ["DONE_AFTER", "EARLY", "RUN_LATE"],
        id="loe-only",
    ),
    pytest.param(
        (),
        [],
        (4, 8),
        ["DONE_AFTER", "EARLY", "LOE", "RUN_LATE"],
        id="no-exclusion",
    ),
]


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(("exclude", "steps", "counts", "flagged"), INVALID_DATES_CASES)
def test_invalid_dates_funnel_has_one_step_per_exclusion_in_the_order_given(exclude, steps, counts, flagged):
    """One funnel step per key of ``exclude``, in the order given, labelled as EXCLUSIONS labels it; the
    population is the tasks left (``funnel.rows`` is ``checked``). Source: the ``exclude`` contract of the rule;
    the order of the steps is a contract of the rule, not a text of P6 or DCMA.

    By hand, eight tasks. Invalid (101248, DECM 06A506: a forecast before the status date, an actual after it):
    DONE_AFTER (actual), EARLY (forecast start), RUN_LATE (remaining finish); LOE too when it is not left out
    (forecast start 02-27). RUN_OK finishes after, ON_STATUS_DATE starts on the date, FINE starts after.
    Default: LOE out (7 left), DONE_BEFORE out (6 left): 3 / 6. Without "complete_before_data_date" it stays
    in, 3 / 7, not invalid (complete, actual before the date). Without any key, 4 / 8 (LOE counted).
    """
    context = AnalysisContext(snap(INVALID_DATES_TASKS))
    result = rules.invalid_dates(context, exclude=exclude)

    assert (result.numerator, result.denominator) == counts
    assert codes(result) == flagged
    assert result.funnel is not None, "invalid_dates gives no funnel (None)"
    assert _read(result.funnel) == (8, steps)
    assert _population(result.funnel.rows) == _population(result.checked)
    assert len(result.funnel.rows) == result.denominator


@pytest.mark.oracle("standard")
def test_invalid_dates_started_denominator_keeps_no_funnel():
    """DECM 06A506a: the base is the tasks with an actual start, not the population, so no population funnel.

    By hand, four tasks: DONE_AFTER (started, actual finish after the status date: invalid), RUN_LATE (started,
    remaining finish before: invalid), RUN_OK (started, valid), FINE (not started, valid, not in the base).
    No task is level of effort or completed before the status date, so the exclusions take nothing:
    2 invalid / 3 started.
    """
    tasks = [
        done("DONE_AFTER", act_end_date="2026-03-04 17:00"),
        active("RUN_LATE", restart_date="2026-02-26 08:00", reend_date="2026-02-27 17:00"),
        active("RUN_OK", restart_date="2026-02-27 08:00", reend_date="2026-03-05 17:00"),
        todo("FINE", early_start_date="2026-03-03 08:00"),
    ]
    result = rules.invalid_dates(AnalysisContext(snap(tasks)), denominator="started")

    assert (result.numerator, result.denominator) == (2, 3)
    assert codes(result) == ["DONE_AFTER", "RUN_LATE"]
    assert result.funnel is None


@pytest.mark.oracle("standard")
def test_invalid_dates_without_a_status_date_gives_no_funnel_and_says_so():
    """Without a status date, "before the status date" has no meaning: no funnel, and the note says why
    (101248 and DECM 06A506 both compare to the status date).

    By hand: one task, a file whose project carries no data date (``data_date`` is None).
    """
    snapshot = snap([todo("A")], project=WITHOUT_STATUS_DATE)
    result = rules.invalid_dates(AnalysisContext(snapshot))

    assert snapshot.data_date is None
    assert "no status date" in result.note
    assert result.funnel is None


# --- late_vs_baseline ------------------------------------------------------------------------------

LATE_BASELINE_TASKS = [
    todo("DONE", early_end_date="2026-02-12 17:00"),
    todo("MS", early_end_date="2026-03-10 17:00", **SM),
    todo("LOE", early_end_date="2026-03-10 17:00", task_type="TT_LOE"),
    todo("LATE", early_end_date="2026-03-09 17:00"),
    todo("ON_TIME", early_end_date="2026-03-09 17:00"),
    todo("NO_WORKING_TIME", early_end_date="2026-03-06 17:00"),
]
LATE_TASKS = [
    done("DONE"),  # finished Fri 02-13 17:00 against a baseline of Thu 02-12 17:00: one working day late
    todo("MS", early_end_date="2026-03-20 17:00", **SM),  # 8 working days late
    todo("LOE", early_end_date="2026-03-20 17:00", task_type="TT_LOE"),  # 8 working days late
    todo("LATE", early_end_date="2026-03-10 17:00"),  # Tue against Mon: 1 working day = 8 h late
    todo("ON_TIME", early_end_date="2026-03-09 17:00"),  # equal to its baseline finish: not late
    todo("NO_WORKING_TIME", early_end_date="2026-03-07 17:00"),  # Sat against Fri: no working time, not late
    todo("NEW", early_end_date="2026-03-10 17:00", target_end_date="2026-03-09 17:00"),  # no baseline
    todo("NEW2", early_end_date="2026-03-10 17:00", target_end_date="2026-03-10 17:00"),  # no baseline
]
LATE_CASES = [
    pytest.param(
        ("complete", "milestones", "loe"),
        [_step("complete", ["DONE"], 7), _step("milestones", ["MS"], 6), _step("loe", ["LOE"], 5)],
        (1, 5),
        ["LATE"],
        id="default",
    ),
    pytest.param(
        ("loe", "complete", "milestones"),
        [_step("loe", ["LOE"], 7), _step("complete", ["DONE"], 6), _step("milestones", ["MS"], 5)],
        (1, 5),
        ["LATE"],
        id="loe-first",
    ),
    pytest.param(
        ("complete",),
        [_step("complete", ["DONE"], 7)],
        (3, 7),
        ["LATE", "LOE", "MS"],
        id="complete-only",
    ),
]


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(("exclude", "steps", "counts", "flagged"), LATE_CASES)
def test_late_vs_baseline_funnel_has_one_step_per_exclusion_in_the_order_given(exclude, steps, counts, flagged):
    """One funnel step per key of ``exclude``, in the order given, labelled as EXCLUSIONS labels it; the
    population is the tasks left (``funnel.rows`` is ``checked``). Source: the ``exclude`` contract of the rule
    (order: a contract of the rule, not a text of P6 or DCMA).

    By hand, eight tasks. Late = finish later than the baseline finish by working time on the task's calendar
    (docstring of the rule; P6 Finish Variance): LATE +1 working day (8 h), MS and LOE +8 working days, DONE +1
    working day; ON_TIME equal, NO_WORKING_TIME Sat against Fri (0 h), NEW and NEW2 no baseline: they pass.
    Default: DONE, MS, LOE out (5 left), 1 late (LATE): 1 / 5. Only "complete": MS, LOE, LATE late, 3 / 7.
    """
    baseline = Baseline.from_snapshot(snap(LATE_BASELINE_TASKS))
    context = AnalysisContext(snap(LATE_TASKS), baseline=baseline)
    result = rules.late_vs_baseline(context, exclude=exclude)

    assert (result.numerator, result.denominator) == counts
    assert codes(result) == flagged
    assert result.funnel is not None, "late_vs_baseline gives no funnel (None)"
    assert _read(result.funnel) == (8, steps)
    assert _population(result.funnel.rows) == _population(result.checked)
    assert len(result.funnel.rows) == result.denominator


@pytest.mark.oracle("standard")
def test_late_vs_baseline_planned_reads_a_task_without_baseline_against_its_planned_finish():
    """``no_baseline = "planned"`` (P6 Professional, docstring of the rule): a task with no baseline finish is
    late when its finish is later than its planned finish. The funnel is the same as with ``"pass"``.

    By hand, same eight tasks: NEW finishes Tue 03-10, planned finish Mon 03-09: late. NEW2 finishes on its
    planned finish: not late. With LATE (1 working day): 2 late / 5 (DONE, MS, LOE out) = 2 / 5.
    """
    baseline = Baseline.from_snapshot(snap(LATE_BASELINE_TASKS))
    result = rules.late_vs_baseline(AnalysisContext(snap(LATE_TASKS), baseline=baseline), no_baseline="planned")

    assert (result.numerator, result.denominator) == (2, 5)
    assert codes(result) == ["LATE", "NEW"]
    assert result.funnel is not None, "late_vs_baseline gives no funnel (None)"
    assert _read(result.funnel) == (
        8,
        [_step("complete", ["DONE"], 7), _step("milestones", ["MS"], 6), _step("loe", ["LOE"], 5)],
    )
    assert _population(result.funnel.rows) == _population(result.checked)


# --- bei -------------------------------------------------------------------------------------------

BEI_BASELINE_TASKS = [
    todo("LOE", early_end_date="2026-02-20 17:00", task_type="TT_LOE"),
    todo("MS", early_end_date="2026-02-20 17:00", **SM),
    todo("A", early_end_date="2026-02-27 17:00"),
    todo("B", early_end_date="2026-02-27 17:00"),
    todo("C", early_end_date="2026-03-02 08:00"),  # exactly the status date
    todo("D", early_end_date="2026-03-20 17:00"),
    todo("G", early_end_date="2026-02-13 17:00"),
]
BEI_TASKS = [
    todo("LOE", task_type="TT_LOE"),  # left out by loe
    todo("MS", **SM),  # left out by milestones
    done("A"),  # due 02-27, finished 02-13: due, completed
    todo("B"),  # due 02-27, not finished: due, not completed
    todo("C"),  # baseline finish on the status date: due (on or before), not completed
    todo("D"),  # baseline finish 03-20, after the status date: not due
    done("G"),  # due 02-13, finished 02-13: due, completed
    todo("NEW"),  # no baseline finish
]
BEI_STEPS = [_step("loe", ["LOE"], 7), _step("milestones", ["MS"], 6)]
BEI_CASES = [
    pytest.param(
        "due",
        (2, 5),
        ["B", "C", "NEW"],
        ["D"],
        id="missing-baseline-due",
    ),
    pytest.param(
        "ignore",
        (2, 4),
        ["B", "C"],
        ["D", "NEW"],
        id="missing-baseline-ignore",
    ),
]


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(("missing_baseline", "counts", "flagged", "not_due"), BEI_CASES)
def test_bei_funnel_ends_with_the_tasks_due_by_the_status_date(missing_baseline, counts, flagged, not_due):
    """BEI = tasks completed / tasks due by the status date (docstring of the rule). A task is due when its
    baseline finish is on or before the status date (DCMA-EA PAM 200.1 3.1.2.4, as quoted in tests/test_rules.py;
    not re-read here); with ``missing_baseline = "due"`` a task with no baseline finish is due too (P6 EPPM,
    docstring), with ``"ignore"`` it is not (PAM 200.1 3.1.2.4 counts it, so "due" is the DCMA reading).

    By hand, eight tasks: LOE and MS out (6 left: A, B, C, D, G, NEW). Due: A, B, G (baseline before), C (baseline
    exactly on the status date); D not (03-20). Completed: A, G = 2. "due": NEW due, 2 / 5 (D out, 5 rows left).
    "ignore": NEW out with D, 2 / 4 (4 rows left). Open and due: B, C (and NEW with "due").
    """
    baseline = Baseline.from_snapshot(snap(BEI_BASELINE_TASKS))
    result = rules.bei(AnalysisContext(snap(BEI_TASKS), baseline=baseline), missing_baseline=missing_baseline)
    last_step = (DUE_BY_THE_STATUS_DATE, not_due, counts[1])

    assert (result.numerator, result.denominator) == counts
    assert codes(result) == flagged
    assert result.funnel is not None, "bei gives no funnel (None)"
    assert _read(result.funnel) == (8, [*BEI_STEPS, last_step])
    assert _population(result.funnel.rows) == _population(result.checked)
    assert len(result.funnel.rows) == result.denominator


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(
    ("exclude", "steps"),
    [
        pytest.param(
            ("loe", "milestones"),
            [_step("loe", ["LOE"], 7), _step("milestones", ["MS"], 6)],
            id="default",
        ),
        pytest.param(
            ("milestones", "loe"),
            [_step("milestones", ["MS"], 7), _step("loe", ["LOE"], 6)],
            id="milestones-first",
        ),
    ],
)
def test_bei_funnel_has_one_step_per_exclusion_in_the_order_given_then_the_due_step(exclude, steps):
    """One step per key of ``exclude`` in the order given, then "due by the status date" as the last one.
    Source: the ``exclude`` contract of the rule; the order is a contract of the rule, not of PAM 200.1.

    Same eight tasks as above, ``missing_baseline = "due"``: 8 tasks, the two exclusions leave 6 (A, B, C, D, G,
    NEW), the last step removes D and leaves 5; 2 / 5 whatever the order of the exclusions.
    """
    baseline = Baseline.from_snapshot(snap(BEI_BASELINE_TASKS))
    result = rules.bei(AnalysisContext(snap(BEI_TASKS), baseline=baseline), exclude=exclude)

    assert (result.numerator, result.denominator) == (2, 5)
    assert result.funnel is not None, "bei gives no funnel (None)"
    assert _read(result.funnel) == (8, [*steps, (DUE_BY_THE_STATUS_DATE, ["D"], 5)])


@pytest.mark.oracle("standard")
def test_bei_from_the_baseline_keeps_no_funnel():
    """``due_from = "baseline"`` (P6 Professional, docstring of the rule): the due tasks are counted in the
    baseline itself, ``exclude`` applied there; a task added since is never due, one deleted since still is.

    By hand, the baseline of seven tasks plus GONE (baseline finish 02-27, no longer in the schedule): LOE and MS
    out; due: A, B, C (on the status date), G, GONE = 5; D not (03-20); NEW is not in the baseline, never due.
    Completed in the schedule: A, G = 2. So 2 / 5, and the funnel stays None (the population is in the baseline).
    """
    baseline = Baseline.from_snapshot(snap([*BEI_BASELINE_TASKS, todo("GONE", early_end_date="2026-02-27 17:00")]))
    result = rules.bei(AnalysisContext(snap(BEI_TASKS), baseline=baseline), due_from="baseline")

    assert (result.numerator, result.denominator) == (2, 5)
    assert result.funnel is None


@pytest.mark.oracle("standard")
def test_bei_without_a_status_date_gives_no_funnel_and_says_so():
    """Without a status date nothing is "due by the status date" (PAM 200.1 3.1.2.4): no funnel, and the note
    says why.

    By hand: one task, planned baseline, a file whose project carries no data date (``data_date`` is None).
    """
    snapshot = snap([todo("A")], project=WITHOUT_STATUS_DATE)
    result = rules.bei(AnalysisContext(snapshot, baseline=Baseline.planned(snapshot)))

    assert snapshot.data_date is None
    assert "no status date" in result.note
    assert result.funnel is None
