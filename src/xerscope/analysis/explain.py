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
    "Pace (4 weeks)": {XS: "PF(t) = Σ ΔES / Σ ΔAT over the weeks of the SPI (4 weeks) window"},
    "Pace (all updates)": {XS: "PF(t) = Σ ΔES / Σ ΔAT over every week read since the first update loaded"},
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
for _ahead in (1, 2, 4, 8):  # the lookahead horizons of the PPC page, one KPI label each
    KPI_FORMULAS[f"TA ({_ahead} ahead)"] = {
        LPS: f"Tasks Anticipated = commitments of the weekly work plan that the plan {_ahead} update(s) before "
        "held for the same week / commitments of the weekly work plan (Hamzeh, Ballard & Tommelein 2012, fig. 5)"
    }
    KPI_FORMULAS[f"TMR ({_ahead} ahead)"] = {
        LPS: f"Tasks Made Ready = commitments the plan {_ahead} update(s) before held for the week that were kept "
        f"in W / commitments that plan held for the week (TMR({_ahead}, 0), Hamzeh, Ballard & Tommelein 2012)"
    }


@dataclass(frozen=True)
class Reading:
    """Hold the text of a "How to read" popover: how a chart or table is drawn, what it means, what to conclude.

    ``source`` names a standard or a document, never a web address (docs/standards.md, Sources, holds them).
    A table's text is one paragraph, kept in ``how``."""

    how: str
    meaning: str = ""
    conclude: str = ""
    source: str = ""


# Figures by the key their builder sets (viz/charts.py ``reading``), tables by the key a page passes
# to ``ui.table``.

# Which baseline a page's figures are computed against, and why (the baseline each page reads).
CHECKS_BASELINE = (
    "Against the baseline assigned in this update, as P6 Check Schedule and the DCMA 14-Point Assessment define "
    "their items; the window's choice when the file holds none."
)
ORIGIN_BASELINE = (
    "PV, EV, SPI and the Earned Schedule are computed against the origin baseline of the series: a cumulative "
    "index needs a baseline that does not move (Lipke 2009: the Earned Schedule reliability studies exclude "
    "re-planned projects); switch to the P6 view to read the file's own Planned Value."
)

FUNNEL_READING = Reading(
    how=(
        "start, then one row per population step: its label, the text it follows, rows removed, rows left; last row "
        "= counted. The denominator is the last step's left."
    ),
    source=(
        "`populations.STEP_SOURCES` (docs/formulas.md:127-128: Oracle P6 help 101248 and 46282, R1, Ten Six, PAM "
        "200.1, DECM 8.0, xerscope)"
    ),
)

PPC_COMMITMENTS_READING = Reading(
    how=(
        "Per commitment: kind, kept, forecast at W−1, actual, forecast now, status now, in update. Milestones are "
        "shown but out of the PPC counts."
    ),
    source="Last Planner System (PPC); docs/formulas.md §4",
)

TASK_TABLES_READING = Reading(
    how=(
        "TASKRSRC rows (units budgeted / actual / remaining); predecessors then successors with type and lag; one "
        "row per update with status, dates, float, durations, % complete, critical."
    ),
    source="P6 Activity Details (Resources, Relationships)",
)

EXPORT_TABLES_READING = Reading(
    how="table, rows, columns of the star schema; the first 200 rows of fact_activity.",
    source="`export.export_tables`",
)


READINGS: dict[str, Reading] = {
    "scurve": Reading(
        how=(
            "x = calendar dates, y = labour hours or % of BAC (toggle). PV (baseline) is a line through every day "
            "of the plan; EV and AC are one point per update (circles, squares); the dashed line continues AC with "
            "the remaining hours to the EAC label; the BAC label ends the PV curve. A dashed vertical line marks "
            "the status date (`_mark_data_date`, `charts.py:70-83`); at it a vertical mark joins PV and EV, "
            "labelled SV, green when EV ≥ PV, red when behind (`charts.py:210-240`)."
        ),
        meaning=(
            "EV under PV at the status date is work planned and not earned; AC above EV is hours spent for less "
            "work; the forecast end above BAC is an overrun in hours."
        ),
        conclude=f"SV < 0 is behind plan in hours; the gap EV–PV read along x is the time behind. {ORIGIN_BASELINE}",
        source=(
            "Oracle P6 glossary definitions quoted in docs/formulas.md §3 (PV, EV, BAC, SPI); EVMS EIA-748 / PMI "
            "Practice Standard for EVM for the names (explain.py `EVMS`)."
        ),
    ),
    "index_trend": Reading(
        how=(
            "x = status dates, y = a ratio; one line per index (SPI labour units, SPI 4 weeks, BEI DCMA, EV / AC, "
            "and SPI cost when costs are on); a grey line at 1.0, a red dotted line at 0.95 labelled; end labels "
            "give the last value (three decimals for SPI, `charts.py:248`)."
        ),
        meaning=(
            "1.0 = on plan; SPI < 1 = less earned than planned to date; SPI (4 weeks) = the last month alone "
            f"(`SPI_WINDOW_READING`, `explain.py:296`); BEI = tasks completed / tasks due. {ORIGIN_BASELINE} "
            "The BEI, a check, is computed against the baseline assigned in each update."
        ),
        conclude=(
            "BEI < 0.95 is flagged by DCMA 14-Point (PAM 200.1 §3.1.2.4, `dcma.toml:141`) and by P6 Check Schedule "
            "(> 0.95, `p6.toml:164`); for SPI and EV / AC the 0.95 line is xerscope's alert (`charts.py:39`), no "
            "standard in the repository fixes it."
        ),
        source=(
            "DCMA 14-Point Assessment, item 14 (BEI); P6 Professional Check Schedule report (BEI); EVMS EIA-748 for "
            "SPI; docs/formulas.md §3."
        ),
    ),
    "mta": Reading(
        how=(
            "x = reporting (status) date, y = forecast date of the milestone, both axes on the same scale so the "
            "line forecast = status date is the 45° diagonal; below it is the past (shaded). One line per milestone "
            "in its tag colour; a diamond where the update reports it complete, where the line meets the diagonal. "
            "The last point is bigger and red when the date moved later in the last update, green when earlier; the "
            "end label gives the code and the move in wd (`_mta_end_label`, `charts.py:377-387`)."
        ),
        meaning=(
            "a horizontal line is a stable forecast; a rising line is a milestone slipping week after week; a line "
            "climbing parallel to the diagonal is a milestone that moves as fast as time passes."
        ),
        conclude=(
            "red up-arrows on several milestones in the same update mean the week's replanning moved the end dates; "
            "read the Slippage table for the wd on each milestone's calendar."
        ),
        source=(
            "docs/formulas.md §4 (MTA: `milestone_trend`, `milestone_slips`, `plotted_trend`); no external standard "
            "is named in the repository for the MTA."
        ),
    ),
    "activity_dates": Reading(
        how="x = status date, y = the task's forecast start and finish, one line each.",
        meaning=(
            "a finish rising from update to update is the task slipping; a flat start with a rising finish is a "
            "duration growing."
        ),
        conclude=(
            "compare with the Total float chart beside it: a slip with float falling to 0 puts the task on the "
            "critical path."
        ),
        source="xerscope (`store.history`); P6 fields Start / Finish as docs/architecture.md defines them.",
    ),
    "activity_float": Reading(
        how=(
            "x = status date, y = total float in working days of the task's calendar; a red dotted line at 0 "
            'labelled "critical". The hover of each point lists that update\'s predecessors and successors: link '
            "type, driving (recalculated by the CPM: the XER does not export P6's Driving flag), total float and "
            "constraints. A neighbour picked in Show on the chart is drawn too, dotted (predecessor) or dashed "
            "(successor), in the updates whose relationships link it; a faded point: its link does not drive "
            "there; a diamond: the activity carries a constraint."
        ),
        meaning=(
            "float is the delay the task can take without moving the project finish (or its Must Finish By); "
            "negative float = the project is already late against that date. A predecessor whose float falls "
            "with the task's is likely what pushes it."
        ),
        conclude=(
            "≤ 0 d is critical (`config.py:12`; P6 Define critical activities, read by "
            "`explain.critical_definition`); > 44 wd is high float for DCMA 14-Point, item 6 (`dcma.toml:70`), and "
            "P6 Check Schedule Large Float (`p6.toml:86`)."
        ),
        source=(
            "DCMA 14-Point Assessment, items 6 and 7; P6 Professional Check Schedule report (Large Float, Negative "
            "Float); P6 TASKPRED of each update."
        ),
    ),
    "finish_trend": Reading(
        how=(
            "x = status date, y = the project's forecast finish, one point per weekly XER; the hover gives the file "
            "and the shift in wd against the previous update."
        ),
        meaning=(
            "a rising line is the end date slipping; the shift is working days on the newer update's project "
            "calendar, later = negative (`store.py:231-236`)."
        ),
        conclude=(
            'a finish that holds while the half-step "finish before replanning" slips (Delay analysis) is a delay '
            "absorbed by replanning."
        ),
        source="xerscope (`SnapshotStore.summary`, docs/formulas.md §4 Finish shift); P6 Latest Early Finish.",
    ),
    "ppc": Reading(
        how=(
            "x = week ending (status date, categorical), y = % 0–105; three lines: PPC Finish (Last Planner's PPC), "
            "PPC Start, PPC W/W−1 (both kinds together); a red dotted line at the target with its label in the "
            "right margin; an open marker = a week with a note (more than a week since the previous update, or Task "
            "IDs changed); a gap = a week with nothing committed."
        ),
        meaning=(
            "the share of what W−1 promised to start or finish by W's status date that W reports done "
            "(docs/formulas.md:368-378); milestones and LOE are left out."
        ),
        conclude=(
            "under the target line, commitments are not kept; the Commitments table names which. 80 % is xerscope's "
            "default target (`charts.py:40`); the repository names no PPC threshold from the Last Planner System."
        ),
        source="Last Planner System (PPC); docs/formulas.md §4.",
    ),
    "metric_trend": Reading(
        how=(
            "x = status date, y = the check's value in its unit (%, count, ratio); the hover gives found / checked; "
            "a red dotted line at the target when the check has one (none for pass/fail)."
        ),
        meaning=f"the same check, same standard, on every loaded update. {CHECKS_BASELINE}",
        conclude=(
            "on the wrong side of the target line the check fails that week; the target and its direction are the "
            "TOML's (`standards/*.toml` `target`)."
        ),
        source=(
            "the check's own `source` field (P6 Professional Check Schedule help page ids; DCMA-EA PAM 200.1 §; "
            "DECM v8.0 metric ID; Oracle P6 EPPM 26 help, Schedule Project Log), shown by `show_method`."
        ),
    ),
    "half_step": Reading(
        how=(
            "x = the steps of the half-step reading in order (scope, dates, logic, durations, constraints, "
            "calendars, options…), y = working days the project finish moved when that kind of change was applied "
            "to the earlier update; red bars = lost, green = gained; the hover gives the finish once applied and "
            "the number of changes."
        ),
        meaning=(
            "the earlier update is rescheduled with this update's changes one kind at a time "
            "(analysis/forensics.py); each bar is what that kind did to the finish."
        ),
        conclude=(
            "a progress bar deeper than the period (warning `forensics.py:124-129`) points to a revision hidden in "
            "the half-step or to a non-working stretch; a residual (`130-134`) means a change the changelog does "
            "not list moved the finish."
        ),
        source="AACE RP 29R-03 MIP 3.4 (observational, dynamic, contemporaneous, half-step; docs/formulas.md §5.1).",
    ),
    "slip_trend": Reading(
        how=(
            'x = status date, y = date; two lines: "Finish shown" (the recalculated finish of each update) and '
            "\"Finish before replanning\" (where the previous update's plan lands with this update's progress alone)."
        ),
        meaning="the gap between them, week after week, is the delay the replanning absorbs.",
        conclude=(
            'a flat "Finish shown" over a rising "Finish before replanning" is a schedule being re-planned to hold '
            "its date; read the series table for the wd of slip and replanning."
        ),
        source="AACE RP 29R-03 MIP 3.4; docs/formulas.md §5.1.",
    ),
    "gantt": Reading(
        how=(
            "a tree grid on the left (Activity / WBS, % complete, float) and the timeline on the right, one row "
            "each, in P6 Activities-view order (WBS node, its activities, its child nodes). Bar colour = float "
            "category: Critical (red, P6 critical), Near critical (amber, total float ≤ 10 wd), Normal (blue), "
            "Complete (grey) (`PALETTE`, `gantt.py:29-35`; `categorise` 43-50). Diamonds = milestones; a dark thin "
            "bar = WBS summary; a hollow outline behind a bar = the same activity in the comparison update or "
            'baseline (legend item with the comparison label); a dashed vertical line = data date. Hover: "Finish '
            'vs <comparison>" in wd, or "Finish vs BL (baselined tasks)".'
        ),
        meaning=(
            "slippage reads as the bar leaving its outline; red bars are the path that sets the finish; amber bars "
            f"are within 10 wd of it. The baseline outline and the variance to BL: {CHECKS_BASELINE}"
        ),
        conclude=(
            "red bars not started before the data date line are the week's risk; the Float filter and the Ask field "
            "isolate them. Thresholds: critical = total float ≤ 0 d or the project's critical path type (P6 Define "
            "critical activities); near critical = 10 wd (xerscope setting, no standard)."
        ),
        source=(
            "Oracle P6 Professional Activities view and Define critical activities (via "
            "`explain.critical_definition`); xerscope `config.Settings`."
        ),
    ),
    "overview_updates": Reading(
        how=(
            "One row per weekly XER: status date, file, forecast finish, finish shift (wd, later = negative), "
            "counts of tasks by status, critical, relationships, % complete by count. A finish shift < 0 week after "
            "week is a slipping project."
        ),
        source="xerscope `store.summary` (`store.py:209-238`)",
    ),
    "health_results": Reading(
        how=(
            "One row per check in the standard's order: status (pass red/green labels), id, group, check, result in "
            "its unit, found / checked, target, items listed, and for a check that reads a baseline the one it was "
            "measured against: name (Project ID) · kind. Only kind exact or in file is the baseline P6 measured "
            "against; probable is a copy found by its content. Fail = result on the wrong side of the target; info "
            f"and n/a are not scored. {CHECKS_BASELINE}"
        ),
        source="The standard's TOML `source` per check; `SCORE_HELP` (`ui.py:400-405`) for the score",
    ),
    "check_parameters": Reading(
        how="parameter, value, set by (standard or default): the effective settings of the check.",
        source="the TOML",
    ),
    "check_flagged": Reading(
        how=f"The tasks or links the check lists, culprits first; select a row to open the Gantt. {CHECKS_BASELINE}",
        source="the check's `source`",
    ),
    "health_trend": Reading(
        how=(
            "One row per check, one column per update (value, `%.2f`). Read a row left to right as the check's "
            f"history. {CHECKS_BASELINE}"
        ),
        source="the check's `source`",
    ),
    "health_report": Reading(
        how=(
            "Found / total typed from the P6 report beside xerscope's, Match ticked when equal. A mismatch names "
            "the population to audit."
        ),
        source="P6 Professional Check Schedule report",
    ),
    "sheet_settings": Reading(
        how="setting, now, default, accepts: the `[[metric]]` values to paste into a standard file.",
        source="`analysis/audit.settings_table`",
    ),
    "check_sets": Reading(
        how=f"The three sets behind a count; nothing is recomputed (`audit.split`). {CHECKS_BASELINE}",
        source="the check's `source`",
    ),
    "funnel": FUNNEL_READING,
    "ask_funnel": FUNNEL_READING,
    "changelog_categories": Reading(
        how="category, total changes, kinds seen.",
        source="docs/formulas.md §5",
    ),
    "changelog_all": Reading(
        how=(
            "One row per change: task, category, change, field, before, after, Δ (wd for dates, later = negative; "
            "after − before otherwise)."
        ),
        source="docs/formulas.md §5",
    ),
    "changelog_weekly": Reading(
        how=(
            "(category, change) rows, one column per week: counts. A kind that repeats every week is a habit of the "
            "updating, not an event."
        ),
        source="`changelog.weekly_change_matrix` (`493-499`)",
    ),
    "forensics_steps": Reading(
        how="step, finish once applied, shift (wd), changes applied: the table of the half-step bars.",
        source="AACE RP 29R-03 MIP 3.4",
    ),
    "forensics_series": Reading(
        how=(
            "One row per update: finish held by (last activity, Must Finish By, Mandatory Finish), finish shown, "
            "finish before replanning, slip, replanning, residual, period (wd), recalculated vs file (wd), longest "
            "path float (d), matched / added / deleted, note."
        ),
        source="AACE RP 29R-03 MIP 3.4; `FINISH_CASES` text (`forensics.py:20-25`)",
    ),
    "forensics_horizon": Reading(
        how=(
            "Per step after progress, then for all of them: revisions on tasks starting within the lookahead "
            "(work under way included), revisions beyond it, and the share beyond (%). The lookahead runs from "
            "the status date, 6 weeks unless set otherwise."
        ),
        source=(
            "AACE RP 29R-03 3.4.K.4 (what counts as a revision); Last Planner (the lookahead); the split is "
            "xerscope's reading, docs/formulas.md §5.1"
        ),
    ),
    "forensics_path": Reading(
        how=(
            "One row per open task on the longest path of either update: its change (stayed, entered, left: "
            "finished, left: still open, left: deleted), its total float in the earlier update, then the task as "
            "the later update holds it."
        ),
        source="AACE RP 29R-03 3.4.E.9 and SVP 2.3.B.6; docs/formulas.md §5.2",
    ),
    "forensics_path_commitments": Reading(
        how=(
            "The week's commitments made on the earlier update's longest path, read as on the PPC page: each "
            "task, what it committed and whether it was kept. A miss here moves the finish."
        ),
        source="Last Planner (PPC); restricted to the longest path, xerscope's reading, docs/formulas.md §5.2",
    ),
    "forensics_path_churn": Reading(
        how=(
            "Per update after the first: tasks on the longest path, stayed, entered, left finished, left still "
            "open, left deleted, stability = stayed / (stayed + left still open), where the path was read, then "
            "the week's PPC over every commitment and over those on the path."
        ),
        source="AACE RP 29R-03 SVP 2.3.B.6; docs/formulas.md §5.2",
    ),
    "ev_window_weeks": Reading(
        how=(
            "One row per week of the SPI (4 weeks) window, oldest first: the hours earned and planned that week "
            "(ev_gain_hr, pv_gain_hr), the plan days gained and elapsed (es_gain_plan_d, at_gain_plan_d), and "
            "whether the baseline changed at the week's end."
        ),
        meaning="SPI (4 weeks) is the sum of ev_gain_hr over the sum of pv_gain_hr; the pace, the same in plan days.",
        conclude="a week with few planned hours weighs little; the week with the largest gap is the one to look at.",
        source="xerscope (docs/formulas.md, Earned Schedule): weekly gains, each week read on the plan in force.",
    ),
    "ev_calculation": Reading(
        how=(
            "measure, P6 column, formula, value this update: each EV figure with its P6 name and the numbers behind "
            f"it. {ORIGIN_BASELINE}"
        ),
        source="Oracle P6 glossary (docs/formulas.md §3); EVMS EIA-748 names",
    ),
    "ev_updates": Reading(
        how=(
            "One row per update: PV, EV, AC, SV, SPI, SPI 4 weeks, BEI P6 / DCMA, CPI, EV / AC baselined; indices "
            f"written as text with a dash on the first update. {ORIGIN_BASELINE}"
        ),
        source="docs/formulas.md §3; DCMA 14-Point item 14 (BEI)",
    ),
    "ev_tasks": Reading(
        how=(
            "Per baseline task present in the update: EV budget, schedule %, PV, technique, performance %, EV, "
            f"actual hours, EV finish. {ORIGIN_BASELINE}"
        ),
        source="docs/formulas.md §3",
    ),
    "mta_slips": Reading(
        how=(
            "Per milestone: first and latest forecast, slip since first (wd), last update (wd), on its own "
            "calendar; later = negative."
        ),
        source="docs/formulas.md §4 MTA",
    ),
    "mta_trend": Reading(
        how="The long frame of the chart: one row per milestone and update.",
        source="docs/formulas.md §4 MTA",
    ),
    "ppc_weeks": Reading(
        how="Per week: starts / finishes kept and committed, the three PPC, kept and committed together, note.",
        source="Last Planner System (PPC); docs/formulas.md §4",
    ),
    "ppc_commitments": PPC_COMMITMENTS_READING,
    "ppc_milestones": PPC_COMMITMENTS_READING,
    "ppc_wbs": Reading(
        how="Per WBS level 1: progress points, earned and actual hours this week, budget, tasks progressed.",
        source="docs/formulas.md §4 Roll-up",
    ),
    "ppc_unplanned": Reading(
        how="Tasks absent from W−1 with an actual start by W's status date: work done outside W−1's plan.",
        source="docs/formulas.md §4",
    ),
    "ppc_lookahead": Reading(
        how=(
            "Per week and horizon (updates ahead): the plan read, the week's commitments, those that plan already "
            "held for the week (TA %), what that plan held for the week and how much of it was done (TMR %)."
        ),
        source=(
            "Last Planner: Hamzeh, Ballard & Tommelein 2012 (TA and TMR one and two weeks ahead; four and eight "
            "are xerscope's reading); docs/formulas.md §4"
        ),
    ),
    "ppc_progress": Reading(
        how=(
            "Tasks whose % complete, earned or actual hours moved: % previous, % now, Δ, earned and actual hours "
            "this week."
        ),
        source="docs/formulas.md §4 Progress delta",
    ),
    "ppc_variances": Reading(
        how=(
            "Per task, wd of its calendar between its date in W−1 / W−2 and now (reference − current): negative = "
            "later."
        ),
        source="xerscope (`analysis/progress.py`)",
    ),
    "gantt_tasks": Reading(
        how=(
            "The bars as rows: task, WBS, status, float category, dates, total float and remaining (wd, dash when "
            f"complete), % complete, budget hours, constraint. {CHECKS_BASELINE}"
        ),
        source=(
            "Oracle P6 Professional Activities view and Define critical activities (via "
            "`explain.critical_definition`); xerscope `config.Settings`."
        ),
    ),
    "task_resources": TASK_TABLES_READING,
    "task_logic": TASK_TABLES_READING,
    "task_trail": Reading(
        how=(
            "one row per task opened from this panel, in the order they were opened (the one shown last), then "
            "one per predecessor and successor of the task shown; one column per update: the link as that update "
            "holds it (type, and driving when it sets the successor's date: recalculated by the CPM, the XER does "
            "not export it), P6's total float (TF) and free float (FF) in working days, then the primary / "
            "secondary constraint with its date. A blank cell: not in that update, or not linked to the task "
            "there. Select a row to open that task."
        ),
        source="P6 TASK (total_float_hr_cnt, free_float_hr_cnt, cstr_type, cstr_date, cstr_type2, cstr_date2) and "
        "TASKPRED of each update; driving: xerscope CPM (`cpm.Schedule.links`)",
    ),
    "task_constraints": Reading(
        how=(
            "each constraint added, removed or changed on the task between two consecutive updates, dated by the "
            "later update's status date: the Constraints rows of the changelog."
        ),
        source="xerscope changelog (`changelog.constraint_changes`)",
    ),
    "task_history": TASK_TABLES_READING,
    "export_tables": EXPORT_TABLES_READING,
    "export_fact_activity": EXPORT_TABLES_READING,
    "debug": Reading(
        how=(
            "Raw readings for comparison with P6; no reading beyond each block's caption (`debug.py:379-381, "
            "419-423, 469-472`)."
        ),
        source="Oracle P6 EPPM 26 help, Schedule Project Log; P6 XER data map",
    ),
}


TSPI_HOLDS, TSPI_CATCH_UP = 1.00, 1.10  # Lipke: up to 1.00 the date holds; above 1.10 it is rarely caught up


def schedule_reading(
    gap_d: float | None,
    plan_reached: str,
    pace_4w: float | None,
    pace_all: float | None,
    finish_4w: str,
    finish_all: str,
    plan_finish: str,
    tspi: float | None,
) -> str:
    """The Earned Schedule figures of an update put into one paragraph, in the order a reader asks: where the
    project stands, at what pace, whether it ends on the planned finish. Dates come formatted; a figure
    missing leaves its sentence out. The only judgement is Lipke's TSPI band, which the TSPI help cites.
    """
    sentences = [
        _standing(gap_d, plan_reached),
        _pace(pace_4w, pace_all),
        _forecasts(finish_4w, finish_all),
        _tspi(tspi, plan_finish),
    ]
    return " ".join(sentence for sentence in sentences if sentence)


def _standing(gap_d: float | None, plan_reached: str) -> str:
    """Where the project stands on its plan, from the time gap in calendar days."""
    if gap_d is None:
        return "Every planned hour is earned."
    if round(gap_d) == 0:
        return f"On plan: the plan reached is the status date ({plan_reached})."
    side = "behind" if gap_d < 0 else "ahead of"
    return f"{abs(gap_d):.0f} calendar days {side} the plan: the work done was planned for {plan_reached}."


def _pace(pace_4w: float | None, pace_all: float | None) -> str:
    """The pace of the last four weeks against the pace since the first update; empty without both."""
    if pace_4w is None or pace_all is None:
        return ""
    trend = "slower than" if pace_4w < pace_all else "faster than" if pace_4w > pace_all else "the same as"
    return f"Pace over the last 4 weeks {pace_4w:.2f}, {trend} since the first update ({pace_all:.2f})."


def _forecasts(finish_4w: str, finish_all: str) -> str:
    """When the plan ends at each pace; empty without either forecast."""
    forecasts = [
        f"at the recent pace on {finish_4w}" if finish_4w else "",
        f"at the overall pace on {finish_all}" if finish_all else "",
    ]
    forecasts = [text for text in forecasts if text]
    return "The plan ends " + " and ".join(forecasts) + "." if forecasts else ""


def _tspi(tspi: float | None, plan_finish: str) -> str:
    """The pace the planned finish needs, read on Lipke's band; empty once the planned finish is passed."""
    if tspi is None:
        return ""
    if tspi <= TSPI_HOLDS:
        verdict = "the date holds"
    elif tspi <= TSPI_CATCH_UP:
        verdict = "it can be caught up"
    else:
        verdict = "it is rarely caught up (Lipke)"
    return f"Ending on the planned finish ({plan_finish}) needs a pace of {tspi:.2f}: {verdict}."
