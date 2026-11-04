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
        out.append("Relationships to or from level-of-effort activities are left out.")
    if params.get("types"):
        out.append("Constraint types: " + ", ".join(CONSTRAINT.get(code, code) for code in params["types"]) + ".")
    return out


def _flag_line(rule: Rule, params: dict) -> list[str]:
    """'Flagged when <what> <op> <value> <unit>.' for the rules that compare a value."""
    if "op" not in params or "value" not in params:
        return []
    what = MEASURE_TEXT.get(rule.name, "value").format(**params)
    unit = params.get("unit", "")
    comparison = OP_TEXT.get(params["op"], params["op"])
    return [f"Flagged when {what} {comparison} {params['value']:g} {unit}".rstrip() + "."]


def _relationship_type_notes(params: dict) -> list[str]:
    return [f"Counts relationships of type {params.get('type', 'FS')}; the list shows the others."]


def _invalid_dates_notes(params: dict) -> list[str]:
    if params.get("in_progress") == "start":
        return ["An in-progress activity is flagged when its remaining early start is before the data date."]
    return []


def _late_vs_baseline_notes(params: dict) -> list[str]:
    notes = ["Variance is working time on the activity's calendar, as P6's Finish Variance."]
    if params.get("no_baseline") == "planned":
        notes.append("An activity with no baseline finish is late when its finish is later than its planned finish.")
    return notes


def _bei_notes(params: dict) -> list[str]:
    if params.get("due_from") == "baseline":
        due_text = (
            "Due = baseline activities finishing on or before the data date, counted in the "
            "baseline: an activity added since is never due, one deleted since still is."
        )
    else:
        missing = "counted as due" if params.get("missing_baseline", "due") == "due" else "left out"
        due_text = f"Activities without a baseline finish are {missing}."
    return [due_text + " Completed = all completed activities in the population, early ones included."]


def _limit_note(measure: str, key: str, unit: str) -> Callable[[dict], list[str]]:
    """'Flagged when <measure> > <limit> <unit>.' for the built-in checks with an x threshold."""
    return lambda params: [f"Flagged when {measure} > {params[key]:g} {unit}."]


def _slip_notes(params: dict) -> list[str]:
    return [f"The first open critical activity is delayed by {params['slip_days']:g} working days."]


def _status_period_notes(params: dict) -> list[str]:
    return [f"Compared with the latest update at least {params['status_period_days']:g} days older."]


def _riding_notes(params: dict) -> list[str]:
    return [
        *_status_period_notes(params),
        f"Rides when the start is within {params['riding_window_wd']:g} working days of the data date in both updates,"
        f" or the remaining duration moved by at most {params['remaining_tolerance_wd']:g} working days.",
    ]


# rule name -> sentences that depend on the rule's parameters
NOTES: dict[str, Callable[[dict], list[str]]] = {
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
    "invalid_dates": _invalid_dates_notes,
    "late_vs_baseline": _late_vs_baseline_notes,
    "bei": _bei_notes,
}


def _population(rule: Rule, params: dict) -> list[str]:
    """The docstring's population lines, then the sentences written from the parameters."""
    notes = NOTES.get(rule.name)
    return [*rule.population, *_scope_lines(rule, params), *_flag_line(rule, params), *(notes(params) if notes else [])]


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
        return "Reported for review: this standard sets no pass/fail target."
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
    num_word, den_word = rule.numerator_word, rule.denominator_word
    links = rule.links or "pred_code" in result.flagged.columns
    subject = "relationships" if links else "activities"
    if links and den_word == "checked":
        den_word = "relationships checked"

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
