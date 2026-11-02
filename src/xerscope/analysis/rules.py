"""Rule library: every schedule check is one parameterised function.

A standard is a TOML profile (``xerscope/standards/*.toml`` or your own file) that picks
rules, sets their parameters and a target. One rule serves several standards: P6's
"Large Float" and DCMA-06 are both ``float``, one in hours with P6's population, the
other in working days with DCMA's. So P6, DCMA and a company standard share the code
and differ only in data.

Each rule returns a :class:`RuleOutput`; the profile's target turns it into pass/fail.
Populations always exclude WBS-summary rows (``Snapshot.activities``).

Docstring convention. ``explain.py`` words a result from the rule's docstring:

    Constrained activities.                    <- title (label of the flagged list)
    Counts: constrained / checked              <- numerator word / denominator word
    Excludes: completed activities.            <- population lines, zero or more, shown as written
    Constraint types: A, B,
        continued on an indented line.         <- an indented line continues the one above

    Everything after the first blank line is the method text (what ``--rules`` prints).

A docstring without a ``Counts:`` second line is all method text. Rules whose population
depends on their parameters (the generic ones) leave out the population lines:
``explain.py`` writes those from the parameters.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from ..xer.model import CONSTRAINT, forecast_dates
from .baseline import Baseline
from .populations import (  # noqa: F401 - re-exported
    ACTIVITY_COLS,
    LINK_COLS,
    constrained_by,
    flagged_activities,
    flagged_relationships,
    open_end_reason,
)

if TYPE_CHECKING:
    from .checks import AnalysisContext

Unit = Literal["%", "ratio", "count", "days", "pass/fail"]
Names = tuple[str, ...] | list[str]  # TOML gives lists, defaults are tuples
Op = Literal["<", "<=", ">", ">="]
LinkPop = Literal["all", "not_both_complete", "succ_incomplete"]


@dataclass
class RuleOutput:
    flagged: pd.DataFrame = field(default_factory=pd.DataFrame)
    numerator: int | None = None
    denominator: int | None = None
    value: float | None = None  # set by ratio / pass-fail rules; % and counts are derived
    note: str = ""


_OPS = {"<": np.less, ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal}


@dataclass(frozen=True)
class Rule:
    name: str
    fn: Callable[..., RuleOutput]
    unit: Unit
    doc: str  # the method text: the docstring without its header
    needs_baseline: bool = False
    title: str = ""  # label of the flagged list, from the docstring header
    numerator_word: str = "flagged"
    denominator_word: str = "checked"
    population: tuple[str, ...] = ()  # fixed population lines, from the docstring header

    @property
    def links(self) -> bool:
        """True when the rule counts relationships, not activities."""
        return "relationships" in self.denominator_word

    @property
    def params(self) -> dict[str, object]:
        signature = inspect.signature(self.fn)
        return {name: parameter.default for name, parameter in list(signature.parameters.items())[1:]}

    def validate(self, params: dict) -> None:
        """Every parameter of a TOML metric checked on load against the rule's signature:
        name, choice (Literal), number, flag or list of names. A bad standard is refused
        before any check runs."""
        unknown = set(params) - set(self.params)
        if unknown:
            raise ValueError(
                f"rule {self.name!r} has no parameter(s) {sorted(unknown)}; allowed: {sorted(self.params)}"
            )
        hints = typing.get_type_hints(self.fn)
        for key, value in params.items():
            _check_value(f"{self.name}.{key}", hints.get(key), value)
        self._check_vocabulary(params)

    def _check_vocabulary(self, params: dict) -> None:
        for key in sorted(set(params) & set(ALLOWED)):
            bad = set(params[key]) - ALLOWED[key]
            if bad:
                what = "unknown" if key == "types" else "unknown value(s)"
                raise ValueError(f"{self.name}.{key}: {what} {sorted(bad)}; allowed {sorted(ALLOWED[key])}")


def _check_value(where: str, hint, value) -> None:
    if typing.get_origin(hint) is Literal:
        choices = typing.get_args(hint)
        if value not in choices:
            raise ValueError(f"{where}: {value!r} is not one of {list(choices)}")
    elif hint is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{where}: expected true or false, got {value!r}")
    elif hint in (float, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where}: expected a number, got {value!r}")
    elif hint == Names:
        if isinstance(value, str) or not all(isinstance(name, str) for name in value):
            raise ValueError(f"{where}: expected a list of names, got {value!r}")


RULES: dict[str, Rule] = {}


def read_docstring(doc: str) -> dict:
    """Split a docstring (convention at the top of this file) into Rule fields."""
    header, _, method = doc.partition("\n\n")
    lines: list[str] = []
    for line in header.splitlines():
        if line.startswith(" ") and lines:
            lines[-1] += " " + line.strip()  # an indented line continues the one above
        else:
            lines.append(line)
    if len(lines) < 2 or not lines[1].startswith("Counts:"):
        return {"doc": doc}
    numerator, _, denominator = lines[1].removeprefix("Counts:").partition("/")
    return {
        "doc": method,
        "title": lines[0].rstrip("."),
        "numerator_word": numerator.strip(),
        "denominator_word": denominator.strip(),
        "population": tuple(lines[2:]),
    }


def rule(name: str, unit: Unit, needs_baseline: bool = False):
    def register(function):
        fields = read_docstring(inspect.getdoc(function) or "")
        RULES[name] = Rule(name, function, unit, needs_baseline=needs_baseline, **fields)
        return function

    return register


# --- populations -------------------------------------------------------------------------


def is_complete(tasks, data_date):
    return tasks["is_complete"]


def is_complete_before_data_date(tasks, data_date):
    if data_date is None:
        return tasks["is_complete"]
    return tasks["act_end_date"] < data_date


def is_started(tasks, data_date):
    return tasks["is_started"]


def is_level_of_effort(tasks, data_date):
    return tasks["is_loe"]


def is_milestone(tasks, data_date):
    return tasks["is_milestone"]


def has_no_duration(tasks, data_date):
    return ~(tasks["target_drtn_hr_cnt"].fillna(0) > 0)


# Each closed vocabulary is declared once: key -> (label for explain, function).
EXCLUDE: dict[str, tuple[str, Callable]] = {
    "complete": ("completed activities", is_complete),
    "complete_before_data_date": ("activities completed before the data date", is_complete_before_data_date),
    "started": ("started activities", is_started),
    "loe": ("level of effort", is_level_of_effort),
    "milestones": ("milestones", is_milestone),
    "no_duration": ("activities with no original duration", has_no_duration),
}
EXEMPT: dict[str, str] = {
    "started": "started activities",
    "start_milestone": "start milestones",
    "finish_milestone": "finish milestones",
    "project_start": "the project's first activity",
    "project_finish": "the project's last activity",
}
ALLOWED: dict[str, set[str]] = {
    "exclude": set(EXCLUDE),
    "pred_exempt": set(EXEMPT),
    "succ_exempt": set(EXEMPT),
    "types": set(CONSTRAINT),
}


def activities(context: AnalysisContext, exclude: list[str]) -> pd.DataFrame:
    return _without(context.snapshot.activities, context.snapshot.data_date, exclude)


def _without(tasks: pd.DataFrame, data_date, exclude: list[str]) -> pd.DataFrame:
    excluded = pd.Series(False, index=tasks.index)
    for key in exclude:
        excluded |= EXCLUDE[key][1](tasks, data_date).fillna(False).astype(bool)
    return tasks[~excluded]


def _flag_of(codes: pd.Series, flags: pd.Series) -> pd.Series:
    """The boolean ``flags`` (indexed by task code) of each code; False for an unknown code."""
    return codes.map(flags).fillna(False).astype(bool)


def link_population(
    context: AnalysisContext, links: str, exclude_loe: bool = False, exclude: Names = ()
) -> pd.DataFrame:
    snapshot = context.snapshot
    tasks = snapshot.activities.set_index("task_code")
    relationships = snapshot.relationships
    relationships = relationships[relationships["succ_code"].isin(tasks.index)]
    predecessor_done = _flag_of(relationships["pred_code"], tasks["is_complete"])
    successor_done = _flag_of(relationships["succ_code"], tasks["is_complete"])
    if links == "not_both_complete":
        relationships = relationships[~(predecessor_done & successor_done)]
    elif links == "succ_incomplete":
        relationships = relationships[~successor_done]
    if exclude:
        # DCMA PAM 200.1 section 4.0 reading: a link counts when its successor is a retained
        # task; the predecessor may itself be excluded (a link out of a milestone counts).
        kept = _without(snapshot.activities, snapshot.data_date, list(exclude))
        relationships = relationships[relationships["succ_code"].isin(kept["task_code"])]
    if exclude_loe:
        touches_loe = _flag_of(relationships["pred_code"], tasks["is_loe"]) | _flag_of(
            relationships["succ_code"], tasks["is_loe"]
        )
        relationships = relationships[~touches_loe]
    names = tasks["task_name"]
    return relationships.assign(
        pred_name=relationships["pred_code"].map(names), succ_name=relationships["succ_code"].map(names)
    )


def _project_ends(context: AnalysisContext) -> tuple[set[str], set[str]]:
    """Activities at the project's start (no predecessor, earliest start) and finish."""
    tasks = context.snapshot.activities
    relationships = context.snapshot.relationships
    no_predecessor = tasks[~tasks["task_code"].isin(relationships["succ_code"])]
    no_successor = tasks[~tasks["task_code"].isin(relationships["pred_code"])]
    first = no_predecessor["start"].min()
    last = no_successor["finish"].max()
    return (
        set(no_predecessor.loc[no_predecessor["start"] == first, "task_code"]),
        set(no_successor.loc[no_successor["finish"] == last, "task_code"]),
    )


def _exempt_masks(population: pd.DataFrame, start_ids: set[str], finish_ids: set[str]) -> dict[str, pd.Series]:
    """One boolean mask per EXEMPT key: the activities that pass the missing-logic test."""
    masks = {
        "started": population["is_started"],
        "start_milestone": population["is_start_milestone"],
        "finish_milestone": population["is_milestone"] & ~population["is_start_milestone"],
        "project_start": population["task_code"].isin(start_ids),
        "project_finish": population["task_code"].isin(finish_ids),
    }
    return {key: masks[key] for key in EXEMPT}


# --- logic -------------------------------------------------------------------------------


@rule("missing_logic", "%")
def missing_logic(
    context,
    exclude: Names = ("complete",),
    pred_exempt: Names = (),
    succ_exempt: Names = (),
    external_passes: bool = True,
    dangling: bool = False,
) -> RuleOutput:
    """Missing a predecessor or a successor.
    Counts: open-ended / checked

    Activities without a predecessor or a successor (open ends).

    ``pred_exempt`` / ``succ_exempt`` pass one side for: started, start_milestone,
    finish_milestone, project_start, project_finish. ``external_passes`` counts links to
    other projects. ``dangling`` also flags a start not driven by any FS/SS predecessor
    or a finish that drives no FS/FF successor.
    """
    population = activities(context, exclude)
    relationships = context.snapshot.relationships
    own = relationships[~relationships["is_external"].astype(bool)]  # links within the project; the others are optional
    has_predecessor = population["task_code"].isin(own["succ_code"])
    has_successor = population["task_code"].isin(own["pred_code"])
    if external_passes:
        has_predecessor |= population["has_external_pred"]
        has_successor |= population["has_external_succ"]
    exempt_mask = _exempt_masks(population, *_project_ends(context))
    for key in pred_exempt:
        has_predecessor |= exempt_mask[key]
    for key in succ_exempt:
        has_successor |= exempt_mask[key]
    reason = open_end_reason(~has_predecessor, ~has_successor)
    if dangling:
        drives_start = set(relationships.loc[relationships["type"].isin(["FS", "SS"]), "succ_code"])
        driven_by_finish = set(relationships.loc[relationships["type"].isin(["FS", "FF"]), "pred_code"])
        dangling_start = (
            has_predecessor
            & ~population["task_code"].isin(drives_start)
            & ~population["is_started"]
            & ~population["has_external_pred"]
            & ~exempt_mask["project_start"]
        )
        dangling_finish = (
            has_successor
            & ~population["task_code"].isin(driven_by_finish)
            & ~population["has_external_succ"]
            & ~exempt_mask["project_finish"]
        )
        reason = reason.mask((reason == "") & dangling_start, "dangling start (no FS/SS predecessor)")
        reason = reason.mask((reason == "") & dangling_finish, "dangling finish (no FS/FF successor)")
    flagged = population[reason != ""]
    return RuleOutput(flagged_activities(flagged, reason=reason[reason != ""]), len(flagged), len(population))


@rule("dangling", "%")
def dangling(context, end: Literal["start", "finish"] = "finish", exclude: Names = ("complete",)) -> RuleOutput:
    """Logic that does not drive the activity.
    Counts: dangling / checked

    Activities with logic on one end that does not drive it.

    ``end = "start"``: has predecessors but none FS or SS (the start floats free).
    ``end = "finish"``: has successors but none FS or FF (the finish drives nothing).
    Activities with no logic at all on that end are left to ``missing_logic``.
    """
    if end not in ("start", "finish"):
        raise ValueError("dangling.end must be 'start' or 'finish'")
    population = activities(context, exclude)
    relationships = context.snapshot.relationships
    if end == "start":
        population = population[~population["is_started"]]
        has_logic = population["task_code"].isin(relationships["succ_code"])
        driving_types = relationships["type"].isin(["FS", "SS"])
        driving = population["task_code"].isin(relationships.loc[driving_types, "succ_code"])
    else:
        has_logic = population["task_code"].isin(relationships["pred_code"])
        driving_types = relationships["type"].isin(["FS", "FF"])
        driving = population["task_code"].isin(relationships.loc[driving_types, "pred_code"])
    flagged = population[has_logic & ~driving]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population))


@rule("lag", "%")
def lag(
    context,
    op: Op = ">",
    value: float = 0,
    unit: Literal["hours", "days"] = "hours",
    links: LinkPop = "succ_incomplete",
    exclude_loe: bool = False,
    exclude: Names = (),
) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / relationships checked

    Relationships whose lag compares to ``value`` with ``op`` (<, >, <=, >=).

    Negative = lead (``op = "<"``, value 0); positive lag (``">"``, 0); long lag
    (``">"``, 352 hours). ``unit``: hours, or days on the lag calendar.
    """
    relationships = link_population(context, links, exclude_loe, exclude)
    column = {"hours": "lag_hr", "days": "lag_d"}[unit]
    flagged = relationships[_OPS[op](relationships[column].fillna(0), value)]
    return RuleOutput(flagged_relationships(flagged), len(flagged), len(relationships))


@rule("relationship_type", "%")
def relationship_type(
    context,
    type: Literal["FS", "SS", "FF", "SF"] = "FS",
    links: LinkPop = "succ_incomplete",
    exclude_loe: bool = False,
    exclude: Names = (),
) -> RuleOutput:
    """Relationships of another type.
    Counts: of the required type / relationships checked

    Share of relationships of ``type`` (value), listing the others.
    """
    relationships = link_population(context, links, exclude_loe, exclude)
    of_type = relationships["type"] == type
    share = 100.0 * of_type.sum() / len(relationships) if len(relationships) else None
    mix = ", ".join(f"{kind} {count}" for kind, count in relationships["type"].value_counts().items())
    others = flagged_relationships(relationships[~of_type])
    return RuleOutput(others, int(of_type.sum()), len(relationships), share, note=mix)


# --- constraints, float, duration ----------------------------------------------------------


@rule("constraints", "%")
def constraints(
    context, types: Names = (), exclude: Names = ("complete",), ignore_start_when_started: bool = True
) -> RuleOutput:
    """Constrained activities.
    Counts: constrained / checked

    Activities with a primary or secondary constraint in ``types`` (P6 codes, e.g. CS_MANDSTART).
    """
    population = activities(context, exclude)
    flagged = population[constrained_by(population, types, ignore_start_when_started)]
    extra = {"constraint2": flagged["cstr_type2"].map(CONSTRAINT)}
    return RuleOutput(flagged_activities(flagged, **extra), len(flagged), len(population))


@rule("float", "%")
def total_float(
    context, op: Op = ">", value: float = 44, unit: Literal["hours", "days"] = "days", exclude: Names = ("complete",)
) -> RuleOutput:
    """Activities outside the float limit.
    Counts: flagged / checked

    Activities whose total float compares to ``value`` (hours as stored, or working days).
    """
    population = activities(context, exclude)
    column = {"hours": "total_float_hr_cnt", "days": "total_float_d"}[unit]
    flagged = population[_OPS[op](population[column], value).fillna(False).astype(bool)]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population))


@rule("duration", "%")
def duration(
    context,
    field: Literal["original", "remaining", "baseline"] = "original",
    op: Op = ">",
    value: float = 44,
    unit: Literal["hours", "days"] = "days",
    exclude: Names = ("complete",),
) -> RuleOutput:
    """Activities outside the duration limit.
    Counts: flagged / checked

    Activities whose ``original``, ``remaining`` or ``baseline`` duration compares to ``value``.

    ``baseline`` (DCMA-EA PAM 200.1 4.8) is the baseline's planned duration, matched by Activity ID. In
    days it is divided by the activity's current hours per day (the baseline calendar is not used). An
    activity absent from the baseline has no baseline duration, so it is never flagged but stays in the
    denominator. Without a baseline the rule has no value (n/a).
    """
    population = activities(context, exclude)
    if field == "baseline":
        if context.baseline is None:
            return RuleOutput(note="needs a baseline")
        hours = population["task_code"].map(context.baseline.frame["bl_duration_hr"])
        measured = hours if unit == "hours" else hours / population["hours_per_day"]
    else:
        column = {
            ("original", "hours"): "target_drtn_hr_cnt",
            ("remaining", "hours"): "remain_drtn_hr_cnt",
            ("original", "days"): "original_d",
            ("remaining", "days"): "remaining_d",
        }[(field, unit)]
        measured = population[column]
    flagged = population[_OPS[op](measured, value).fillna(False).astype(bool)]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population))


# --- progress --------------------------------------------------------------------------


@rule("invalid_dates", "%")
def invalid_dates(
    context,
    kind: Literal["forecast", "actual", "both"] = "both",
    exclude: Names = ("loe", "complete_before_data_date"),
    denominator: Literal["population", "started"] = "population",
    include_data_date: bool = False,
    in_progress: Literal["finish", "start"] = "finish",
) -> RuleOutput:
    """Progress dates on the wrong side of the data date.
    Counts: with invalid dates / checked

    Progress dates on the wrong side of the data date.

    ``forecast``: incomplete activity scheduled before the data date (not-started start or
    finish; in-progress remaining finish, or remaining start with ``in_progress = "start"``,
    P6 Professional's reading). ``actual``: actual start or finish after it.
    ``denominator``: the population, or ``started`` (activities with an actual start, as
    DECM 06A506a). ``include_data_date`` also flags a forecast exactly on the data date:
    off by default, because P6's data date is the first instant of remaining work (DECM's
    "on or before the status date", the end of the reported period, is "before" it).
    """
    data_date = context.snapshot.data_date
    population = activities(context, exclude)
    if data_date is None:
        return RuleOutput(note="no data date")
    if denominator not in ("population", "started"):
        raise ValueError("invalid_dates.denominator must be 'population' or 'started'")
    if in_progress not in ("finish", "start"):
        raise ValueError("invalid_dates.in_progress must be 'finish' or 'start'")
    before = np.less_equal if include_data_date else np.less
    is_open = ~population["is_complete"]
    early_start, early_finish = forecast_dates(population)  # the same reading as the model's Start / Finish
    if in_progress == "start":
        forecast = is_open & before(early_start, data_date)  # a finish before the data date has its start before it too
    else:
        not_started_early = (~population["is_started"]) & before(early_start, data_date)
        forecast = is_open & (not_started_early | before(early_finish, data_date))
    actual = (population["act_start_date"] > data_date) | (population["act_end_date"] > data_date)
    forecast, actual = forecast.fillna(False).astype(bool), actual.fillna(False).astype(bool)
    hit = {"forecast": forecast, "actual": actual, "both": forecast | actual}[kind]
    reason = np.select(
        [forecast & actual, forecast],
        ["forecast before and actual after data date", "forecast before data date"],
        default="actual after data date",
    )
    flagged = population[hit]
    total = int(population["act_start_date"].notna().sum()) if denominator == "started" else len(population)
    reasons = pd.Series(reason, index=population.index)[hit]
    return RuleOutput(flagged_activities(flagged, reason=reasons), len(flagged), total)


@rule("no_resource", "%")
def no_resource(context, exclude: Names = ("complete", "loe", "milestones"), expenses_count: bool = True) -> RuleOutput:
    """Activities with no resource assignment.
    Counts: without resources / checked

    Activities with no resource assignment (and, if ``expenses_count``, no expense).
    """
    population = activities(context, exclude)
    has_cost = population["has_resource"] | (population["has_expense"] if expenses_count else False)
    flagged = population[~has_cost]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population))


# --- baseline ---------------------------------------------------------------------------------


def _with_baseline(context, population: pd.DataFrame) -> pd.DataFrame:
    return population.join(context.baseline.frame[["bl_start", "bl_finish"]], on="task_code")


@rule("late_vs_baseline", "%", needs_baseline=True)
def late_vs_baseline(
    context,
    exclude: Names = ("complete", "milestones", "loe"),
    tolerance_hours: float = 0,
    no_baseline: Literal["pass", "planned"] = "pass",
) -> RuleOutput:
    """Forecast to finish after their baseline finish.
    Counts: late / checked

    Activities forecast to finish later than their baseline finish.

    P6's finish variance is working time on the activity's calendar, so a finish at
    17:00 against a baseline of 08:00 the next working morning is not late.
    ``no_baseline``: an activity with no baseline finish passes, or (``"planned"``, P6
    Professional) is late when its finish is later than its planned finish.
    """
    if no_baseline not in ("pass", "planned"):
        raise ValueError("late_vs_baseline.no_baseline must be 'pass' or 'planned'")
    population = _with_baseline(context, activities(context, exclude))
    if no_baseline == "planned":
        population["bl_finish"] = population["bl_finish"].combine_first(population["target_end_date"])
    variance_hours = context.snapshot.work_hours(population["clndr_id"], population["bl_finish"], population["finish"])
    late = variance_hours > tolerance_hours
    flagged = population[late.fillna(False).astype(bool)]
    variance_days = (variance_hours[flagged.index] / flagged["hours_per_day"]).round(2)
    extra = {"bl_finish": flagged["bl_finish"], "finish_variance_wd": variance_days}
    return RuleOutput(flagged_activities(flagged, **extra), len(flagged), len(population))


@rule("missed_tasks", "%", needs_baseline=True)
def missed_tasks(context, exclude: Names = ("loe", "milestones")) -> RuleOutput:
    """Due by the data date and not finished on time.
    Counts: missed / due by the data date

    DCMA-EA PAM 200.1 4.11: of the tasks due by the data date, those finishing after their baseline finish.

    Base = tasks with both a baseline start and finish. Due = baseline finish on or before the data
    date. Missed = actual finish (else forecast finish) on a later date than the baseline finish, so a
    completed task stays in and an unfinished one forecast past its baseline finish is missed.
    UNRESOLVED: the pamphlet's Finish Variance is working time; the calendar date is compared here, as
    an actual on a non-working day is still late.
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no data date")
    population = _with_baseline(context, activities(context, exclude))
    due = population[population["bl_start"].notna() & (population["bl_finish"] <= data_date)]
    late = due["finish"].dt.normalize() > due["bl_finish"].dt.normalize()
    flagged = due[late.fillna(False).astype(bool)]
    return RuleOutput(flagged_activities(flagged, bl_finish=flagged["bl_finish"]), len(flagged), len(due))


@rule("bei", "ratio", needs_baseline=True)
def bei(
    context,
    exclude: Names = ("loe", "milestones"),
    missing_baseline: Literal["due", "ignore"] = "due",
    due_from: Literal["snapshot", "baseline"] = "snapshot",
) -> RuleOutput:
    """Due by the data date but not completed.
    Counts: completed / due by the data date

    Baseline Execution Index = activities completed / activities due by the data date.

    ``missing_baseline = "due"`` counts an activity with no baseline finish as due (P6
    EPPM); ``"ignore"`` leaves it out. ``due_from = "baseline"`` (P6 Professional) counts
    the due activities in the baseline itself, ``exclude`` applied there: an activity
    added since is never due, one deleted since still is; ``missing_baseline`` is unused.
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no data date")
    population = _with_baseline(context, activities(context, exclude))
    done = int(population["is_complete"].sum())
    if due_from == "baseline":
        baseline = context.baseline
        kept_codes = _without(baseline.snapshot.activities, data_date, exclude)["task_code"]
        kept = baseline.frame[baseline.frame.index.isin(kept_codes)]
        due_codes = set(kept.index[kept["bl_finish"] <= data_date])
        late = population[population["task_code"].isin(due_codes) & ~population["is_complete"]]
        gone = len(due_codes - set(context.snapshot.activities["task_code"]))
        note = f"{done} completed / {len(due_codes)} due in the baseline" + (
            f"; {gone} of them no longer in the schedule" if gone else ""
        )
        due_count = len(due_codes)
        index = done / due_count if due_count else None
        return RuleOutput(flagged_activities(late, bl_finish=late["bl_finish"]), done, due_count, index, note)
    if due_from != "snapshot":
        raise ValueError("bei.due_from must be 'snapshot' or 'baseline'")
    is_due = population["bl_finish"] <= data_date
    if missing_baseline == "due":
        is_due |= population["bl_finish"].isna()
    elif missing_baseline != "ignore":
        raise ValueError("bei.missing_baseline must be 'due' or 'ignore'")
    due = population[is_due]
    late = due[~due["is_complete"]]
    without_baseline = int(population["bl_finish"].isna().sum())
    note = f"{done} completed / {len(due)} due" + (
        f"; {without_baseline} without baseline finish" if without_baseline else ""
    )
    index = done / len(due) if len(due) else None
    return RuleOutput(flagged_activities(late, bl_finish=late["bl_finish"]), done, len(due), index, note)


# --- critical path -------------------------------------------------------------------------------


def _finish_driver(context) -> pd.Series | None:
    tasks = context.snapshot.activities
    open_tasks = tasks[~tasks["is_complete"] & ~tasks["is_loe"] & tasks["finish"].notna()]
    return None if open_tasks.empty else open_tasks.loc[open_tasks["finish"].idxmax()]


@rule("cpli", "ratio")
def cpli(context) -> RuleOutput:
    """Critical Path Length Index = (CPL + TF) / CPL.

    CPL = working days from the data date to the forecast finish, TF = total float of the
    activity that sets the finish, both on the project calendar. TF is the schedule's:
    P6 measures it against the project's Must Finish By date, the contract finish in
    DCMA's terms. Without that date the last activity's float is 0 and the index 1.0
    whatever the schedule, so the check is n/a until the date is set in P6.
    """
    snapshot = context.snapshot
    last_task = _finish_driver(context)
    if snapshot.data_date is None:
        return RuleOutput(note="no data date")
    if last_task is None:
        return RuleOutput(note="no remaining work")
    if snapshot.options.get("must_finish_by") is None:
        return RuleOutput(note="no Must Finish By date (P6: Project > Dates): the float would be 0 by construction")
    calendar = snapshot.calendar()
    length = calendar.working_days(snapshot.data_date, last_task["finish"])
    float_hours = float(last_task["total_float_hr_cnt"]) if pd.notna(last_task["total_float_hr_cnt"]) else 0.0
    total_float = float_hours / calendar.hours_per_day if calendar.hours_per_day else 0.0
    if length <= 0:
        return RuleOutput(note="critical path length is 0")
    return RuleOutput(
        value=(length + total_float) / length,
        note=f"CPL {length:g} wd to {last_task['task_code']}, total float {total_float:g} wd",
    )


@rule("critical_path_test", "pass/fail")
def critical_path_test(context, delay_days: float = 600) -> RuleOutput:
    """Add ``delay_days`` to the first open critical activity; the finish must slip as much."""
    from .cpm import critical_path_test as run

    if context.snapshot.data_date is None:
        return RuleOutput(note="no data date")
    if _finish_driver(context) is None:
        return RuleOutput(note="no remaining work")
    result = run(context.snapshot, delay_days)
    return RuleOutput(value=1.0 if result.passed else 0.0, note=result.note, flagged=pd.DataFrame(result.blocking))


# --- integrity: is the file what P6 would calculate? ------------------------------------------


@rule("recalculated", "%")
def recalculated(
    context,
    fields: Names = ("early_start_date", "early_end_date", "late_start_date", "late_end_date", "total_float_hr_cnt"),
) -> RuleOutput:
    """Stored dates differ from the recalculation.
    Counts: different / open activities

    Open activities whose stored dates or float differ from a P6-style recalculation.

    A difference means the file was edited after the last F9, or uses a scheduling
    feature xerscope does not model (see analysis/cpm.py). Exact to the minute.
    """
    from .cpm import CycleError, compare_with_stored

    try:
        comparison = compare_with_stored(context.snapshot)
    except CycleError as exc:
        return RuleOutput(note=f"cannot schedule: {exc}")
    comparison = comparison[comparison["field"].isin(fields) & comparison["stored"].notna()]
    if comparison.empty:
        return RuleOutput(numerator=0, denominator=0, note="no stored dates to compare")
    differences: dict[str, list[str]] = {}
    columns = ["task_code", "field", "stored", "computed", "agree"]
    for task_code, field_name, stored, computed, agrees in comparison[columns].itertuples(index=False):
        if not agrees:
            differences.setdefault(task_code, []).append(f"{field_name}: {stored} -> {computed}")
    tasks = context.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    flagged = tasks.loc[sorted(differences)].reset_index()
    texts = ["; ".join(differences[task_code]) for task_code in flagged["task_code"]]
    different_values = sum(len(found) for found in differences.values())
    return RuleOutput(
        flagged_activities(flagged, differences=texts),
        len(differences),
        comparison["task_code"].nunique(),
        note=f"{len(comparison) - different_values} of {len(comparison)} stored values reproduced",
    )


def _out_of_sequence_by_decm(context, population: pd.DataFrame, tasks: pd.DataFrame) -> RuleOutput:
    """Relationships into incomplete work whose dates contradict their type (DECM 06A212a)."""
    successors = population[~population["is_complete"]].drop_duplicates("task_code").set_index("task_code")
    relationships = context.snapshot.relationships
    links = relationships[
        relationships["succ_code"].isin(successors.index) & relationships["pred_code"].isin(tasks.index)
    ].copy()
    if successors.empty:
        return RuleOutput(flagged_relationships(links), 0, 0)
    pred_start, pred_finish = links["pred_code"].map(tasks["start"]), links["pred_code"].map(tasks["finish"])
    succ_start, succ_finish = links["succ_code"].map(successors["start"]), links["succ_code"].map(successors["finish"])
    out_of_sequence = np.select(
        [links["type"] == "FS", links["type"] == "SS", links["type"] == "FF", links["type"] == "SF"],
        [succ_start < pred_finish, succ_start < pred_start, succ_finish < pred_finish, succ_finish < pred_start],
        default=False,
    )
    flagged = links[out_of_sequence.astype(bool)]
    names = tasks["task_name"]
    shown = flagged_relationships(
        flagged.assign(pred_name=flagged["pred_code"].map(names), succ_name=flagged["succ_code"].map(names))
    )
    for column, dates in (
        ("pred_start", pred_start),
        ("pred_finish", pred_finish),
        ("succ_start", succ_start),
        ("succ_finish", succ_finish),
    ):
        shown[column] = dates[flagged.index]
    return RuleOutput(shown, len(flagged), len(links))


def _out_of_sequence_by_actuals(context, population: pd.DataFrame, tasks: pd.DataFrame) -> RuleOutput:
    """Started activities whose predecessor had not finished (FS) or started (SS) at their actual start."""
    started = population[population["is_started"]].drop_duplicates("task_code").set_index("task_code")
    relationships = context.snapshot.relationships
    relationships = relationships[
        relationships["succ_code"].isin(started.index) & relationships["pred_code"].isin(tasks.index)
    ]
    ahead_of: dict[str, list[str]] = {}
    columns = ["pred_code", "succ_code", "type"]
    for predecessor, successor, link_type in relationships[columns].itertuples(index=False):
        start = started.at[successor, "act_start_date"]
        predecessor_finish = tasks.at[predecessor, "act_end_date"]
        predecessor_start = tasks.at[predecessor, "act_start_date"]
        finish_after = link_type == "FS" and (pd.isna(predecessor_finish) or predecessor_finish > start)
        start_after = link_type == "SS" and (pd.isna(predecessor_start) or predecessor_start > start)
        if finish_after or start_after:
            ahead_of.setdefault(successor, []).append(f"{predecessor} ({link_type})")
    flagged = started.loc[sorted(ahead_of)].reset_index()
    texts = [", ".join(ahead_of[task_code]) for task_code in flagged["task_code"]]
    return RuleOutput(flagged_activities(flagged, ahead_of=texts), len(flagged), len(started))


@rule("out_of_sequence", "count")
def out_of_sequence(context, exclude: Names = ("loe",), method: Literal["actuals", "decm"] = "actuals") -> RuleOutput:
    """Progressed out of logic sequence.
    Counts: out of sequence /

    Progress out of logic sequence.

    ``method = "actuals"``: started activities whose FS predecessor had not finished, or
    SS predecessor not started, at their actual start (P6 lists them in its scheduling
    log). Counts activities.

    ``method = "decm"`` (DECM 06A212a): counts relationships into incomplete work where
    FS: (S.AS or S.FS) < P.FF; SS: (S.AS or S.FS) < P.FS; FF: (S.AF or S.FF) < P.FF;
    SF: (S.AF or S.FF) < P.FS. Actual dates first, else forecast; lags are not added,
    so a lead that lets work overlap is also an out-of-sequence condition.
    """
    population = activities(context, exclude)
    tasks = context.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    if method == "decm":
        return _out_of_sequence_by_decm(context, population, tasks)
    if method != "actuals":
        raise ValueError("out_of_sequence.method must be 'actuals' or 'decm'")
    return _out_of_sequence_by_actuals(context, population, tasks)


def _describe_differences(group: pd.DataFrame) -> str:
    """One assignment's stored-vs-recalculated fields as 'field: stored -> computed; ...'."""
    pairs = group[["field", "stored", "computed"]].itertuples(index=False)
    return "; ".join(f"{field_name}: {stored} -> {computed}" for field_name, stored, computed in pairs)


@rule("assignments_recalculated", "%")
def assignments_recalculated(context) -> RuleOutput:
    """Assignment dates differ from the recalculation.
    Counts: different / open assignments

    Open resource assignments whose stored remaining early/late dates differ from a recalculation.

    Same idea as ``recalculated``, on TASKRSRC: activity dates + assignment lag, duration
    = remaining units / units per hour, on the resource's calendar for resource-dependent
    activities.
    """
    from .cpm import CycleError, compare_assignments

    try:
        comparison = compare_assignments(context.snapshot)
    except CycleError as exc:
        return RuleOutput(note=f"cannot schedule: {exc}")
    comparison = comparison[comparison["stored"].notna()]
    if comparison.empty:
        return RuleOutput(numerator=0, denominator=0, note="no stored assignment dates to compare")
    different = comparison[~comparison["agree"]]
    flagged = pd.DataFrame()
    if not different.empty:
        by_assignment = different.groupby("taskrsrc_id")
        flagged = pd.DataFrame(
            {
                "task_code": by_assignment["task_code"].first(),
                "resource": by_assignment["rsrc"].first(),
                "differences": by_assignment.apply(_describe_differences, include_groups=False),
            }
        ).reset_index()
    return RuleOutput(
        flagged,
        different["taskrsrc_id"].nunique(),
        comparison["taskrsrc_id"].nunique(),
        note=f"{len(comparison) - len(different)} of {len(comparison)} stored assignment dates reproduced",
    )


# --- DCMA DECM v8.0, Guideline 6 (schedule) -------------------------------------------------------


def _incomplete(context, loe: bool) -> pd.DataFrame:
    """DECM population: incomplete (no actual finish) tasks and milestones, LOE optional."""
    tasks = context.snapshot.activities
    population = tasks[~tasks["is_complete"]]
    return population if loe else population[~population["is_loe"]]


def _join_sorted(codes: pd.Series) -> str:
    return ", ".join(sorted(codes))


@rule("open_ends", "%")
def open_ends(context, exempt_ends: Literal["baseline", "none"] = "baseline") -> RuleOutput:
    """Open start or open finish.
    Counts: with an open start or finish / incomplete tasks and milestones

    DECM 06A204b dangling logic: incomplete non-LOE tasks and milestones with an open start or finish.

    Open start: a task whose predecessors are only FF / SF, or none; a milestone with no
    predecessor. Open finish: a task whose successors are only SS / SF, or none; a
    milestone with no successor. Started tasks are included (incomplete = no actual
    finish). ``exempt_ends``: the earliest-baseline-start activities pass the start test
    and the latest-baseline-finish ones the finish test (``baseline``; the snapshot's
    planned dates when no baseline is loaded), or ``none``.
    """
    population = _incomplete(context, loe=False)
    relationships = context.snapshot.relationships
    codes = population["task_code"]
    has_predecessor = codes.isin(relationships["succ_code"]) | population["has_external_pred"]
    has_successor = codes.isin(relationships["pred_code"]) | population["has_external_succ"]
    start_types = relationships["type"].isin(["FS", "SS"])
    finish_types = relationships["type"].isin(["FS", "FF"])
    drives_start = codes.isin(relationships.loc[start_types, "succ_code"]) | population["has_external_pred"]
    finish_drives = codes.isin(relationships.loc[finish_types, "pred_code"]) | population["has_external_succ"]
    is_milestone = population["is_milestone"]
    open_start = np.where(is_milestone, ~has_predecessor, ~drives_start)
    open_finish = np.where(is_milestone, ~has_successor, ~finish_drives)
    note = ""
    if exempt_ends == "baseline":
        # the project's first start and last finish are looked up over every activity,
        # finished ones included: once the first activity is done, the next one in line
        # is not the project start
        frame = (context.baseline or Baseline.planned(context.snapshot)).frame
        all_starts, all_finishes = frame["bl_start"], frame["bl_finish"]
        starts, finishes = codes.map(all_starts), codes.map(all_finishes)
        note = (
            "first/last by baseline dates"
            if context.baseline is not None
            else "no baseline: first/last by planned dates"
        )
        open_start &= ~(starts == all_starts.min()).fillna(False).to_numpy(bool)
        open_finish &= ~(finishes == all_finishes.max()).fillna(False).to_numpy(bool)
    elif exempt_ends != "none":
        raise ValueError("open_ends.exempt_ends must be 'baseline' or 'none'")
    reason = np.select(
        [open_start & open_finish, open_start, open_finish],
        ["open start and finish", "open start (no FS/SS predecessor)", "open finish (no FS/FF successor)"],
        default="",
    )
    hit = reason != ""
    flagged = population[hit]
    return RuleOutput(flagged_activities(flagged, reason=reason[hit]), len(flagged), len(population), note=note)


@rule("lagged_activities", "%")
def lagged_activities(
    context, loe: bool = True, sign: Literal["positive", "negative", "any"] = "positive"
) -> RuleOutput:
    """Activities with a lag on a predecessor.
    Counts: with a lag / incomplete tasks and milestones

    DECM 06A205a: incomplete tasks and milestones with at least one lag (``sign``:
    positive lags, negative = leads, or any non-zero lag) in their predecessor logic.
    """
    population = _incomplete(context, loe)
    relationships = context.snapshot.relationships
    lag_hours = relationships["lag_hr"].fillna(0)
    has_lag = {"positive": lag_hours > 0, "negative": lag_hours < 0, "any": lag_hours != 0}[sign]
    lagged_from = relationships[has_lag].groupby("succ_code")["pred_code"].agg(_join_sorted)
    flagged = population[population["task_code"].isin(lagged_from.index)]
    return RuleOutput(
        flagged_activities(flagged, lagged_from=flagged["task_code"].map(lagged_from)), len(flagged), len(population)
    )


@rule("summary_logic", "count")
def summary_logic(context) -> RuleOutput:
    """Summary activities carrying logic.
    Counts: with logic /

    DECM 06A208a: summary activities (P6 WBS summary) with a predecessor or successor.
    """
    tasks = context.snapshot.tasks
    summaries = tasks[tasks["is_wbs_summary"]]
    relationships = context.snapshot.relationships
    has_logic = summaries["task_code"].isin(relationships["pred_code"]) | summaries["task_code"].isin(
        relationships["succ_code"]
    )
    flagged = summaries[has_logic]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(summaries))


@rule("loe_successors", "%")
def loe_successors(context) -> RuleOutput:
    """LOE driving discrete work.
    Counts: with a discrete successor / incomplete LOE

    DECM 06A210a: incomplete LOE activities with a discrete (non-LOE) successor.
    """
    tasks = context.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    population = _incomplete(context, loe=True)
    population = population[population["is_loe"]]
    relationships = context.snapshot.relationships
    from_loe = relationships[
        relationships["pred_code"].isin(population["task_code"]) & relationships["succ_code"].isin(tasks.index)
    ]
    discrete = from_loe[~_flag_of(from_loe["succ_code"], tasks["is_loe"])]
    successors = discrete.groupby("pred_code")["succ_code"].agg(_join_sorted)
    flagged = population[population["task_code"].isin(successors.index)]
    return RuleOutput(
        flagged_activities(flagged, drives=flagged["task_code"].map(successors)), len(flagged), len(population)
    )


@rule("missing_baseline", "%", needs_baseline=True)
def missing_baseline(context) -> RuleOutput:
    """Missing a baseline start or finish.
    Counts: without baseline dates / tasks and milestones

    DECM 06A501a: tasks and milestones without a baseline start or finish (summaries excluded).
    """
    population = _with_baseline(context, context.snapshot.activities)
    flagged = population[population["bl_start"].isna() | population["bl_finish"].isna()]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population))


def _update_before(context, period_days: int):
    """The latest update at least ``period_days`` older than the snapshot (0: the previous
    one), or None. DECM compares status periods, which are monthly on most contracts."""
    store, snapshot = context.store, context.snapshot
    if period_days <= 0:
        return context.previous
    if store is None or snapshot.data_date is None:
        return None
    cutoff = snapshot.data_date - pd.Timedelta(days=period_days)
    earlier = [update for update in store if update.data_date is not None and update.data_date <= cutoff]
    return earlier[-1] if earlier else None


@rule("actuals_changed", "%")
def actuals_changed(context, field: Literal["start", "finish"] = "start", period_days: int = 28) -> RuleOutput:
    """Actual date changed since the previous update.
    Counts: changed / with that actual date

    DECM 06A504a / 06A504b: actual start (or finish) different from the previous period's.

    X = activities whose actual date differs from (or was removed since) the one the
    update ``period_days`` earlier reported; Y = activities with that actual date in either
    update, so a removed date counts on both sides and the share never exceeds 100 %.
    ``period_days = 0`` compares with the previous update whatever its date.
    """
    column = {"start": "act_start_date", "finish": "act_end_date"}[field]
    previous = _update_before(context, period_days)
    if previous is None:
        return RuleOutput(
            note="needs the previous update" if period_days <= 0 else f"needs an update {period_days} days older"
        )
    now = context.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    before = previous.activities.drop_duplicates("task_code").set_index("task_code")[column].dropna()
    common = before.index.intersection(now.index)
    changed = [code for code in common if now.at[code, column] != before[code]]
    flagged = now.loc[changed].reset_index()
    shown = flagged_activities(flagged, previous=[before[code] for code in changed], now=flagged.get(column))
    dated = set(now.index[now[column].notna()]) | set(common)
    return RuleOutput(shown, len(flagged), len(dated))


@rule("progress_actuals", "%")
def progress_actuals(context, kind: Literal["in_progress", "complete"] = "in_progress") -> RuleOutput:
    """Progress without the matching actual.
    Counts: without the actual date / showing that progress

    DECM 06A505a / 06A505b: progress without the matching actual date.

    ``in_progress``: % complete > 0 (or status in progress) but no actual start, of the
    activities showing progress. ``complete``: 100 % (or status complete) but no actual
    finish, of the activities at 100 %.
    """
    tasks = context.snapshot.activities
    if kind == "in_progress":
        population = tasks[(tasks["pct_complete"] > 0) | tasks["is_started"]]
        flagged = population[population["act_start_date"].isna()]
    elif kind == "complete":
        population = tasks[(tasks["pct_complete"] >= 100) | tasks["is_complete"]]
        flagged = population[population["act_end_date"].isna()]
    else:
        raise ValueError("progress_actuals.kind must be 'in_progress' or 'complete'")
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population))


def _start_near_data_date(snapshot, frame: pd.DataFrame, window_wd: float) -> pd.Series:
    """True where the forecast start is within ``window_wd`` working days after the data date."""
    data_dates = pd.Series(snapshot.data_date, index=frame.index)
    hours = snapshot.work_hours(frame["clndr_id"], data_dates, frame["start"])
    return (hours >= 0) & (hours <= window_wd * frame["hours_per_day"])


@rule("riding_status_date", "%")
def riding_status_date(
    context, window_wd: float = 3, remaining_tolerance_wd: float = 2, period_days: int = 28
) -> RuleOutput:
    """Forecasts riding the status date.
    Counts: riding the status date / checked

    DECM 06A506c: forecasts riding the status date over two consecutive (monthly) updates.

    Compared with the latest update at least ``period_days`` older. A not-started activity
    rides when its forecast start is within ``window_wd`` working days of the data date in
    both; a started one when its remaining duration has moved by no more than
    ``remaining_tolerance_wd`` (its finish slides with the data date). Y = incomplete
    activities.
    """
    previous = _update_before(context, period_days)
    if previous is None:
        return RuleOutput(note=f"needs an update {period_days} days older")
    population = _incomplete(context, loe=False)
    previous_tasks = previous.activities.drop_duplicates("task_code").set_index("task_code")
    population = population[population["task_code"].isin(previous_tasks.index)]

    start_now = _start_near_data_date(context.snapshot, population, window_wd) & ~population["is_started"]
    before = previous_tasks.loc[population["task_code"]].set_index(population.index)
    start_before = _start_near_data_date(previous, before, window_wd) & ~before["is_started"]
    remaining_change = (population["remaining_d"] - before["remaining_d"]).abs()
    both_started = population["is_started"] & before["is_started"]
    finish_rides = both_started & (remaining_change <= remaining_tolerance_wd)
    riding = ((start_now & start_before) | finish_rides).fillna(False).astype(bool)
    flagged = population[riding]
    why = np.where(
        finish_rides[riding],
        "remaining duration unchanged",
        f"start within {window_wd:g} wd of the data date in both updates",
    )
    return RuleOutput(
        flagged_activities(flagged, reason=why),
        len(flagged),
        len(population),
        note=f"vs update of {previous.data_date:%Y-%m-%d}",
    )
