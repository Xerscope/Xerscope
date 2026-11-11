"""Contracts every check result must satisfy, on random schedules (seeded, so a failure reproduces).

No P6 output exists for these schedules: they check what a result must be whatever the schedule,
for every metric of the built-in standards, without a baseline, with the planned dates as baseline
and with another schedule as baseline (tasks of the same codes with other types and dates).

- no rule raises (no ``error`` status); the counts are not negative
- ``%`` and ``count`` metrics: the numerator is at most the denominator, and the value follows from
  the two; the rows behind the denominator are as many as it says, and so is the last funnel step
- a result without a population is never a failure; ``n/a`` carries no value, ``pass`` and ``fail``
  carry one
- the listed rows are the numerator, each once, and are tasks of the population

Left out, each for a reason:
- the indices (P6-13, DCMA-13, DCMA-14) are not bound by their denominator: a BEI above 1.00 is
  "a higher task throughput than planned" (PAM 200.1 §3.1.2.4), and (CPL + TF) / CPL is negative
  when the float is more negative than the path is long. Only the BEI is known to be >= 0.
- P6-13 counts completed tasks of the update over the tasks of the baseline: its list is read on
  the update and can hold a task the baseline leaves out (a milestone there, a task here).
- P6-07 and DCMA-04 count the FS relationships and list the others; P6-13 and DCMA-14 count the
  completed tasks and list those due and not completed; P6-15 lists one row per predecessor.
"""

from __future__ import annotations

import random

import pytest
from rulekit import STANDARDS
from test_cpm_properties import random_network
from xerkit import CONSTRAINT_TYPES, snap

from xerscope.analysis import AnalysisContext, Baseline, run_metric

pytestmark = pytest.mark.oracle("property")

SEEDS = range(15)
INDICES = {"P6-13", "DCMA-13", "DCMA-14"}
LISTS_ANOTHER_SET = {"P6-07", "DCMA-04", "P6-13", "DCMA-14"}  # the list is not the numerator
ONE_ROW_PER_PREDECESSOR = {"P6-15"}
LISTED_ON_THE_UPDATE = {"P6-13"}  # the population is the baseline's


def random_schedule(seed: int):
    """A random network with calendars, floats, constraints, level of effort, hours and resources."""
    rnd = random.Random(7000 + seed)
    tasks, links = random_network(seed, n=rnd.randint(1, 18))
    for task in tasks:
        task["clndr_id"] = rnd.choice(["C8", "C8", "C10", "C7D"])
        task["total_float_hr_cnt"] = str(rnd.choice([0, 0, 8, 80, 400, -8, -80]))
        if rnd.random() < 0.2:
            task["cstr_type"] = rnd.choice(CONSTRAINT_TYPES)
            task["cstr_date"] = rnd.choice(["2026-03-09 08:00", "2026-04-06 08:00"])
        if rnd.random() < 0.1:
            task["cstr_type2"] = rnd.choice(CONSTRAINT_TYPES)
            task["cstr_date2"] = "2026-03-20 17:00"
        if rnd.random() < 0.08 and task.get("status_code", "TK_NotStart") == "TK_NotStart":
            task["task_type"] = "TT_LOE"
        if rnd.random() < 0.5:
            task["target_work_qty"] = str(rnd.choice([8, 40, 80]))
        task["target_start_date"] = f"2026-03-{rnd.randint(1, 27):02d} 08:00"
        task["target_end_date"] = f"2026-04-{rnd.randint(1, 28):02d} 17:00"
    with_resource = [task["task_code"] for task in tasks if rnd.random() < 0.4]
    status_date = rnd.choice(["2026-03-02 08:00", "2026-03-16 08:00", "2026-04-13 08:00"])
    return snap(tasks, links, rsrc=with_resource, data_date=status_date)


def _check(result, where) -> None:
    metric, numerator, denominator, value = result.metric, result.numerator, result.denominator, result.value
    assert result.status != "error", (where, result.note)
    assert numerator is None or numerator >= 0, (where, "numerator")
    assert denominator is None or denominator >= 0, (where, "denominator")
    if result.status == "n/a":
        assert value is None, (where, "n/a with a value")
    if result.status in ("pass", "fail"):
        assert value is not None, (where, "judged without a value")
    if denominator == 0:
        assert result.status != "fail", (where, "fails on an empty population")
    if metric.id in INDICES:
        if metric.id != "DCMA-13" and value is not None:
            assert value >= 0, (where, "negative index")
    elif numerator is not None and denominator is not None:
        assert numerator <= denominator, (where, "numerator above denominator")
        if metric.unit == "%" and denominator:
            assert value == pytest.approx(100 * numerator / denominator), (where, "% value")
        if metric.unit == "count":
            assert value == pytest.approx(numerator), (where, "count value")
    if denominator is not None and result.checked is not None:
        assert len(result.checked) == denominator, (where, "rows behind the denominator")
    if denominator is not None and result.funnel is not None and result.funnel.steps:
        assert len(result.funnel.rows) == denominator, (where, "last funnel step")

    listed = result.flagged
    if numerator is not None and metric.id not in LISTS_ANOTHER_SET | ONE_ROW_PER_PREDECESSOR:
        assert len(listed) == numerator, (where, "listed rows are not the numerator")
    if len(listed) and metric.id not in ONE_ROW_PER_PREDECESSOR:
        key = [column for column in ("pred_code", "succ_code", "pred_type", "lag_hr") if column in listed]
        assert not listed.duplicated(key or ["task_code"]).any(), (where, "a row listed twice")
    population = result.checked
    tasks_listed = len(listed) and "task_code" in listed and "pred_code" not in listed
    if tasks_listed and population is not None and metric.id not in LISTED_ON_THE_UPDATE:
        assert set(listed["task_code"]) <= set(population["task_code"]), (where, "listed outside the population")


@pytest.mark.parametrize("seed", SEEDS)
def test_every_result_keeps_its_contracts(seed):
    update = random_schedule(seed)
    baselines = {
        "none": None,
        "planned dates": Baseline.planned(update),
        "another schedule": Baseline.from_snapshot(random_schedule(seed + 1)),
    }
    for kind, baseline in baselines.items():
        context = AnalysisContext(update, baseline=baseline)
        for standard in STANDARDS.values():
            for metric in standard.metrics:
                _check(run_metric(metric, context), (seed, kind, metric.id))
