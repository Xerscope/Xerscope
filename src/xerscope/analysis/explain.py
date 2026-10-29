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

from dataclasses import dataclass, field

from ..xer.model import CONSTRAINT
from .checks import CheckResult
from .rules import RULES

EXCLUDE_TEXT = {
    "complete": "completed activities",
    "complete_before_data_date": "activities completed before the data date",
    "started": "started activities",
    "loe": "level of effort",
    "milestones": "milestones",
    "no_duration": "activities with no original duration",
}
EXEMPT_TEXT = {
    "started": "started activities",
    "start_milestone": "start milestones",
    "finish_milestone": "finish milestones",
    "project_start": "the project's first activity",
    "project_finish": "the project's last activity",
}
LINKS_TEXT = {
    "all": "all relationships",
    "not_both_complete": "relationships where predecessor and successor are not both complete",
    "succ_incomplete": "relationships into an incomplete successor",
}
OP_TEXT = {"<=": "≤", ">=": "≥", "==": "=", "<": "<", ">": ">"}

# rule -> (what the numerator counts, what the denominator counts, what the flagged list holds)
WORDING: dict[str, tuple[str, str, str]] = {
    "relationship_type": ("of the required type", "relationships checked", "Relationships of another type"),
    "bei": ("completed", "due by the data date", "Due by the data date but not completed"),
    "missed_tasks": ("missed", "due by the data date", "Due by the data date and not finished on time"),
    "late_vs_baseline": ("late", "checked", "Forecast to finish after their baseline finish"),
    "missing_logic": ("open-ended", "checked", "Missing a predecessor or a successor"),
    "open_ends": ("with an open start or finish", "incomplete tasks and milestones", "Open start or open finish"),
    "constraints": ("constrained", "checked", "Constrained activities"),
    "float": ("flagged", "checked", "Activities outside the float limit"),
    "duration": ("flagged", "checked", "Activities outside the duration limit"),
    "lag": ("flagged", "relationships checked", "Relationships with the lag in question"),
    "invalid_dates": ("with invalid dates", "checked", "Progress dates on the wrong side of the data date"),
    "no_resource": ("without resources", "checked", "Activities with no resource assignment"),
    "recalculated": ("different", "open activities", "Stored dates differ from the recalculation"),
    "assignments_recalculated": ("different", "open assignments", "Assignment dates differ from the recalculation"),
    "out_of_sequence": ("out of sequence", "", "Progressed out of logic sequence"),
    "lagged_activities": ("with a lag", "incomplete tasks and milestones", "Activities with a lag on a predecessor"),
    "summary_logic": ("with logic", "", "Summary activities carrying logic"),
    "loe_successors": ("with a discrete successor", "incomplete LOE", "LOE driving discrete work"),
    "missing_baseline": ("without baseline dates", "tasks and milestones", "Missing a baseline start or finish"),
    "actuals_changed": ("changed", "with that actual date", "Actual date changed since the previous update"),
    "progress_actuals": ("without the actual date", "showing that progress", "Progress without the matching actual"),
    "riding_status_date": ("riding the status date", "checked", "Forecasts riding the status date"),
    "dangling": ("dangling", "checked", "Logic that does not drive the activity"),
}
LINK_RULES = {"lag", "relationship_type"}


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


def noun(subject: str, n: int) -> str:
    """'activities' / 'relationships', singular when n == 1."""
    return subject if n != 1 else {"activities": "activity", "relationships": "relationship"}.get(subject, subject)


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "%":
        return f"{value:.1f} %"
    if unit == "ratio":
        return f"{value:.2f}"
    if unit == "pass/fail":
        return "pass" if value >= 1 else "fail"
    return f"{value:g}"


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


def _population(rule: str, p: dict) -> list[str]:
    out = []
    if p.get("exclude"):
        out.append("Excludes: " + ", ".join(EXCLUDE_TEXT.get(k, k) for k in p["exclude"]) + ".")
    if p.get("pred_exempt"):
        out.append("No predecessor required for: " + ", ".join(EXEMPT_TEXT.get(k, k) for k in p["pred_exempt"]) + ".")
    if p.get("succ_exempt"):
        out.append("No successor required for: " + ", ".join(EXEMPT_TEXT.get(k, k) for k in p["succ_exempt"]) + ".")
    if "links" in p:
        out.append("Relationships counted: " + LINKS_TEXT.get(p["links"], p["links"]) + ".")
    if p.get("exclude_loe"):
        out.append("Relationships to or from level-of-effort activities are left out.")
    if p.get("types"):
        out.append("Constraint types: " + ", ".join(CONSTRAINT.get(c, c) for c in p["types"]) + ".")
    if "op" in p and "value" in p:
        what = {"lag": "lag", "float": "total float", "duration": f"{p.get('field', 'original')} duration"}.get(
            rule, "value"
        )
        unit = p.get("unit", "")
        out.append(f"Flagged when {what} {OP_TEXT.get(p['op'], p['op'])} {p['value']:g} {unit}".rstrip() + ".")
    if rule == "relationship_type":
        out.append(f"Counts relationships of type {p.get('type', 'FS')}; the list shows the others.")
    if rule == "bei":
        rule_text = "counted as due" if p.get("missing_baseline", "due") == "due" else "left out"
        out.append(
            f"Activities without a baseline finish are {rule_text}. "
            "Completed = all completed activities in the population, early ones included."
        )
    if rule == "missed_tasks":
        out.append(
            "Due = baseline finish on or before the data date. Missed = not finished, "
            "or finished on a later day than the baseline finish."
        )
    if rule == "late_vs_baseline":
        out.append("Variance is working time on the activity's calendar, as P6's Finish Variance.")
    return out


def explain(result: CheckResult) -> Explanation:
    m = result.metric
    rule = RULES[m.rule]
    effective = {**rule.params, **m.params}
    parameters = [(k, _show(v), "standard" if k in m.params else "default") for k, v in effective.items()]
    num_word, den_word, flagged_word = WORDING.get(m.rule, ("flagged", "checked", "Flagged items"))
    links = m.rule in LINK_RULES or "pred_code" in result.flagged.columns
    subject = "relationships" if links else "activities"
    if links and den_word == "checked":
        den_word = "relationships checked"

    n, d, v = result.numerator, result.denominator, result.value
    if result.status in ("n/a", "error"):
        formula = result.note or "not computed"
    elif m.unit == "%" and n is not None and d:
        formula = f"{n} {num_word} / {d} {den_word} = {fmt_value(v, '%')}"
    elif m.unit == "ratio" and n is not None and d:
        formula = f"{n} {num_word} / {d} {den_word} = {fmt_value(v, 'ratio')}"
    elif m.unit == "count":
        k = n if n is not None else 0
        formula = f"{k} {noun(subject, k)} {num_word}"
    else:
        formula = result.note or fmt_value(v, m.unit)

    target = _target(m)
    shown = fmt_value(v, m.unit)
    if m.unit == "pass/fail" and result.status in ("pass", "fail"):
        verdict = "Passed." if result.status == "pass" else "Failed."
    elif result.status == "pass":
        verdict = f"{shown} meets the target {target}."
    elif result.status == "fail":
        verdict = f"{shown} misses the target {target}."
    elif result.status == "info":
        verdict = "Reported for review: this standard sets no pass/fail target."
    elif result.status == "n/a":
        verdict = "Not applicable: " + (result.note or "nothing to check") + "."
    else:
        verdict = "The rule raised an error: " + result.note

    return Explanation(
        measured=m.description,
        formula=formula,
        verdict=verdict,
        method=rule.doc,
        population=_population(m.rule, effective),
        parameters=parameters,
        flagged_label=flagged_word,
        subject=subject,
    )
