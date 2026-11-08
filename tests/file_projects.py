"""XER text with two projects in one file, for the tests of the P6 Project Baseline pointer."""

from __future__ import annotations

from xerkit import xer_text

POINTERS = ("sum_base_proj_id", "orig_proj_id", "last_baseline_update_date")
BASELINE_DATE = "2026-01-12 08:00"


def two_projects(
    pointer: str = "2",
    original: str = "1",
    *,
    data_date: str = "2026-03-02 08:00",
    baseline_finish: str = "2026-03-06 17:00",
    baseline_ids: tuple[str, ...] = ("A1", "A2"),
    with_baseline: bool = True,
    baseline_code: str = "BL",
    baseline_date: str = "2026-01-05 08:00",
    flag: str = "",
    code: str = "UPD",
) -> str:
    """Project 1 (analysed, A1 and A2, early finish 2026-03-13 17:00) with ``sum_base_proj_id = pointer``;
    project 2 (the baseline copy: ``baseline_ids``, all finishing ``baseline_finish``) with
    ``orig_proj_id = original``. ``with_baseline=False`` leaves project 2 out, the pointer stays."""
    analysed = {
        "proj_short_name": code,
        "sum_base_proj_id": pointer,
        "use_project_baseline_flag": flag,
        "orig_proj_id": "",
        "last_baseline_update_date": "",
    }
    baseline = {
        "proj_id": "2",
        "proj_short_name": baseline_code,
        "last_recalc_date": baseline_date,
        "plan_start_date": baseline_date,
        "clndr_id": "C8",
        "sum_base_proj_id": "",
        "orig_proj_id": original,
        "last_baseline_update_date": BASELINE_DATE,
    }
    tasks = [{"task_code": "A1"}, {"task_code": "A2"}]
    if with_baseline:
        tasks += [
            {"task_code": code, "task_id": str(100 + i), "proj_id": "2", "early_end_date": baseline_finish}
            for i, code in enumerate(baseline_ids)
        ]
    lines = xer_text(tasks, project=analysed, data_date=data_date).splitlines()
    if with_baseline:
        fields = lines[lines.index("%T\tPROJECT") + 1].split("\t")[1:]
        lines.insert(lines.index("%T\tPROJECT") + 3, "%R\t" + "\t".join(baseline.get(f, "") for f in fields))
    return "\n".join(lines) + "\n"


def with_other_projects(text: str, codes: tuple[str, ...] = ("P3", "P4", "P5")) -> str:
    """``text`` plus one project per code (proj_id 3, 4, …, no pointer), one activity each: a file
    exported with other projects of the portfolio."""
    lines = text.splitlines()
    at = lines.index("%T\tPROJECT")
    fields = lines[at + 1].split("\t")[1:]
    project = dict(zip(fields, lines[at + 2].split("\t")[1:], strict=True))
    task_at = lines.index("%T\tTASK")
    task_fields = lines[task_at + 1].split("\t")[1:]
    task = dict(zip(task_fields, lines[task_at + 2].split("\t")[1:], strict=True))
    for number, code in enumerate(codes, start=3):
        row = {**project, "proj_id": str(number), "proj_short_name": code, "sum_base_proj_id": "", "orig_proj_id": ""}
        lines.insert(at + 2, "%R\t" + "\t".join(row.get(f, "") for f in fields))
        task_at += 1
        row = {**task, "task_id": str(300 + number), "proj_id": str(number), "task_code": f"Z{number}"}
        lines.insert(task_at + 2, "%R\t" + "\t".join(row.get(f, "") for f in task_fields))
    return "\n".join(lines) + "\n"
