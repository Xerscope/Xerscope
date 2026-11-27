"""A random network of 3,978 activities (tests/scale_network.py): the checks against what the
generator planted, the CPM against MPXJ's scheduler.

**Checks.** Each check is answered here from the generator's own records (status, type, calendar,
links, stored dates and floats, constraints, assignments), by one function that follows the text
of the check's source as docs/formulas.md section 2 states it, never by reading xerscope's code or
output. The test asserts the exact list of activities (or relationships) found and the exact
denominator. The same file with its TASK and TASKPRED rows shuffled must give the same answers.
Baseline: the planned dates of the file (``Baseline.planned``), which the generator wrote.

Checks left out, because their answer is a recalculation or needs a second update, not a value the
generator plants: DCMA-12, DCMA-13, 06A401a (critical path), 06A504a, 06A504b, 06A506c (an update
28 days older), 06A208a (the file has no WBS summary activity), and the Integrity standard (INT-01
to INT-08 compare with the CPM). DCMA-14 and P6-13 are asserted on value and denominator: the
generator plants no completed activity that was not due, so the numerator is unambiguous.

**CPM.** xerscope's dates and floats against MPXJ's PrimaveraScheduler, activity by activity, on
``Network.for_mpxj`` (the constraints on which the two were seen to differ removed, see there). A
difference is accepted only where MPXJ's own dates contradict its logic (``mpxj_inconsistent``) or
follow from such a date through the links (successors for early dates, predecessors for late
dates), or where ``excused_row`` names it. The network holds no shape of ``crosscheck.UNRESOLVED``
or ``P6_SETTLED``. Needs Java and the built scheduler, skipped otherwise as tests/test_crosscheck_mpxj.py.

**Into P6.** P6's own recalculation is the best oracle for the dates. Write the file with
``PYTHONPATH=src:tests python tests/scale_network.py scale.xer`` (or ``Network.for_mpxj().write``
for the file the CPM is compared on), import it in P6 Professional (File > Import > XER, new
project), schedule (F9) with the file's options, export it again and compare with
``xerscope crosscheck --cpm scale.xer``: the stored dates are then P6's (column ``xs_p6``).

Measured 2026-11-27 on a 4-CPU container: generation 0.4 s, reading 0.5 s, the five standards
0.3 to 1.0 s each, the CPM 0.6 s, the MPXJ comparison 5 s (11,987 values; 349 differ, all after
one of 23 activities whose MPXJ dates contradict their logic: 97.1 % identical).
"""

from __future__ import annotations

import time

import pandas as pd
import pytest
from conftest import missing, mpxj_or_skip
from scale_network import Activity, Network, generate

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.xer import load_snapshot

pytestmark = pytest.mark.slow

LIMIT_HR = 352  # p6.toml limit_hours: the dialog's x
LIMIT_WD = 44  # dcma.toml / decm.toml limit_days
DCMA_HARD = {"CS_MSO", "CS_MSOB", "CS_MEO", "CS_MEOB", "CS_MANDSTART", "CS_MANDFIN"}
P6_HARD = {"CS_MANDSTART", "CS_MSO", "CS_MANDFIN", "CS_MEO"}
P6_SOFT = {"CS_MSOB", "CS_MSOA", "CS_MEOB", "CS_MEOA", "CS_ALAP"}
START_CONSTRAINTS = {"CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MANDSTART"}
DECM_HARD = {"CS_MANDSTART", "CS_MANDFIN"}
STANDARD_SECONDS = 10.0  # slowest measured 1.0 s


# --- the network and xerscope's answers ------------------------------------------------------------


@pytest.fixture(scope="module")
def network() -> Network:
    return generate()


def results_of(path) -> dict[str, object]:
    snapshot = load_snapshot(path)
    context = AnalysisContext(snapshot, None, Baseline.planned(snapshot))
    results = {}
    for standard_id in ("P6", "DCMA", "DECM"):
        started = time.perf_counter()
        for result in run_standard(builtin_standards()[standard_id], context):
            results[result.metric.id] = result
        elapsed = time.perf_counter() - started
        assert elapsed < STANDARD_SECONDS, f"{standard_id}: {elapsed:.1f} s"
    return results


@pytest.fixture(scope="module")
def results(network, tmp_path_factory):
    return results_of(network.write(tmp_path_factory.mktemp("scale") / "scale.xer"))


@pytest.fixture(scope="module")
def shuffled_results(network, tmp_path_factory):
    """The same file, its TASK and TASKPRED rows in another order and nothing else changed."""
    original, shuffled = network.text(), network.text(shuffle_seed=7)
    assert shuffled != original and sorted(shuffled.splitlines()) == sorted(original.splitlines())
    path = tmp_path_factory.mktemp("shuffled") / "scale.xer"
    path.write_text(shuffled, encoding="utf-8")
    return results_of(path)


def found(result) -> set:
    """Activity IDs, or (predecessor, successor) pairs for a relationship check."""
    flagged = result.flagged
    if "pred_code" in flagged and "succ_code" in flagged:
        return set(zip(flagged["pred_code"], flagged["succ_code"], strict=True))
    return set(flagged["task_code"]) if "task_code" in flagged else set()


# --- populations, as the standards state them ------------------------------------------------------


def activities(network: Network, keep) -> list[Activity]:
    return [activity for activity in network.activities.values() if keep(activity)]


def is_open_task(activity: Activity) -> bool:
    """DCMA 14-Point population (PAM 200.1 §4.0): incomplete, not LOE, not milestone."""
    return not activity.is_complete and not activity.is_loe and not activity.is_milestone


def is_open_not_loe(activity: Activity) -> bool:
    """P6 Check Schedule (101248): WBS summary, actual finish and LOE removed."""
    return not activity.is_complete and not activity.is_loe


def dcma_links(network: Network) -> list:
    """PAM 200.1 §4.0: links into incomplete, non-LOE, non-milestone tasks."""
    return [link for link in network.links if is_open_task(network.activities[link.succ])]


def p6_links(network: Network) -> list:
    """P6 46287-46290: every link but those between two finished activities."""

    def both_complete(link):
        return network.activities[link.pred].is_complete and network.activities[link.succ].is_complete

    return [link for link in network.links if not both_complete(link)]


def constraints(activity: Activity) -> set[str]:
    return {activity.cstr_type, activity.cstr_type2} - {""}


def day(moment: pd.Timestamp | None):
    return None if moment is None else moment.normalize()


def finish(activity: Activity) -> pd.Timestamp | None:
    """Actual finish, else forecast (remaining) finish."""
    return activity.act_end if activity.act_end is not None else activity.forecast_finish


def start(activity: Activity) -> pd.Timestamp | None:
    return activity.act_start if activity.act_start is not None else activity.forecast_start


def is_late(activity: Activity) -> bool:
    """Finish later than the baseline finish in working time. The generator never leaves the two
    less than a week apart unless the finish is the earlier or the same, so the working-time
    comparison reduces to the calendar one."""
    slip = finish(activity) - activity.target_end
    assert slip <= pd.Timedelta(0) or slip >= pd.Timedelta(days=7), activity.code
    return slip > pd.Timedelta(0)


# --- the expected answer of each check: (found, denominator) --------------------------------------


def dcma_01(network):
    """PAM 200.1 §4.1: any incomplete task missing a predecessor and/or a successor; §4.0 population."""
    population = activities(network, is_open_task)
    return {
        activity.code
        for activity in population
        if not network.predecessors(activity.code) or not network.successors(activity.code)
    }, len(population)


def dcma_02(network):
    """§4.2: links with a lead (negative lag), §4.0 links."""
    links = dcma_links(network)
    return {(link.pred, link.succ) for link in links if link.lag_hr < 0}, len(links)


def dcma_03(network):
    """§4.3: links with a lag (positive)."""
    links = dcma_links(network)
    return {(link.pred, link.succ) for link in links if link.lag_hr > 0}, len(links)


def dcma_05(network):
    """§4.5: MSO, MFO, SNLT, FNLT and mandatory, primary or secondary, counted once per task."""
    population = activities(network, is_open_task)
    return {activity.code for activity in population if constraints(activity) & DCMA_HARD}, len(population)


def dcma_06(network):
    """§4.6: total float greater than 44 working days of the activity's calendar."""
    population = activities(network, is_open_task)
    return {
        activity.code for activity in population if activity.total_float_hr / activity.hours_per_day > LIMIT_WD
    }, len(population)


def dcma_07(network):
    """§4.7: total float less than 0."""
    population = activities(network, is_open_task)
    return {activity.code for activity in population if activity.total_float_hr < 0}, len(population)


def dcma_08(network):
    """§4.8: baseline duration greater than 44 working days (baseline = the planned dates and the
    original duration of the file)."""
    population = activities(network, is_open_task)
    return {activity.code for activity in population if activity.target_hr / activity.hours_per_day > LIMIT_WD}, len(
        population
    )


def dcma_09(network):
    """§4.9, by calendar day: not started with a forecast start before the status date, a forecast
    finish before it, or an actual start or finish after it."""
    data_day = network.data_date.normalize()
    population = activities(network, is_open_task)

    def is_invalid(activity):
        if not activity.is_started and day(activity.forecast_start) < data_day:
            return True
        if day(activity.forecast_finish) < data_day:
            return True
        return activity.act_start is not None and day(activity.act_start) > data_day

    return {activity.code for activity in population if is_invalid(activity)}, len(population)


def dcma_10(network):
    """§4.10: tasks with a duration and no resource or cost, §4.0 population."""
    population = activities(network, lambda activity: is_open_task(activity) and activity.target_hr > 0)
    return {activity.code for activity in population if not activity.has_assignment and not activity.has_expense}, len(
        population
    )


def dcma_11(network):
    """§4.11: baseline finish on or before the status date (calendar day), finished or forecast to
    finish later; completed tasks stay in; LOE and milestones out."""
    data_day = network.data_date.normalize()

    def is_due(activity):
        is_task = not activity.is_loe and not activity.is_milestone
        return (
            is_task
            and activity.target_start is not None
            and activity.target_end is not None
            and day(activity.target_end) <= data_day
        )

    population = activities(network, is_due)
    return {activity.code for activity in population if is_late(activity)}, len(population)


def dcma_14(network):
    """§3.1.2.4: completed by the status date / due by it (or without a baseline finish); LOE,
    milestones and tasks without duration out. Returns (value, denominator)."""
    data_day = network.data_date.normalize()
    population = activities(
        network, lambda activity: not activity.is_loe and not activity.is_milestone and activity.target_hr > 0
    )
    due = [activity for activity in population if activity.target_end is None or day(activity.target_end) <= data_day]
    completed = [activity for activity in population if activity.is_complete and day(activity.act_end) <= data_day]
    assert {activity.code for activity in completed} <= {
        activity.code for activity in due
    }  # no completed task outside the due ones
    return len(completed) / len(due), len(due)


def p6_01(network):
    """101248: completed activities out; no successor, or no predecessor unless started."""
    population = activities(network, lambda activity: not activity.is_complete)

    def is_open_end(activity):
        return not network.successors(activity.code) or (
            not network.predecessors(activity.code) and not activity.is_started
        )

    return {activity.code for activity in population if is_open_end(activity)}, len(population)


def constrained(network, kinds: set[str]):
    """46286 / 46285: the constraint kinds, primary or secondary; a start constraint does not count
    once the activity is started."""
    population = activities(network, is_open_not_loe)

    def counts(activity):
        kept = constraints(activity) - (START_CONSTRAINTS if activity.is_started else set())
        return bool(kept & kinds)

    return {activity.code for activity in population if counts(activity)}, len(population)


def p6_02(network):
    """46286: Mandatory Start, Start On, Mandatory Finish, Finish On."""
    return constrained(network, P6_HARD)


def p6_03(network):
    """46285: Start or Finish On or Before / On or After, As Late As Possible."""
    return constrained(network, P6_SOFT)


def p6_04(network):
    """101248, 46282: remaining duration over x hours; milestones out."""
    population = activities(network, lambda activity: is_open_not_loe(activity) and not activity.is_milestone)
    return {activity.code for activity in population if activity.remain_hr > LIMIT_HR}, len(population)


def p6_05(network):
    """46288: lag over x hours."""
    links = p6_links(network)
    return {(link.pred, link.succ) for link in links if link.lag_hr > LIMIT_HR}, len(links)


def p6_06(network):
    """46284: total float over x hours."""
    population = activities(network, is_open_not_loe)
    return {activity.code for activity in population if activity.total_float_hr > LIMIT_HR}, len(population)


def p6_07(network):
    """46287: the non-FS links are listed."""
    links = p6_links(network)
    return {(link.pred, link.succ) for link in links if link.type != "FS"}, len(links)


def p6_08(network):
    links = p6_links(network)
    return {(link.pred, link.succ) for link in links if link.lag_hr > 0}, len(links)


def p6_09(network):
    links = p6_links(network)
    return {(link.pred, link.succ) for link in links if link.lag_hr < 0}, len(links)


def p6_10_population(network):
    """101248: WBS, LOE and activities completed before the data date removed."""

    def keep(activity):
        return not activity.is_loe and not (activity.is_complete and activity.act_end <= network.data_date)

    return activities(network, keep)


def p6_10a(network):
    """Not started with a start before the data date; in progress with a remaining early start before it."""
    population = p6_10_population(network)
    return {
        activity.code
        for activity in population
        if not activity.is_complete and activity.forecast_start < network.data_date
    }, len(population)


def p6_10b(network):
    """In progress with an actual start after the data date; completed with an actual finish after it."""
    population = p6_10_population(network)

    def is_after(activity):
        return any(
            moment is not None and moment > network.data_date for moment in (activity.act_start, activity.act_end)
        )

    return {activity.code for activity in population if is_after(activity)}, len(population)


def p6_11(network):
    """46279: no resource assignment and no expense; milestones and LOE out, completed kept."""
    population = activities(network, lambda activity: not activity.is_milestone and not activity.is_loe)
    return {activity.code for activity in population if not activity.has_assignment and not activity.has_expense}, len(
        population
    )


def p6_12(network):
    """101248 and report R1: finish later than the baseline finish; milestones, LOE, completed out."""
    population = activities(network, is_open_task)
    return {activity.code for activity in population if is_late(activity)}, len(population)


def p6_13(network):
    """Report R1: completed / every baseline activity, milestones and LOE out. (value, denominator)."""
    population = activities(network, lambda activity: not activity.is_milestone and not activity.is_loe)
    return sum(activity.is_complete for activity in population) / len(population), len(population)


def p6_14(network):
    """46283: negative total float."""
    population = activities(network, is_open_not_loe)
    return {activity.code for activity in population if activity.total_float_hr < 0}, len(population)


def p6_15(network):
    """R1: started, with an FS predecessor not complete or an SS predecessor not started; over every activity."""

    def is_out_of_sequence(activity):
        for link in network.predecessors(activity.code):
            pred = network.activities[link.pred]
            if (link.type == "FS" and not pred.is_complete) or (link.type == "SS" and not pred.is_started):
                return True
        return False

    population = list(network.activities.values())
    return {activity.code for activity in population if activity.is_started and is_out_of_sequence(activity)}, len(
        population
    )


def p6_16(network):
    """R1, 113174 with Ignore in-progress activities: not started, not milestone, predecessors but none FS or SS."""

    def is_dangling(activity):
        types = {link.type for link in network.predecessors(activity.code)}
        return not activity.is_started and not activity.is_milestone and bool(types) and not types & {"FS", "SS"}

    population = list(network.activities.values())
    return {activity.code for activity in population if is_dangling(activity)}, len(population)


def p6_17(network):
    """R1, 113174: not complete, not milestone, successors but none FS or FF."""

    def is_dangling(activity):
        types = {link.type for link in network.successors(activity.code)}
        return not activity.is_complete and not activity.is_milestone and bool(types) and not types & {"FS", "FF"}

    population = list(network.activities.values())
    return {activity.code for activity in population if is_dangling(activity)}, len(population)


def decm_204b(network):
    """06A204b: open start (milestone: no predecessor; task: no FS/SS predecessor), open finish
    (milestone: no successor; task: no FS/FF successor); incomplete, not LOE; the earliest planned
    start and the latest planned finish of the file exempt their side."""
    first_start = min(
        activity.target_start for activity in network.activities.values() if activity.target_start is not None
    )
    last_finish = max(
        activity.target_end for activity in network.activities.values() if activity.target_end is not None
    )
    population = activities(network, lambda activity: not activity.is_complete and not activity.is_loe)

    def is_open(links, activity, kinds, exempt):
        if exempt:
            return False
        types = {link.type for link in links}
        return not types if activity.is_milestone else not types & kinds

    def is_dangling(activity):
        open_start = is_open(
            network.predecessors(activity.code), activity, {"FS", "SS"}, activity.target_start == first_start
        )
        open_finish = is_open(
            network.successors(activity.code), activity, {"FS", "FF"}, activity.target_end == last_finish
        )
        return open_start or open_finish

    return {activity.code for activity in population if is_dangling(activity)}, len(population)


def decm_205a(network):
    """06A205a: incomplete activities (LOE and milestones kept) with a positive lag on a predecessor link."""
    population = activities(network, lambda activity: not activity.is_complete)
    return {
        activity.code for activity in population if any(link.lag_hr > 0 for link in network.predecessors(activity.code))
    }, len(population)


def decm_209a(network):
    """06A209a: Mandatory Start or Finish, primary or secondary; incomplete, LOE kept."""
    population = activities(network, lambda activity: not activity.is_complete)
    return {activity.code for activity in population if constraints(activity) & DECM_HARD}, len(population)


def decm_210a(network):
    """06A210a: incomplete LOE with a successor that is not LOE."""
    population = activities(network, lambda activity: activity.is_loe and not activity.is_complete)

    def drives_work(activity):
        return any(not network.activities[link.succ].is_loe for link in network.successors(activity.code))

    return {activity.code for activity in population if drives_work(activity)}, len(population)


def decm_211a(network):
    """06A211a: total float over 44 working days; incomplete, not LOE (milestones kept)."""
    population = activities(network, is_open_not_loe)
    return {
        activity.code for activity in population if activity.total_float_hr / activity.hours_per_day > LIMIT_WD
    }, len(population)


def decm_212a(network):
    """06A212a: links from an incomplete predecessor; FS: S.start < P.finish, SS: S.start < P.start,
    FF: S.finish < P.finish, SF: S.finish < P.start (actual, else forecast), lags ignored."""
    links = [link for link in network.links if not network.activities[link.pred].is_complete]

    def is_out_of_sequence(link):
        pred, succ = network.activities[link.pred], network.activities[link.succ]
        successor_end = start(succ) if link.type in ("FS", "SS") else finish(succ)
        predecessor_end = finish(pred) if link.type in ("FS", "FF") else start(pred)
        return successor_end < predecessor_end

    return {(link.pred, link.succ) for link in links if is_out_of_sequence(link)}, len(links)


def decm_501a(network):
    """06A501a: no baseline start or no baseline finish; every activity."""
    population = list(network.activities.values())
    return {
        activity.code for activity in population if activity.target_start is None or activity.target_end is None
    }, len(population)


def decm_505a(network):
    """06A505a: progress (started) without an actual start; the generator gives every started one its date."""
    population = activities(network, lambda activity: activity.is_started)
    return {activity.code for activity in population if activity.act_start is None}, len(population)


def decm_505b(network):
    """06A505b: complete without an actual finish."""
    population = activities(network, lambda activity: activity.is_complete)
    return {activity.code for activity in population if activity.act_end is None}, len(population)


def decm_506a(network):
    """06A506a: an actual start or finish after the status date / activities with an actual start."""
    population = activities(network, lambda activity: activity.act_start is not None)

    def is_after(activity):
        return any(
            moment is not None and moment > network.data_date for moment in (activity.act_start, activity.act_end)
        )

    return {activity.code for activity in population if is_after(activity)}, len(population)


def decm_506b(network):
    """06A506b (v8.0 block 6): incomplete, not started with a forecast start on or before the
    status date, or a forecast finish on or before it; LOE kept."""
    population = activities(network, lambda activity: not activity.is_complete)

    def is_invalid(activity):
        if not activity.is_started and activity.forecast_start <= network.data_date:
            return True
        return activity.forecast_finish <= network.data_date

    return {activity.code for activity in population if is_invalid(activity)}, len(population)


EXPECTED = {
    "DCMA-01": dcma_01, "DCMA-02": dcma_02, "DCMA-03": dcma_03, "DCMA-05": dcma_05, "DCMA-06": dcma_06,
    "DCMA-07": dcma_07, "DCMA-08": dcma_08, "DCMA-09": dcma_09, "DCMA-10": dcma_10, "DCMA-11": dcma_11,
    "P6-01": p6_01, "P6-02": p6_02, "P6-03": p6_03,
    "P6-04": p6_04, "P6-05": p6_05, "P6-06": p6_06, "P6-07": p6_07, "P6-08": p6_08, "P6-09": p6_09,
    "P6-10a": p6_10a, "P6-10b": p6_10b, "P6-11": p6_11, "P6-12": p6_12, "P6-14": p6_14, "P6-15": p6_15,
    "P6-16": p6_16, "P6-17": p6_17, "06A204b": decm_204b, "06A205a": decm_205a, "06A209a": decm_209a,
    "06A210a": decm_210a, "06A211a": decm_211a, "06A212a": decm_212a, "06A501a": decm_501a,
    "06A505a": decm_505a, "06A505b": decm_505b, "06A506a": decm_506a, "06A506b": decm_506b,
}  # fmt: skip
RATIOS = {"DCMA-14": dcma_14, "P6-13": p6_13}


@pytest.mark.oracle("standard")
@pytest.mark.parametrize("metric_id", EXPECTED)
def test_each_check_finds_what_the_generator_planted(network, results, shuffled_results, metric_id):
    expected_found, expected_denominator = EXPECTED[metric_id](network)
    for result in (results[metric_id], shuffled_results[metric_id]):
        assert result.status != "error", result.note
        assert result.denominator == expected_denominator
        assert sorted(found(result) - expected_found) == [], "found, not planted"
        assert sorted(expected_found - found(result)) == [], "planted, not found"


@pytest.mark.oracle("standard")
@pytest.mark.parametrize("metric_id", RATIOS)
def test_each_index_is_the_planted_ratio(network, results, shuffled_results, metric_id):
    expected_value, expected_denominator = RATIOS[metric_id](network)
    for result in (results[metric_id], shuffled_results[metric_id]):
        assert result.denominator == expected_denominator
        assert result.value == pytest.approx(expected_value, abs=1e-9)


@pytest.mark.oracle("standard")
def test_dcma_04_is_the_planted_share_of_finish_to_start_links(network, results, shuffled_results):
    """PAM 200.1 §4.4: FS links / links into incomplete tasks (§4.0)."""
    links = dcma_links(network)
    share = 100 * sum(link.type == "FS" for link in links) / len(links)
    for result in (results["DCMA-04"], shuffled_results["DCMA-04"]):
        assert result.denominator == len(links)
        assert result.value == pytest.approx(share, abs=1e-9)


@pytest.mark.oracle("standard")
def test_the_network_plants_every_kind_of_finding(network):
    """A planted answer of 0 would prove little: every check covered finds something here, except
    the two DECM progress checks the generator cannot plant without breaking the progress the
    schedulers read (06A505a, 06A505b: their denominators are still asserted)."""
    empty = [metric_id for metric_id, expected in EXPECTED.items() if not expected(network)[0]]
    assert empty == ["06A505a", "06A505b"]


# --- the CPM against MPXJ ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def xc():
    mpxj_or_skip()
    from xerscope import crosscheck

    if "mpxj-cpm-" not in crosscheck.mpxj_scheduler_source():
        loaded = crosscheck.mpxj_scheduler_source()
        missing("mpxj", f"scheduler not built ({loaded} loaded): uv run python tests/reference/mpxj_cpm.py")
    return crosscheck


def reached(network: Network, codes: set[str], step) -> set[str]:
    """``codes`` and every activity reached from them through ``step`` (successors or predecessors)."""
    seen, waiting = set(codes), list(codes)
    while waiting:
        for code in step(waiting.pop()):
            if code not in seen:
                seen.add(code)
                waiting.append(code)
    return seen


def after_mpxj_inconsistency(network: Network, differences: pd.DataFrame, inconsistent: set[str]) -> pd.Series:
    """Differences that follow from an MPXJ date contradicting its own logic: an early date downstream
    of one, a late date upstream, a float on either side, a free float before an early date moved."""
    downstream = reached(network, inconsistent, lambda code: [link.succ for link in network.successors(code)])
    upstream = reached(network, inconsistent, lambda code: [link.pred for link in network.predecessors(code)])
    before_downstream = {
        code for code in network.activities if any(link.succ in downstream for link in network.successors(code))
    }
    code, field = differences["task_code"], differences["field"]
    return (
        (field.isin(["es", "ef"]) & code.isin(downstream))
        | (field.isin(["ls", "lf"]) & code.isin(upstream))
        | (field.isin(["tf_hr", "ff_hr"]) & code.isin(upstream | downstream))
        | ((field == "ff_hr") & code.isin(before_downstream))
    )


@pytest.mark.oracle("mpxj")
def test_cpm_agrees_with_mpxj_activity_by_activity(xc, network, tmp_path):
    """Every date and float of every open activity equal to MPXJ's, to the working minute, but those
    an MPXJ self-contradiction accounts for. Measured: 11,987 values, 349 differ, every one after one
    of 23 MPXJ inconsistencies; the share identical (97.1 %) guards against a new bug hiding there."""
    path = network.for_mpxj().write(tmp_path / "scale-mpxj.xer")
    snapshot = load_snapshot(path)
    assert xc.mpxj_unsupported(snapshot) == []
    assert xc.unresolved_patterns(snapshot) == set()
    assert xc.settled_patterns(snapshot) == set()
    comparison = xc.cpm_crosscheck(path)
    compared = comparison[comparison["comparable"]]
    assert len(compared) > 11_000
    differences = compared[~compared["xs_mpxj_work"]]
    named = [
        xc.excused_row(snapshot, code, field) is not None
        for code, field in zip(differences["task_code"], differences["field"], strict=True)
    ]
    differences = differences[~pd.Series(named, index=differences.index, dtype=bool)]
    inconsistent = xc.mpxj_inconsistent(snapshot, comparison)
    unexplained = differences[~after_mpxj_inconsistency(network, differences, inconsistent)]
    assert unexplained.empty, unexplained[["task_code", "field", "xerscope", "mpxj"]].head(20).to_string()
    assert len(inconsistent) <= 30
    assert compared["xs_mpxj_work"].mean() >= 0.97
