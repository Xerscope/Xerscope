"""Plain-language account of how a check result was computed.

The app shows it next to every check so a reviewer can redo the arithmetic and see
which activities were counted:

    e = explain(result)
    e.formula     # "18 late / 19 checked = 94.7 %"
    e.verdict     # "94.7 % misses the target ≤ 5 %"
    e.population  # ["Excludes: completed activities, milestones, level of effort", ...]
    e.parameters  # [("exclude", "complete, milestones, loe", "standard"), ...]

Nothing here recomputes a result: it only reads the CheckResult and the metric's
parameters, so the explanation can never disagree with the number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..xer import Snapshot
from ..xer.model import CONSTRAINT
from .checks import CheckResult, fmt_value
from .populations import EXCLUSIONS
from .rules import EXEMPT, RULES, Rule

LINKS_TEXT = {
    "all": "all relationships",
    "not_both_complete": "relationships where predecessor and successor are not both complete",
    "succ_incomplete": "relationships into an incomplete successor",
}
# what ``op`` / ``value`` compare, per rule (default "value")
MEASURE_TEXT = {"lag": "lag", "float": "total float", "duration": "{field} duration"}
OP_TEXT = {"<=": "≤", ">=": "≥", "==": "=", "<": "<", ">": ">"}


@dataclass
class Explanation:
    measured: str
    formula: str
    verdict: str
    method: str
    population: list[str] = field(default_factory=list)
    parameters: list[tuple[str, str, str]] = field(default_factory=list)  # (name, value, origin)
    flagged_label: str = "Flagged items"
    subject: str = "activities"
    baseline: str = ""  # the baseline the result was computed on, when the check depends on one


def noun(subject: str, n: int) -> str:
    """'activities' / 'relationships', singular when n == 1."""
    return subject if n != 1 else {"activities": "activity", "relationships": "relationship"}.get(subject, subject)


def _target(metric) -> str:
    if metric.comparator is None or metric.threshold is None:
        return ""
    if metric.unit == "pass/fail":
        return "pass"
    return f"{OP_TEXT[metric.comparator]} {metric.threshold:g}{' %' if metric.unit == '%' else ''}"


def _show(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(map(str, value)) if value else "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _exclude_line(links: bool, exclude: list[str]) -> str:
    excluded_text = ", ".join(EXCLUSIONS[key].text for key in exclude)
    return f"Relationships whose successor is excluded: {excluded_text}." if links else f"Excludes: {excluded_text}."


def _scope_lines(rule: Rule, params: dict) -> list[str]:
    out = []
    if params.get("exclude"):
        out.append(_exclude_line(rule.links, params["exclude"]))
    if params.get("pred_exempt"):
        exempt = ", ".join(EXEMPT.get(key, key) for key in params["pred_exempt"])
        out.append(f"No predecessor required for: {exempt}.")
    if params.get("succ_exempt"):
        exempt = ", ".join(EXEMPT.get(key, key) for key in params["succ_exempt"])
        out.append(f"No successor required for: {exempt}.")
    if "links" in params:
        out.append("Relationships counted: " + LINKS_TEXT.get(params["links"], params["links"]) + ".")
    if params.get("exclude_loe"):
        out.append("Relationships to or from level-of-effort tasks are left out.")
    if params.get("types"):
        out.append("Constraint types: " + ", ".join(CONSTRAINT.get(code, code) for code in params["types"]) + ".")
    return out


def _flag_line(rule: Rule, params: dict) -> list[str]:
    """'Flagged when <what> <op> <value> <unit>.' for the rules that compare a value."""
    if "op" not in params or "value" not in params:
        return []
    what = MEASURE_TEXT.get(rule.name, "value").format(**params)
    unit = params.get("unit", "")
    if params["op"] == "between":
        band = f"Flagged when {what} is from {params['value']:g} to {params['value_max']:g} {unit}".rstrip()
        return [band + " (both included)."]
    comparison = OP_TEXT.get(params["op"], params["op"])
    if unit == "project_pct":
        return [f"Flagged when {what} {comparison} {params['value']:g} % of the project's working hours."]
    return [f"Flagged when {what} {comparison} {params['value']:g} {unit}".rstrip() + "."]


def _no_resource_notes(params: dict) -> list[str]:
    if params.get("kind") == "labour_units":
        return ["Loaded means budgeted labour units above zero, not any assignment."]
    return []


def _relationship_type_notes(params: dict) -> list[str]:
    counted = f"relationships of type {params.get('type', 'FS')}"
    if params.get("zero_lag"):
        counted += " with a zero lag"
    shown = "those counted" if params.get("listed") == "of_type" else "the others"
    return [f"Counts {counted}; the list shows {shown}."]


def _invalid_dates_notes(params: dict) -> list[str]:
    if params.get("in_progress") == "start":
        return ["An in-progress task is flagged when its remaining early start is before the status date."]
    return []


def _late_vs_baseline_notes(params: dict) -> list[str]:
    notes = ["Variance is working time on the task's calendar, as P6's Finish Variance: negative = late."]
    if params.get("no_baseline") == "planned":
        notes.append("A task with no baseline finish is late when its finish is later than its planned finish.")
    return notes


def _bei_notes(params: dict) -> list[str]:
    if params.get("due_from") == "baseline":
        due_text = (
            "Due = baseline tasks finishing on or before the status date, counted in the "
            "baseline: a task added since is never due, one deleted since still is."
        )
    else:
        missing = "counted as due" if params.get("missing_baseline", "due") == "due" else "left out"
        due_text = f"Tasks without a baseline finish are {missing}."
    return [due_text + " Completed = all completed tasks in the population, early ones included."]


def _limit_note(measure: str, key: str, unit: str) -> Callable[[dict], list[str]]:
    """'Flagged when <measure> > <limit> <unit>.' for the built-in checks with an x threshold."""
    return lambda params: [f"Flagged when {measure} > {params[key]:g} {unit}."]


def _slip_notes(params: dict) -> list[str]:
    return [f"The first open critical task is delayed by {params['slip_days']:g} working days."]


def _status_period_notes(params: dict) -> list[str]:
    return [f"Compared with the latest update at least {params['status_period_days']:g} days older."]


def _riding_notes(params: dict) -> list[str]:
    return [
        *_status_period_notes(params),
        f"Rides when the start is within {params['riding_window_wd']:g} working days of the status date"
        f" in both updates, or the remaining duration moved by at most"
        f" {params['remaining_tolerance_wd']:g} working days.",
    ]


def _date_grain_notes(params: dict) -> list[str]:
    grain = params.get("date_grain", "timestamp")
    if grain == "day":
        how = "by calendar day, as DCMA-EA PAM 200.1 reads them"
    else:
        how = "as stored, time included (P6's reading)"
    return [f"Dates are compared with the status date {how}."]


# rule name -> sentences that depend on the rule's parameters
NOTES: dict[str, Callable[[dict], list[str]]] = {
    "dcma_09_invalid_dates": _date_grain_notes,
    "dcma_11_missed_tasks": _date_grain_notes,
    "dcma_14_bei": _date_grain_notes,
    "p6_04_large_durations": _limit_note("remaining duration", "limit_hours", "hours"),
    "p6_05_long_lags": _limit_note("lag", "limit_hours", "hours"),
    "p6_06_large_float": _limit_note("total float", "limit_hours", "hours"),
    "dcma_06_high_float": _limit_note("total float", "limit_days", "days"),
    "dcma_08_high_duration": _limit_note("baseline duration", "limit_days", "days"),
    "decm_06a211a_high_float": _limit_note("total float", "limit_days", "days"),
    "dcma_12_critical_path_test": _slip_notes,
    "decm_06a401a_critical_path_test": _slip_notes,
    "decm_06a504a_actual_starts_changed": _status_period_notes,
    "decm_06a504b_actual_finishes_changed": _status_period_notes,
    "decm_06a506c_riding_status_date": _riding_notes,
    "relationship_type": _relationship_type_notes,
    "no_resource": _no_resource_notes,
    "on_data_date": _date_grain_notes,
    "invalid_dates": _invalid_dates_notes,
    "late_vs_baseline": _late_vs_baseline_notes,
    "bei": _bei_notes,
}


def _parameter_lines(rule: Rule, params: dict) -> list[str]:
    """The sentences written from the parameters: what is left out, what is flagged, the rule's notes."""
    notes = NOTES.get(rule.name)
    return [*_scope_lines(rule, params), *_flag_line(rule, params), *(notes(params) if notes else [])]


def _population(rule: Rule, params: dict) -> list[str]:
    """The docstring's population lines, then the sentences written from the parameters."""
    return [*rule.population, *_parameter_lines(rule, params)]


def _counting_words(rule: Rule, links: bool) -> tuple[str, str]:
    """The words of the numerator and of the denominator; relationships are named when checked."""
    checked = "relationships checked" if links and rule.denominator_word == "checked" else rule.denominator_word
    return rule.numerator_word, checked


def _target_line(metric) -> str:
    """What passes, in the words of the formula ('Passes when flagged / checked is < 5 %.')."""
    counted, checked = _counting_words(RULES[metric.rule], RULES[metric.rule].links)
    if not _target(metric):
        return "No target: the result is reported for review."
    if metric.unit == "pass/fail":
        return "Passes when the test passes."
    result = f"the number {counted}" if metric.unit == "count" else f"{counted} / {checked}"
    return f"Passes when {result} is {_target(metric)}."


def settings_lines(metric) -> list[str]:
    """What the settings of a metric ask, before any result: the sentences written from its
    parameters, then the result that passes."""
    rule = RULES[metric.rule]
    return [*_parameter_lines(rule, {**rule.params, **metric.params}), _target_line(metric)]


def _formula(result: CheckResult, subject: str, words: tuple[str, str]) -> str:
    metric = result.metric
    num_word, den_word = words
    numerator, denominator, value = result.numerator, result.denominator, result.value
    if result.status in ("n/a", "error"):
        return result.note or "not computed"
    if metric.unit == "%" and numerator is not None and denominator:
        return f"{numerator} {num_word} / {denominator} {den_word} = {fmt_value(value, '%')}"
    if metric.unit == "ratio" and numerator is not None and denominator:
        return f"{numerator} {num_word} / {denominator} {den_word} = {fmt_value(value, 'ratio')}"
    if metric.unit == "count":
        found = numerator if numerator is not None else 0
        return f"{found} {noun(subject, found)} {num_word}"
    return result.note or fmt_value(value, metric.unit)


def _verdict(result: CheckResult) -> str:
    metric = result.metric
    target = _target(metric)
    shown = fmt_value(result.value, metric.unit)
    if metric.unit == "pass/fail" and result.status in ("pass", "fail"):
        return "Passed." if result.status == "pass" else "Failed."
    if result.status == "pass":
        return f"{shown} meets the target {target}."
    if result.status == "fail":
        return f"{shown} misses the target {target}."
    if result.status == "info":
        return "Reported for review: " + (result.note or "this standard sets no pass/fail target") + "."
    if result.status == "n/a":
        return "Not applicable: " + (result.note or "nothing to check") + "."
    return "The rule raised an error: " + result.note


def explain(result: CheckResult) -> Explanation:
    metric = result.metric
    rule = RULES[metric.rule]
    effective = {**rule.params, **metric.params}
    parameters = [
        (name, _show(value), "standard" if name in metric.params else "default") for name, value in effective.items()
    ]
    links = rule.links or "pred_code" in result.flagged.columns
    subject = "relationships" if links else "activities"
    num_word, den_word = _counting_words(rule, links)

    return Explanation(
        measured=metric.description,
        formula=_formula(result, subject, (num_word, den_word)),
        verdict=_verdict(result),
        method=rule.doc,
        population=_population(rule, effective),
        parameters=parameters,
        flagged_label=rule.title or "Flagged items",
        subject=subject,
        baseline=result.baseline,
    )


def critical_definition(snapshot: Snapshot, default_days: float) -> str:
    """What ``is_critical`` counts in this update (xer/model.py): the project's critical path
    type (PROJECT.critical_path_type), longest path or total float <= threshold
    (PROJECT.critical_drtn_hr_cnt, else ``default_days``, the Settings the file was read with)."""
    options = snapshot.options
    if options.get("critical_path_type") == "CT_DrivPath":
        rule = "on the longest path (P6 Longest Path flag)"
    elif options.get("critical_float_hr") is not None:
        rule = f"total float ≤ {options['critical_float_hr']:g} h"
    else:
        rule = f"total float ≤ {default_days:g} d"
    return f"Open tasks (LOE and milestones included) {rule}"


# Page figures (ui.kpis ``formulas``): label -> standard -> how it is computed. The page's own
# calculation (docs/formulas.md) first, under the name of the standard it follows; a second line
# where another standard words the same figure otherwise. Sources are in docs/formulas.md.
P6 = "P6 Professional"
EVMS = "DCMA EVMS (EIA-748)"
LPS = "Last Planner (PPC)"
LIPKE = "Earned Schedule (Lipke)"
XS = "xerscope"
AACE = "AACE RP 29R-03 MIP 3.4"


# The help of the "SPI (4 weeks)" figure: what it says, how it is calculated, why this way, and the
# settings of the Baseline window it is meant for (their labels are those of app/state.py).
SPI_WINDOW_READING = (
    "**What it says.** Hours earned / hours planned over the last four weeks: 0.80 means 80 % of what the "
    "plan asked for was earned. It describes the month that ended; it does not forecast the next one.\n\n"
    "**How it is calculated.**\n"
    "1. The window runs from the last update dated at least 28 days before this one, to this one; the line "
    "under these figures gives its start.\n"
    "2. Each week, from one update to the next, is read on the baseline of the update that opens it: the "
    "hours earned in the week (ΔEV) and the hours the plan asked for in the week (ΔPV).\n"
    "3. SPI = Σ ΔEV / Σ ΔPV over these weeks.\n\n"
    "**Why each week on its own baseline.** A baseline made again takes in the delay to date: read on it "
    "alone, the weeks before it look better than they were on the plan of the time; read on an old "
    "baseline, the work planned again since is missed. Week by week, each one is judged on the plan in "
    "force when it started, and a new baseline adds no jump.\n\n"
    "**Why a ratio of sums, not the mean of the weekly SPI.** A week weighs what the plan asked of it. "
    "Weeks planned 500, 500, 500 and 20 h and earned 400, 400, 400 and 60 h have SPI of 0.80, 0.80, 0.80 "
    "and 3.00, mean 1.35; yet 1,260 h were earned for 1,520 planned: 0.83.\n\n"
    "**Why the last weeks do not weigh more.** Weighing the recent weeks more (weights 1-2-3-4, or an "
    "exponential smoothing) is a known way to make such a figure react faster. It is not done here, for "
    "three reasons. One week's figure follows the way progress was reported that week more than the pace "
    "of the work: a week at 0.30 and a week at 1.40 can follow each other, and one says little about the "
    "next. The last week is the least sure of the four: progress reported late lands in a later update. "
    "And over four weeks, a heavier last week comes close to reading that week alone. Weeks planned 400 h "
    "each and earned 120, 260, 228 and 560 h give 0.73 here and 0.89 with the weights 1-2-3-4; one more "
    "week, at 168 h, gives 0.76 here and 0.77 with the weights: the figure moves by 0.03 here, by 0.12 "
    "with the weights, for the same work.\n\n"
    "**Settings it is meant for** (sidebar, Baseline).\n"
    "- Baseline (BL): *Baseline in each file (P6 Project Baseline)*, so that each update is measured against "
    "the baseline its file names. With one baseline for every update, all the weeks are read on it: the "
    "figure then says how the month went against that plan only.\n"
    "- Earned value basis: the one set in P6, *Budgeted · planned dates* unless it was changed there. The "
    "current-dates bases move the planned value with the schedule, and a delay partly disappears.\n"
    "- When a file has no baseline: *None*. A week without a baseline then leaves the figure empty; with "
    "the planned dates as fallback it is read on the update's own dates, where a late start does not show.\n"
    "- Link renumbered tasks by GUID: on. A task renumbered during a week otherwise leaves the count with "
    "its hours.\n"
    "- Every update loaded: a missing one makes a week longer and hides what happened in it.\n\n"
    "**Empty.** No update dated at least 28 days before this one, a week without a baseline, or no hours "
    "planned over the window."
)


KPI_FORMULAS: dict[str, dict[str, str]] = {
    "Finish before replanning": {
        AACE: "Finish of the half-step schedule: the previous update with this update's progress data "
        "(actual start, actual finish, percent complete, decreased remaining duration), recalculated at this "
        "update's status date (3.4.K.4.b, c); its shift is the slip due to progress (3.4.K.4.d)"
    },
    "Finish shown": {
        AACE: "Recalculated finish of this update; its shift from the half-step schedule is the slip or gain due "
        "to the non-progress revisions (3.4.K.4.e)"
    },
    "Longest path float": {
        XS: "Lowest total float on the recalculated longest path / hours per day of the project calendar"
    },
    "Tasks matched": {XS: "Tasks of both updates, by Task ID; added and deleted ones enter at the scope step"},
    "Forecast finish": {P6: "Latest Finish of the project's activities (actual, else remaining, else early finish)"},
    "Shift since first update": {
        XS: "working_days(forecast finish in the first update, forecast finish now), project calendar"
    },
    "Tasks complete": {P6: "Activities with status Complete / activities (WBS summaries left out)"},
    "Critical tasks": {
        P6: "Open activities critical as the project's critical path type says (float ≤ threshold, or driving path)"
    },
    "% complete": {
        XS: "Σ (% complete × weight) / Σ weight over the node's activities; weight = budgeted hours, else duration"
    },
    "Labor hours": {P6: "Actual Labor Units / Budgeted Labor Units of the node's activities"},
    "Open critical": {P6: "Open critical activities under the node"},
    "Percent complete": {P6: "Earned Value Labor Units / Budget At Completion", EVMS: "BCWP / BAC"},
    "Percent scheduled": {P6: "Planned Value Labor Units / Budget At Completion", EVMS: "BCWS / BAC"},
    "SPI (labor units)": {P6: "Earned Value Labor Units / Planned Value Labor Units", EVMS: "SPI = BCWP / BCWS"},
    "SPI": {P6: "Earned Value Cost / Planned Value Cost", EVMS: "SPI = BCWP / BCWS (cost)"},
    "SV": {P6: "Earned Value − Planned Value (labor units)", EVMS: "SV = BCWP − BCWS"},
    "BEI (P6 / DCMA)": {
        P6: "Complete activities / activities with a baseline, milestones and LOE out (P6-13)",
        "DCMA 14-Point": "Complete activities / activities with BL finish ≤ status date, no BL finish = due (DCMA-14)",
    },
    "EAC": {P6: "Actual Labor Units + Remaining Labor Units", EVMS: "EAC = ACWP + ETC; VAC = BAC − EAC"},
    "Plan reached": {
        LIPKE: "ES: the date t of the baseline at which PV(t) = EV (Schedule is Different, 2003)",
        XS: "the status date while the plan asks for no hours",
    },
    "Time gap": {LIPKE: "SV(t) = ES − AT, shown in calendar days: plan reached − status date"},
    "SPI(t)": {LIPKE: "SPI(t) = ES / AT, both from the plan's start, in the tasks' working time"},
    "SPI (4 weeks)": {
        XS: "Σ ΔEV / Σ ΔPV over the weeks since the last update dated 28 days before or more, each week read "
        "on the baseline of the update that opens it: the weekly SPI weighted by the planned hours"
    },
    "Planned finish": {LIPKE: "Plan start + PD: the last planned finish of the baseline tasks measured"},
    "Forecast finish (4 weeks)": {
        LIPKE: "IEAC(t) long form, AT + (PD − ES) / PF(t), from the plan's start",
        XS: "PF(t) = Σ ΔES / Σ ΔAT over the weeks of the same window",
    },
    "Forecast finish (all updates)": {
        LIPKE: "IEAC(t) long form, AT + (PD − ES) / PF(t), from the plan's start",
        XS: "PF(t) = Σ ΔES / Σ ΔAT over every week read since the first update loaded",
    },
    "TSPI (planned finish)": {LIPKE: "TSPI = (PD − ES) / (TD − AT), the total duration wanted TD = PD"},
    "PPC Start": {
        XS: "Starts kept / starts committed: not started at W−1 with a W−1 start on or before W's status date; "
        "kept = actual start in W on or before that date (milestones and LOE left out)"
    },
    "PPC Finish": {
        LPS: "Finishes kept / finishes committed: not complete at W−1 with a W−1 finish on or before W's status "
        "date; kept = actual finish in W on or before that date (milestones and LOE left out)"
    },
    "PPC W/W−1": {XS: "(starts + finishes kept) / (starts + finishes committed)"},
}
