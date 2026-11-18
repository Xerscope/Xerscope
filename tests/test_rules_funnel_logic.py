"""The rules ``missing_logic`` and ``dangling`` show their population step by step (``RuleOutput.funnel``).

What this file fixes, on two small schedules built by hand:

- ``missing_logic``: one funnel step per key of ``exclude``, in the order given, labelled as ``EXCLUSIONS``
  (analysis/populations.py) labels it; ``funnel.rows`` is the population ``checked``; set like P6-01 it shows
  the funnel of P6-01 (steps, labels, rows left, tasks removed).
- ``dangling``: the same for ``end = "finish"``; for ``end = "start"`` a last step takes the started tasks out.

The counts (flagged / checked) are written by hand in each test and do not move with the funnel.

``dangling`` is a rule of P6 EPPM; no P6 Professional check has its population (P6-16 / P6-17 count over
every task of the file, see tests/test_custom_standard_equals_p6.py), so its test is a characterization of
the rule's own docstring and of ``EXCLUSIONS``, not a comparison with a P6 check.
"""

import pytest
from rulekit import codes
from xerkit import SM, active, done, snap, todo

from xerscope.analysis import AnalysisContext, builtin_standards, run_metric
from xerscope.analysis.standards import loads_standard

P6 = builtin_standards()["P6"]

STANDARD = loads_standard(
    """
[standard]
id = "FUNNEL"
name = "Funnels of missing_logic and dangling"

[[metric]]
id = "LOGIC-P6"
name = "Logic, set like P6-01"
rule = "missing_logic"
target = "< 5%"
[metric.params]
exclude = ["complete"]
pred_exempt = ["started"]
succ_exempt = []
external_passes = true
dangling = false

[[metric]]
id = "LOGIC-COMPLETE-MILESTONES"
name = "Logic, completed then milestones"
rule = "missing_logic"
target = "< 5%"
params = { exclude = ["complete", "milestones"], pred_exempt = ["started"] }

[[metric]]
id = "LOGIC-MILESTONES-COMPLETE"
name = "Logic, milestones then completed"
rule = "missing_logic"
target = "< 5%"
params = { exclude = ["milestones", "complete"], pred_exempt = ["started"] }

[[metric]]
id = "LOGIC-THREE"
name = "Logic, three exclusions"
rule = "missing_logic"
target = "< 5%"
params = { exclude = ["complete", "loe", "milestones"], pred_exempt = ["started"] }

[[metric]]
id = "DANGLING-FINISH"
name = "Dangling finish"
rule = "dangling"
target = "< 5%"
params = { end = "finish", exclude = ["complete"] }

[[metric]]
id = "DANGLING-START"
name = "Dangling start"
rule = "dangling"
target = "< 5%"
params = { end = "start", exclude = ["complete"] }

[[metric]]
id = "DANGLING-FINISH-LOE-FIRST"
name = "Dangling finish, level of effort then completed"
rule = "dangling"
target = "< 5%"
params = { end = "finish", exclude = ["loe", "complete"] }

[[metric]]
id = "DANGLING-START-LOE-FIRST"
name = "Dangling start, level of effort then completed"
rule = "dangling"
target = "< 5%"
params = { end = "start", exclude = ["loe", "complete"] }
""",
    "funnel-logic.toml",
)

NOT_COMPLETE = "not complete"
NOT_STARTED = "not started"
NOT_LOE = "not level of effort"
NOT_MILESTONE = "not milestone"


def _read(funnel):
    """(start, [(label, task codes removed, rows left)]): the funnel as a reader sees it."""
    steps = [(step.label, sorted(step.removed["task_code"]), step.left) for step in funnel.steps]
    return funnel.start, steps


def _population(frame) -> list[str]:
    """Task codes in the order of the frame (the order of the file, not sorted)."""
    return list(frame["task_code"])


# --- missing_logic ---------------------------------------------------------------------------------

LOGIC_TASKS = [
    done("DONE"),
    done("DONE_MS", **SM),
    todo("LOE", task_type="TT_LOE"),
    todo("MS", **SM),
    active("STARTED"),
    todo("A"),
    todo("B"),
    todo("ISOLATED"),
]
LOGIC_LINKS = [
    ("STARTED", "A", "FS", 0),
    ("MS", "A", "FS", 0),
    ("A", "B", "FS", 0),
]


def _run_logic(metric_id):
    return run_metric(STANDARD[metric_id], AnalysisContext(snap(LOGIC_TASKS, LOGIC_LINKS)))


@pytest.mark.oracle("standard")
def test_missing_logic_set_like_p6_logic_shows_the_same_funnel_as_p6_01():
    """P6-01 "Logic" (Oracle P6 Check Schedule help 101248, docs/standards.md): "completed and WBS summary tasks
    not included; started tasks need no predecessor". Counts: open-ended / checked. A start milestone without
    predecessor and a finish milestone without successor are counted (the P6 26.8 reports win over 101248).

    By hand, eight tasks, links STARTED->A, MS->A, A->B (all FS):

    | task     | what it is                | predecessor    | successor | P6-01                  |
    |----------|---------------------------|----------------|-----------|------------------------|
    | DONE     | completed                 | none           | none      | removed                |
    | DONE_MS  | completed milestone       | none           | none      | removed                |
    | LOE      | level of effort           | none           | none      | in, open ended         |
    | MS       | start milestone           | none           | A         | in, open ended (pred)  |
    | STARTED  | started, in progress      | none (exempt)  | A         | in, not flagged        |
    | A        | not started               | STARTED, MS    | B         | in, not flagged        |
    | B        | not started               | A              | none      | in, open ended (succ)  |
    | ISOLATED | not started, no link      | none           | none      | in, open ended         |

    Start 8; completed removes DONE and DONE_MS, 6 left. Denominator 6; numerator 4 (LOE, MS, B, ISOLATED).

    The generic rule must show the same funnel: same start, same steps in the same order with the same labels,
    same tasks removed and rows left. The ``source`` of a step is not compared (a generic rule has no Oracle
    page of its own).
    """
    context = AnalysisContext(snap(LOGIC_TASKS, LOGIC_LINKS))
    p6 = run_metric(P6["P6-01"], context)
    generic = run_metric(STANDARD["LOGIC-P6"], context)
    by_hand = (8, [(NOT_COMPLETE, ["DONE", "DONE_MS"], 6)])
    flagged = ["B", "ISOLATED", "LOE", "MS"]

    assert (p6.numerator, p6.denominator) == (4, 6)
    assert (generic.numerator, generic.denominator) == (4, 6)
    assert codes(p6) == flagged
    assert codes(generic) == flagged

    assert p6.funnel is not None
    assert generic.funnel is not None, "the generic missing_logic rule gives no funnel (None)"
    assert _read(p6.funnel) == by_hand
    assert _read(generic.funnel) == by_hand
    assert _population(generic.funnel.rows) == _population(generic.checked)
    assert _population(generic.checked) == ["LOE", "MS", "STARTED", "A", "B", "ISOLATED"]


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(
    ("metric_id", "steps", "numerator", "denominator", "flagged"),
    [
        pytest.param(
            "LOGIC-COMPLETE-MILESTONES",
            [(NOT_COMPLETE, ["DONE", "DONE_MS"], 6), (NOT_MILESTONE, ["MS"], 5)],
            3,
            5,
            ["B", "ISOLATED", "LOE"],
            id="complete-then-milestones",
        ),
        pytest.param(
            "LOGIC-MILESTONES-COMPLETE",
            [(NOT_MILESTONE, ["DONE_MS", "MS"], 6), (NOT_COMPLETE, ["DONE"], 5)],
            3,
            5,
            ["B", "ISOLATED", "LOE"],
            id="milestones-then-complete",
        ),
        pytest.param(
            "LOGIC-THREE",
            [(NOT_COMPLETE, ["DONE", "DONE_MS"], 6), (NOT_LOE, ["LOE"], 5), (NOT_MILESTONE, ["MS"], 4)],
            2,
            4,
            ["B", "ISOLATED"],
            id="complete-loe-milestones",
        ),
    ],
)
def test_missing_logic_funnel_has_one_step_per_exclusion_in_the_order_given(
    metric_id, steps, numerator, denominator, flagged
):
    """One funnel step per key of ``exclude``, in the order given, labelled as EXCLUSIONS labels it; the
    population is the tasks left (``funnel.rows`` is ``checked``). Source: the contract of ``exclude``
    (``missing_logic`` docstring; labels of ``EXCLUSIONS``, analysis/populations.py); the order of the steps is
    a contract of the rule, not a text of P6 or DCMA.

    Same eight tasks as above. DONE_MS is both completed and a milestone, so the key that comes first takes it:

    - ["complete", "milestones"]: completed removes DONE, DONE_MS, 6 left; milestones removes MS, 5 left.
    - ["milestones", "complete"]: milestones removes DONE_MS, MS, 6 left; completed removes DONE, 5 left.
    - ["complete", "loe", "milestones"]: 6 left, LOE removes LOE, 5 left; milestones removes MS, 4 left.

    Counts (flagged / checked), the milestone and level-of-effort tasks leaving the population:
    two milestone keys, 5 tasks (LOE, STARTED, A, B, ISOLATED), 3 flagged (LOE, B, ISOLATED); three keys,
    4 tasks (STARTED, A, B, ISOLATED), 2 flagged (B, ISOLATED). A, which has the links STARTED->A and MS->A,
    stays not flagged although MS leaves the population: the links are the file's, not the population's.
    """
    result = _run_logic(metric_id)

    assert (result.numerator, result.denominator) == (numerator, denominator)
    assert codes(result) == flagged
    assert result.funnel is not None, f"{metric_id}: the generic missing_logic rule gives no funnel (None)"
    assert _read(result.funnel) == (8, steps)
    assert _population(result.funnel.rows) == _population(result.checked)
    assert len(result.funnel.rows) == result.denominator


# --- dangling --------------------------------------------------------------------------------------

DANGLING_TASKS = [
    done("DONE"),
    active("STARTED"),
    todo("A"),
    todo("B"),
    todo("C"),
    todo("D"),
    todo("E"),
    todo("G"),
    todo("H"),
]
DANGLING_LINKS = [
    ("A", "B", "FS", 0),
    ("A", "C", "SS", 0),
    ("A", "STARTED", "FF", 0),
    ("A", "E", "SS", 0),
    ("B", "D", "FF", 0),
    ("B", "H", "FF", 0),
    ("C", "D", "SF", 0),
    ("DONE", "E", "SS", 0),
    ("STARTED", "E", "FF", 0),
    ("G", "E", "SS", 0),
]


def _run_dangling(metric_id):
    return run_metric(STANDARD[metric_id], AnalysisContext(snap(DANGLING_TASKS, DANGLING_LINKS)))


DANGLING_CASES = [
    pytest.param(
        "DANGLING-FINISH",
        [(NOT_COMPLETE, ["DONE"], 8)],
        (2, 8),
        ["C", "G"],
        ["STARTED", "A", "B", "C", "D", "E", "G", "H"],
        id="finish",
    ),
    pytest.param(
        "DANGLING-START",
        [(NOT_COMPLETE, ["DONE"], 8), (NOT_STARTED, ["STARTED"], 7)],
        (2, 7),
        ["D", "H"],
        ["A", "B", "C", "D", "E", "G", "H"],
        id="start",
    ),
    pytest.param(
        "DANGLING-FINISH-LOE-FIRST",
        [(NOT_LOE, [], 9), (NOT_COMPLETE, ["DONE"], 8)],
        (2, 8),
        ["C", "G"],
        ["STARTED", "A", "B", "C", "D", "E", "G", "H"],
        id="finish-loe-first",
    ),
    pytest.param(
        "DANGLING-START-LOE-FIRST",
        [(NOT_LOE, [], 9), (NOT_COMPLETE, ["DONE"], 8), (NOT_STARTED, ["STARTED"], 7)],
        (2, 7),
        ["D", "H"],
        ["A", "B", "C", "D", "E", "G", "H"],
        id="start-loe-first",
    ),
]


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(("metric_id", "steps", "counts", "flagged", "population"), DANGLING_CASES)
def test_dangling_funnel_has_one_step_per_exclusion_then_not_started_for_a_start(
    metric_id, steps, counts, flagged, population
):
    """Rule ``dangling`` (EPPM; no P6 Professional check has its population): its funnel and its counts.

    Source: the docstring of ``dangling``: ``end = "finish"`` flags a task with successors but none FS or FF;
    ``end = "start"`` flags a task with predecessors but none FS or SS; a task with no logic at all on that end
    is not flagged (it is ``missing_logic``'s). With ``end = "start"``, the started tasks are not in the
    population (docs/standards.md, P6-16: a task in progress is not counted); the step is the EXCLUSIONS key
    ``started``, "not started", after the steps of ``exclude``. Labels: EXCLUSIONS.

    By hand, nine tasks, ten links (all lag 0):

    | task    | what it is  | predecessors   | successors                | as finish (end)   | as start (end)    |
    |---------|-------------|----------------|---------------------------|-------------------|-------------------|
    | DONE    | completed   | none           | E SS                      | dangling, removed | not flagged       |
    | STARTED | in progress | A FF           | E FF                      | driven            | dangling, removed |
    | A       | not started | none           | B FS, C SS, STARTED FF, E SS | driven         | not flagged       |
    | B       | not started | A FS           | D FF, H FF                | driven            | driven            |
    | C       | not started | A SS           | D SF                      | DANGLING (SF)     | driven            |
    | D       | not started | B FF, C SF     | none                      | not flagged       | DANGLING          |
    | E       | not started | A SS, G SS, ...| none                      | not flagged       | driven (A SS)     |
    | G       | not started | none           | E SS                      | DANGLING (SS)     | not flagged       |
    | H       | not started | B FF           | none                      | not flagged       | DANGLING (FF)     |

    E also has DONE SS and STARTED FF as predecessors. "not flagged": no logic on that end, left to missing_logic.

    Finish, exclude ["complete"]: start 9; completed removes DONE, 8 left. Flagged C, G: 2 / 8. A population that
    keeps DONE would give 3 / 9.
    Start, exclude ["complete"]: 9, completed removes DONE (8), started removes STARTED (7). Flagged D, H: 2 / 7.
    A population that keeps STARTED would give 3 / 8. The last step has 7 rows, the denominator.
    With "loe" first: no task is level of effort, so that step removes nothing and leaves 9; then the above.
    """
    result = _run_dangling(metric_id)

    assert (result.numerator, result.denominator) == counts
    assert codes(result) == flagged
    assert result.funnel is not None, f"{metric_id}: the dangling rule gives no funnel (None)"
    assert _read(result.funnel) == (9, steps)
    assert _population(result.funnel.rows) == _population(result.checked) == population
    assert result.funnel.steps[-1].left == result.denominator
