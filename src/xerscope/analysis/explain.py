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
from .rules import EXCLUDE, EXEMPT, RULES, Rule

LINKS_TEXT = {
    "all": "all relationships",
    "not_both_complete": "relationships where predecessor and successor are not both complete",
    "succ_incomplete": "relationships into an incomplete successor",
}
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


def _exclude_line(links: bool, exclude: list[str]) -> str:
    what = ", ".join((EXCLUDE[k][0] if k in EXCLUDE else k) for k in exclude)
    return f"Relationships whose successor is excluded: {what}." if links else f"Excludes: {what}."


def _scope_lines(rule: Rule, p: dict) -> list[str]:
    out = []
    if p.get("exclude"):
        out.append(_exclude_line(rule.links, p["exclude"]))
    if p.get("pred_exempt"):
        out.append("No predecessor required for: " + ", ".join(EXEMPT.get(k, k) for k in p["pred_exempt"]) + ".")
    if p.get("succ_exempt"):
        out.append("No successor required for: " + ", ".join(EXEMPT.get(k, k) for k in p["succ_exempt"]) + ".")
    if "links" in p:
        out.append("Relationships counted: " + LINKS_TEXT.get(p["links"], p["links"]) + ".")
    if p.get("exclude_loe"):
        out.append("Relationships to or from level-of-effort activities are left out.")
    if p.get("types"):
        out.append("Constraint types: " + ", ".join(CONSTRAINT.get(c, c) for c in p["types"]) + ".")
    return out


def _flag_line(rule: Rule, p: dict) -> list[str]:
    if "op" not in p or "value" not in p:
        return []
    what = {"lag": "lag", "float": "total float", "duration": f"{p.get('field', 'original')} duration"}.get(
        rule.name, "value"
    )
    unit = p.get("unit", "")
    return [f"Flagged when {what} {OP_TEXT.get(p['op'], p['op'])} {p['value']:g} {unit}".rstrip() + "."]


def _population(rule: Rule, p: dict) -> list[str]:
    return _scope_lines(rule, p) + _flag_line(rule, p) + (rule.notes(p) if rule.notes else [])


def _formula(result: CheckResult, subject: str, words: tuple[str, str]) -> str:
    m = result.metric
    num_word, den_word = words
    n, d, v = result.numerator, result.denominator, result.value
    if result.status in ("n/a", "error"):
        return result.note or "not computed"
    if m.unit == "%" and n is not None and d:
        return f"{n} {num_word} / {d} {den_word} = {fmt_value(v, '%')}"
    if m.unit == "ratio" and n is not None and d:
        return f"{n} {num_word} / {d} {den_word} = {fmt_value(v, 'ratio')}"
    if m.unit == "count":
        k = n if n is not None else 0
        return f"{k} {noun(subject, k)} {num_word}"
    return result.note or fmt_value(v, m.unit)


def _verdict(result: CheckResult) -> str:
    m = result.metric
    target = _target(m)
    shown = fmt_value(result.value, m.unit)
    if m.unit == "pass/fail" and result.status in ("pass", "fail"):
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
    m = result.metric
    rule = RULES[m.rule]
    effective = {**rule.params, **m.params}
    parameters = [(k, _show(v), "standard" if k in m.params else "default") for k, v in effective.items()]
    num_word, den_word, flagged_word = rule.wording or ("flagged", "checked", "Flagged items")
    links = rule.links or "pred_code" in result.flagged.columns
    subject = "relationships" if links else "activities"
    if links and den_word == "checked":
        den_word = "relationships checked"

    return Explanation(
        measured=m.description,
        formula=_formula(result, subject, (num_word, den_word)),
        verdict=_verdict(result),
        method=rule.doc,
        population=_population(rule, effective),
        parameters=parameters,
        flagged_label=flagged_word,
        subject=subject,
    )
