"""Score of a standard: checks in pass / checks evaluated (pass + fail), info, n/a and error left out."""

import pandas as pd
import pytest
from xerkit import snap, todo

from xerscope.analysis import AnalysisContext, CheckResult, Metric, loads_standard, run_standard, standard_score
from xerscope.analysis.checks import (
    compare_counts,
    flagged_codes,
    flagged_trail,
    mismatch_count,
    report_counts,
    results_frame,
    shown_by_group,
    status_counts,
    summary_frame,
)

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


# --- what the Schedule health page shows of a list of results -----------------------------------


def _check(metric_id: str, status: str, group: str = "", flagged: pd.DataFrame | None = None, **fields) -> CheckResult:
    metric = Metric(id=metric_id, name=f"check {metric_id}", standard="T", rule="p6_01_logic", group=group)
    return CheckResult(metric, status, flagged=pd.DataFrame() if flagged is None else flagged, **fields)


def test_status_counts_give_each_status_and_the_checks_with_a_target():
    """Eight results: 2 pass, 3 fail, 1 info, 1 n/a, 1 error. Scored: 2 + 3 = 5."""
    counts = status_counts(_results("pass", "fail", "info", "fail", "n/a", "pass", "fail", "error"))
    assert counts == {"pass": 2, "fail": 3, "info": 1, "n/a": 1, "error": 1, "scored": 5}
    assert status_counts([])["scored"] == 0


def test_summary_frame_counts_the_items_listed_and_names_the_baseline_in_the_note():
    """A lists 2 tasks, computed on baseline "BL1" with the note "late"; B lists nothing, has no
    baseline and no note."""
    two_tasks = pd.DataFrame({"task_code": ["T1", "T2"]})
    results = [_check("A", "fail", flagged=two_tasks, note="late", baseline="BL1"), _check("B", "pass")]
    summary = summary_frame(results)
    assert summary["id"].tolist() == ["A", "B"] and summary["flagged"].tolist() == [2, 0]
    assert summary["note"].tolist() == ["late · baseline: BL1", ""]
    assert results_frame(results)["note"].tolist() == ["late", ""]  # the plain frame keeps the plain note


def test_flagged_trail_lists_every_item_under_its_check():
    """A (fail) lists T1 and T2, B (pass) nothing, C (info) the link P1 -> S1: three rows, in the
    order of the checks, each naming its check first; a task has no link columns and a link no
    task column."""
    results = [
        _check("A", "fail", flagged=pd.DataFrame({"task_code": ["T1", "T2"]})),
        _check("B", "pass"),
        _check("C", "info", flagged=pd.DataFrame({"pred_code": ["P1"], "succ_code": ["S1"]})),
    ]
    trail = flagged_trail(results)
    assert trail.columns.tolist() == ["check_id", "check", "check_status", "task_code", "pred_code", "succ_code"]
    assert trail["check_id"].tolist() == ["A", "A", "C"] and trail["check_status"].tolist() == ["fail", "fail", "info"]
    assert trail["task_code"].tolist()[:2] == ["T1", "T2"] and pd.isna(trail["task_code"].iloc[2])
    assert trail["succ_code"].iloc[2] == "S1"
    assert flagged_trail([_check("B", "pass")]).empty


def test_flagged_codes_name_each_activity_once_and_no_end_outside_the_file():
    """Tasks T1, T2, T1 again: T1, T2. Links A -> B, B -> [ext] X, blank -> C: A, B (once), C; the
    external end and the blank are not activities of the file."""
    assert flagged_codes(pd.DataFrame({"task_code": ["T1", "T2", "T1"]})) == ["T1", "T2"]
    links = pd.DataFrame({"pred_code": ["A", "B", None], "succ_code": ["B", "[ext] X", "C"]})
    assert flagged_codes(links) == ["A", "B", "C"]
    assert flagged_codes(pd.DataFrame({"wbs_code": ["W"]})) == []


def test_shown_by_group_keeps_the_groups_in_order_of_first_appearance():
    """A standard that interleaves its groups: 1 (Logic, fail), 2 (Dates, pass), 3 (Logic, pass),
    4 (Dates, fail). All: Logic [1, 3] then Dates [2, 4]. Failed only: Logic [1], Dates [4]."""
    results = [
        _check("1", "fail", "Logic"),
        _check("2", "pass", "Dates"),
        _check("3", "pass", "Logic"),
        _check("4", "fail", "Dates"),
    ]
    ids = lambda groups: {group: [result.metric.id for result in shown] for group, shown in groups.items()}  # noqa: E731
    assert ids(shown_by_group(results)) == {"Logic": ["1", "3"], "Dates": ["2", "4"]}
    assert list(shown_by_group(results)) == ["Logic", "Dates"]
    assert ids(shown_by_group(results, only_failed=True)) == {"Logic": ["1"], "Dates": ["4"]}
    assert shown_by_group([_check("2", "pass", "Dates")], only_failed=True) == {}


def test_report_counts_hold_one_line_per_check_filled_where_the_report_names_it():
    """Checks A, B, C. No report: three blank lines. A report naming B (4 of 10) and Z (unknown):
    B filled, A and C blank, Z left out."""
    got = pd.DataFrame({"id": ["A", "B", "C"], "check": ["a", "b", "c"], "found": [1, 2, 3], "total": [9, 9, 9]})
    blank = report_counts(got)
    assert blank["id"].tolist() == ["A", "B", "C"] and blank["check"].tolist() == ["a", "b", "c"]
    assert blank["found"].isna().all() and blank["total"].isna().all()
    assert str(blank["found"].dtype) == "Int64"  # the editor takes whole numbers
    typed = pd.DataFrame({"id": ["B", "Z"], "found": [4, 1], "total": [10, 1]})
    lines = report_counts(got, typed).set_index("id")
    assert lines.index.tolist() == ["A", "B", "C"]
    assert (lines.loc["B", "found"], lines.loc["B", "total"]) == (4, 10)
    assert lines.loc[["A", "C"], ["found", "total"]].isna().all().all()


def test_mismatch_count_counts_the_checks_that_differ_from_the_report():
    """xerscope: A 1 of 9, B 2 of 9. The report: A 1 of 9 (same), B 3 of 9 (found differs), D 0 of 5
    (no such check). Two differ."""
    got = pd.DataFrame({"id": ["A", "B"], "check": ["a", "b"], "found": [1, 2], "total": [9, 9]})
    got[["found", "total"]] = got[["found", "total"]].astype("Int64")
    typed = pd.DataFrame({"id": ["A", "B", "D"], "found": [1, 3, 0], "total": [9, 9, 5]})
    assert mismatch_count(compare_counts(got, typed)) == 2


# --- items: a standard scored by the criteria of its source, not by its metrics -----------------


def _item_results(*rows: tuple[str, str, str]) -> list[CheckResult]:
    """(metric id, item, status) rows as results; ``item`` "" leaves the metric its own criterion."""
    return [
        CheckResult(Metric(id=metric_id, name=metric_id, standard="T", rule="p6_01_logic", item=item), status)
        for metric_id, item, status in rows
    ]


@pytest.mark.oracle("standard")
def test_score_counts_the_items_of_the_source_not_the_metrics():
    """A checklist item written as two metrics is one criterion: it passes when every metric of it
    passes, fails when one fails, and the failed label names the metric that failed. Hand count:
    item 1 = T-01 pass + T-02 fail -> fail; T-03 alone pass; item 2 = T-04 pass + T-05 n/a -> pass
    (n/a weighs nothing); item 3 = T-06 info -> not evaluated. 2 passed / 3 evaluated."""
    score = standard_score(
        _item_results(
            ("T-01", "1", "pass"),
            ("T-02", "1", "fail"),
            ("T-03", "", "pass"),
            ("T-04", "2", "pass"),
            ("T-05", "2", "n/a"),
            ("T-06", "3", "info"),
        )
    )
    assert (score.passed, score.evaluated, score.failed_ids) == (2, 3, ("1 (T-02)",))
    assert (score.value, score.detail) == ("67 %", "3 evaluated · 1 fail: 1 (T-02)")


@pytest.mark.oracle("standard")
def test_an_item_with_two_failed_metrics_is_one_fail_naming_both():
    score = standard_score(_item_results(("A", "9", "fail"), ("B", "9", "fail"), ("C", "", "pass")))
    assert (score.passed, score.evaluated, score.failed_ids) == (1, 2, ("9 (A, B)",))


def test_item_is_read_from_the_toml_and_must_be_a_string():
    standard = loads_standard(
        HEAD + _metric("T-01", "p6_01_logic", "< 5%").replace('name = "T-01"', 'name = "T-01"\nitem = "1"')
    )
    assert standard["T-01"].item == "1"
    with pytest.raises(ValueError, match=r"T-01.*item must be a string"):
        loads_standard(
            HEAD + _metric("T-01", "p6_01_logic", "< 5%").replace('name = "T-01"', 'name = "T-01"\nitem = 1')
        )


def test_p6_invalid_progress_dates_is_one_check_of_the_dialog():
    """101248 lists Invalid Progress Dates once; P6 Professional 26.8 prints it on two lines (before /
    after the data date). The two metrics are one item of the score: 17 criteria, as the dialog's
    14 plus the three report-only checks (P6-15 to P6-17)."""
    from xerscope.analysis import builtin_standards

    p6 = builtin_standards()["P6"]
    assert p6["P6-10a"].item == "P6-10" == p6["P6-10b"].item
    assert len({metric.item or metric.id for metric in p6.metrics}) == 17
