"""Score of a standard: checks in pass / checks evaluated (pass + fail), info, n/a and error left out."""

import pytest
from xerkit import snap, todo

from xerscope.analysis import AnalysisContext, CheckResult, Metric, loads_standard, run_standard, standard_score

# A -> B -> C, D alone. P6-01's rule flags A (no predecessor), C (no successor) and D (neither):
# 3 of 4 open tasks = 75 %.
CHAIN = snap([todo("A"), todo("B"), todo("C"), todo("D")], [("A", "B", "FS", 0), ("B", "C", "FS", 0)])

HEAD = '[standard]\nid = "T"\nname = "Test"\n'


def _metric(metric_id: str, rule: str, target: str) -> str:
    return f'\n[[metric]]\nid = "{metric_id}"\nname = "{metric_id}"\nrule = "{rule}"\ntarget = "{target}"\n'


def test_score_on_a_hand_made_schedule_is_two_pass_over_three_evaluated():
    standard = loads_standard(
        HEAD
        + _metric("T-01", "p6_01_logic", "<= 100%")  # 75 % <= 100 %: pass
        + _metric("T-02", "p6_01_logic", "< 5%")  # 75 % < 5 %: fail
        + _metric("T-03", "p6_01_logic", "<= 75%")  # 75 % <= 75 %: pass
        + _metric("T-04", "p6_13_bei", "> 0.95")  # BEI needs a baseline, none given: n/a
    )
    results = run_standard(standard, AnalysisContext(CHAIN))
    assert [(r.metric.id, r.status, r.numerator, r.denominator) for r in results] == [
        ("T-01", "pass", 3, 4),
        ("T-02", "fail", 3, 4),
        ("T-03", "pass", 3, 4),
        ("T-04", "n/a", None, None),
    ]
    score = standard_score(results)
    assert (score.passed, score.evaluated, score.failed_ids) == (2, 3, ("T-02",))
    assert score.share == pytest.approx(2 / 3) and round(score.share, 3) == 0.667
    assert (score.value, score.detail) == ("67 %", "3 evaluated · 1 fail: T-02")


def test_a_standard_without_an_applicable_check_has_no_score():
    standard = loads_standard(HEAD + _metric("T-01", "p6_13_bei", "> 0.95") + _metric("T-02", "p6_01_logic", "info"))
    results = run_standard(standard, AnalysisContext(CHAIN))
    assert [r.status for r in results] == ["n/a", "info"]
    score = standard_score(results)
    assert (score.passed, score.evaluated, score.share) == (0, 0, None)
    assert (score.value, score.detail) == ("–", "0 evaluated")


def _results(*statuses: str) -> list[CheckResult]:
    return [
        CheckResult(Metric(id=f"T-{index:02d}", name=f"check {index}", standard="T", rule="p6_01_logic"), status)
        for index, status in enumerate(statuses, start=1)
    ]


@pytest.mark.parametrize(
    ("statuses", "passed", "evaluated", "failed_ids"),
    [
        # 3 pass + 2 fail evaluated; the 2 info, the n/a and the error are not: 3 / 5
        (("pass", "fail", "info", "pass", "n/a", "fail", "info", "pass", "error"), 3, 5, ("T-02", "T-06")),
        # the same pass and fail without the others: the same score
        (("pass", "fail", "pass", "fail", "pass"), 3, 5, ("T-02", "T-04")),
        (("pass",) * 4, 4, 4, ()),
        (("info", "n/a", "error"), 0, 0, ()),
        ((), 0, 0, ()),
    ],
)
def test_info_na_and_error_are_in_neither_term(statuses, passed, evaluated, failed_ids):
    score = standard_score(_results(*statuses))
    assert (score.passed, score.evaluated, score.failed_ids) == (passed, evaluated, failed_ids)
