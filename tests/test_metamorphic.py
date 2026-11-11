"""Three changes to a schedule that leave every check result as it was (seeded random schedules).

No P6 output exists for these schedules: each is compared with itself, changed in a way that does
not change the plan. The stored dates and floats are the engine's own, as a file exported after a
calculation; some schedules carry a Must Finish By date. The baseline is the planned dates.

- rows in another order (tasks and relationships, so the task ids of the file change too):
  every metric gives the same verdict, counts, value and list
- tasks renamed, the order of the Activity IDs kept: the same, under the new names. The order is
  kept because the critical path test delays, among the open tasks of the longest path that start
  first, the one with the lowest Activity ID (``cpm.critical_path_test``)
- the schedule twice in one file, no relationship between the two copies: counts and lists
  double; percentages, indices and verdicts stay
"""

from __future__ import annotations

import functools
import random

import pandas as pd
import pytest
from rulekit import STANDARDS
from test_cpm_properties import random_network
from xerkit import CONSTRAINT_TYPES, snap

from xerscope.analysis import AnalysisContext, Baseline, run_metric
from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("property")

SEEDS = range(12)
STORED = {
    "es": "early_start_date",
    "ef": "early_end_date",
    "ls": "late_start_date",
    "lf": "late_end_date",
}


def random_plan(seed: int) -> dict:
    """The arguments of ``xerkit.snap`` for a random schedule, dates and floats as the engine computes them."""
    rnd = random.Random(7000 + seed)
    tasks, links = random_network(seed, n=rnd.randint(2, 16))
    for task in tasks:
        task["clndr_id"] = rnd.choice(["C8", "C8", "C10", "C7D"])
        if rnd.random() < 0.2:
            task["cstr_type"] = rnd.choice(CONSTRAINT_TYPES)
            task["cstr_date"] = rnd.choice(["2026-03-09 08:00", "2026-04-06 08:00"])
        if rnd.random() < 0.08 and task.get("status_code", "TK_NotStart") == "TK_NotStart":
            task["task_type"] = "TT_LOE"
        if rnd.random() < 0.5:
            task["target_work_qty"] = str(rnd.choice([8, 40, 80]))
        task["target_start_date"] = f"2026-03-{rnd.randint(1, 27):02d} 08:00"
        task["target_end_date"] = f"2026-04-{rnd.randint(1, 28):02d} 17:00"
    plan = {
        "tasks": tasks,
        "preds": links,
        "rsrc": [task["task_code"] for task in tasks if rnd.random() < 0.4],
        "data_date": rnd.choice(["2026-03-02 08:00", "2026-03-16 08:00", "2026-04-13 08:00"]),
        "project": None,
    }
    if rnd.random() < 0.4:
        plan["project"] = {"plan_end_date": rnd.choice(["2026-03-27 17:00", "2026-05-29 17:00"])}
    computed = schedule(_snapshot(plan)).frame
    for task in tasks:
        row = computed.loc[task["task_code"]]
        for column, stored in STORED.items():
            task[stored] = "" if pd.isna(row[column]) else f"{row[column]:%Y-%m-%d %H:%M}"
        task["total_float_hr_cnt"] = "" if pd.isna(row["tf_hr"]) else f"{row['tf_hr']:g}"
    return plan


def _snapshot(plan: dict):
    return snap(plan["tasks"], plan["preds"], **{key: plan[key] for key in ("rsrc", "data_date", "project")})


def _renamed(plan: dict, name) -> dict:
    return {
        **plan,
        "tasks": [dict(task, task_code=name(task["task_code"])) for task in plan["tasks"]],
        "preds": [(name(pred), name(succ), *rest) for pred, succ, *rest in plan["preds"]],
        "rsrc": [name(code) for code in plan["rsrc"]],
    }


def _results(plan: dict) -> dict:
    """Per metric id: verdict, numerator, denominator, value, unit and the listed tasks or relationships."""
    snapshot = _snapshot(plan)
    context = AnalysisContext(snapshot, baseline=Baseline.planned(snapshot))
    found = {}
    for standard in STANDARDS.values():
        for metric in standard.metrics:
            result = run_metric(metric, context)
            listed = result.flagged
            names = [column for column in ("task_code", "pred_code", "succ_code") if column in listed]
            rows = sorted(tuple(row) for row in listed[names].itertuples(index=False)) if names else len(listed)
            found[metric.id] = {
                "status": result.status,
                "numerator": result.numerator,
                "denominator": result.denominator,
                "value": result.value,
                "unit": metric.unit,
                "listed": rows,
            }
    return found


@functools.cache
def _base(seed: int) -> tuple[dict, dict]:
    plan = random_plan(seed)
    return plan, _results(plan)


def _differences(before: dict, after: dict) -> dict:
    """The metrics whose result is not the same, with both results (empty when all agree)."""
    differ = {}
    for metric_id, old in before.items():
        new = after[metric_id]
        same_value = old["value"] == new["value"] or (
            None not in (old["value"], new["value"]) and old["value"] == pytest.approx(new["value"])
        )
        if not same_value or any(old[key] != new[key] for key in ("status", "numerator", "denominator", "listed")):
            differ[metric_id] = (old, new)
    return differ


@pytest.mark.parametrize("seed", SEEDS)
def test_the_order_of_the_rows_changes_no_result(seed):
    plan, before = _base(seed)
    rnd = random.Random(seed)
    tasks, links = list(plan["tasks"]), list(plan["preds"])
    rnd.shuffle(tasks)
    rnd.shuffle(links)
    assert not _differences(before, _results({**plan, "tasks": tasks, "preds": links}))


@pytest.mark.parametrize("seed", SEEDS)
def test_renaming_the_tasks_in_the_same_order_changes_no_result(seed):
    plan, before = _base(seed)
    rank = {code: i for i, code in enumerate(sorted(task["task_code"] for task in plan["tasks"]))}
    old_name = {f"wp-{i:03d}.x": code for code, i in rank.items()}
    after = _results(_renamed(plan, lambda code: f"wp-{rank[code]:03d}.x"))
    for result in after.values():
        if isinstance(result["listed"], list):
            result["listed"] = sorted(tuple(old_name[code] for code in row) for row in result["listed"])
    assert not _differences(before, after)


@pytest.mark.parametrize("seed", SEEDS)
def test_two_copies_side_by_side_double_the_counts_and_keep_the_shares(seed):
    plan, before = _base(seed)
    copy = _renamed(plan, lambda code: code + "b")
    twice = {**plan, **{key: plan[key] + copy[key] for key in ("tasks", "preds", "rsrc")}}
    expected = {}
    for metric_id, old in before.items():
        listed = old["listed"]
        expected[metric_id] = {
            **old,
            "numerator": None if old["numerator"] is None else 2 * old["numerator"],
            "denominator": None if old["denominator"] is None else 2 * old["denominator"],
            "value": 2 * old["value"] if old["unit"] == "count" and old["value"] is not None else old["value"],
            "listed": sorted(listed + [tuple(code + "b" for code in row) for row in listed])
            if isinstance(listed, list)
            else 2 * listed,
        }
    assert not _differences(expected, _results(twice))
