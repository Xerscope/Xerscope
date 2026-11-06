"""A file whose project holds one Activity ID twice (a merged or hand-made file: P6 does not write it).

xerscope keeps the first TASK row of each repeated Activity ID, leaves the other rows out with their
relationships, assignments and expenses, and says so in the load warnings. These tests measure what that
choice does to the results, so a change of the choice shows up here.

The file: A -> B(first row) -> C, and a second row of B (task_id 3) with its own link from A, its own
1 000 cost assignment and its own 70 expense; the first row of B carries a 1 000 cost assignment too.
"""

import sys

import pytest
from xerkit import todo, xer_text

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.xer import build_snapshot, parse_text

FIRST_B, SECOND_B = "2", "3"


def _with_second_row_of_b() -> str:
    text = xer_text(
        [todo("A"), {"task_code": "B", "task_id": FIRST_B}, {"task_code": "C", "task_id": "4"}],
        [("A", "B", "FS", 0), ("B", "C", "FS", 0)],
        assign=[{"task_code": "B", "rsrc_id": "R1", "target_cost": "1000", "target_qty": "8"}],
        costs=[{"task_code": "B", "target_cost": "30"}],
    )
    lines = text.splitlines()

    def add_row(table: str, **values) -> None:
        header = lines.index(f"%T\t{table}") + 1
        columns = lines[header].split("\t")[1:]
        model = dict(zip(columns, lines[header + 1].split("\t")[1:], strict=True))
        lines.insert(header + 1, "%R\t" + "\t".join(str(values.get(c, model[c])) for c in columns))

    add_row("TASK", task_id=SECOND_B, task_code="B", task_name="B second row")
    add_row("TASKPRED", task_pred_id="9", task_id=SECOND_B, pred_task_id="1")
    add_row("TASKRSRC", taskrsrc_id="900", task_id=SECOND_B, target_cost="1000")
    add_row("PROJCOST", cost_item_id="90", task_id=SECOND_B, target_cost="70")
    # the second B row must come after the first in TASK, as a later row of the file
    task_header = lines.index("%T\tTASK") + 1
    rows = lines[task_header + 1 : task_header + 5]
    rows.sort(key=lambda line: int(line.split("\t")[1]))
    lines[task_header + 1 : task_header + 5] = rows
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot(parse_text(_with_second_row_of_b(), source="merged.xer"))


def test_the_first_row_is_kept_and_the_warning_names_the_code_and_the_rows_left_out(snapshot):
    assert snapshot.activities["task_code"].tolist().count("B") == 1
    assert snapshot.by_code.loc["B", "task_id"] == FIRST_B
    repeated = [w for w in snapshot.warnings if "Activity ID repeated" in w]
    assert len(repeated) == 1 and "['B']" in repeated[0] and "1 TASK row(s)" in repeated[0]
    assert any("1 relationship(s) of the TASK rows left out" in w for w in snapshot.warnings)


def test_the_left_out_row_brings_no_relationship_assignment_or_expense(snapshot):
    links = snapshot.relationships
    assert sorted(zip(links["pred_code"], links["succ_code"], strict=True)) == [("A", "B"), ("B", "C")]
    assert snapshot.assignments["task_id"].tolist() == [FIRST_B]
    assert set(snapshot.expenses["task_id"]) <= {FIRST_B, SECOND_B}  # the table as read; costs below


def test_baseline_cost_counts_the_kept_row_only(snapshot):
    """DF-2: before, bl_cost of B summed both rows (2 000 + both expenses) on the first row's dates."""
    baseline = Baseline.from_snapshot(snapshot)
    assert baseline.frame.loc["B", "bl_cost"] == pytest.approx(1000 + 30)


def test_every_check_runs_on_the_file(snapshot):
    """DF-1: before, eight checks ended in InvalidIndexError (P6-05, 07, 08, 09, DCMA-02, 03, 04, INT-08)."""
    context = AnalysisContext(snapshot, None, baseline=Baseline.from_snapshot(snapshot))
    statuses = {
        result.metric.id: result.status
        for standard in ("P6", "DCMA", "INTEGRITY")
        for result in run_standard(builtin_standards()[standard], context)
    }
    assert [metric for metric, status in statuses.items() if status == "error"] == []


def test_an_expense_on_a_task_the_project_does_not_hold_is_reported():
    """DF-5: the cost dropped out of every total without a word."""
    text = xer_text([todo("A")], costs=[{"task_code": "A", "target_cost": "50"}])
    lines = text.splitlines()
    header = lines.index("%T\tPROJCOST") + 1
    columns = lines[header].split("\t")[1:]
    row = dict(zip(columns, lines[header + 1].split("\t")[1:], strict=True), cost_item_id="77", task_id="999")
    lines.insert(header + 2, "%R\t" + "\t".join(row[c] for c in columns))
    snapshot = build_snapshot(parse_text("\n".join(lines) + "\n", source="orphan.xer"))
    assert any("1 PROJCOST row(s) of the project on a task it does not hold" in w for w in snapshot.warnings)


def test_a_task_without_finish_date_is_named_in_the_lateness_note():
    """DF-3: P6-12 kept it in the denominator without a word; it is still counted, and now said."""
    current = build_snapshot(parse_text(xer_text([todo("A", early_end_date=""), todo("B")]), source="u.xer"))
    planned = build_snapshot(parse_text(xer_text([todo("A"), todo("B")]), source="b.xer"))
    context = AnalysisContext(current, None, baseline=Baseline.from_snapshot(planned))
    p6_12 = next(r for r in run_standard(builtin_standards()["P6"], context) if r.metric.id == "P6-12")
    assert p6_12.denominator == 2 and "1 task(s) without a finish date" in p6_12.note


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
