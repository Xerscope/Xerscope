"""Rule registry, and the generic parameterised rules for your own standard.

The built-in standards (P6, DCMA, DECM, INTEGRITY) are one explicit function per check
(``p6/``, ``dcma/``, ``decm/``, ``integrity.py``); the TOML only gives each its target.
The rules below take parameters instead, so a company standard
(``standards/custom-template.toml``) can pick a rule, set its parameters and a target:
``Rule.params`` / ``Rule.validate``, ``EXEMPT`` and ``ALLOWED`` exist for them alone.
The helpers after the generic rules (``share_of_type``, ``late_output``, ...) are shared
with the explicit checks.

Each rule returns a :class:`RuleOutput`; the profile's target turns it into pass/fail.
Populations always exclude WBS-summary rows (``Snapshot.tasks``).

Docstring convention. ``explain.py`` words a result from the rule's docstring:

    Constrained tasks.                    <- title (label of the flagged list)
    Counts: constrained / checked              <- numerator word / denominator word
    Excludes: completed tasks.            <- population lines, zero or more, shown as written
    Constraint types: A, B,
        continued on an indented line.         <- an indented line continues the one above

    Everything after the first blank line is the method text (what ``--rules`` prints).

A docstring without a ``Counts:`` second line is all method text. Rules whose population
depends on their parameters (the generic ones) leave out the population lines:
``explain.py`` writes those from the parameters.
"""

from __future__ import annotations

import inspect
import math
import operator
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from ..xer.calendar import hours_to_days
from ..xer.model import CONSTRAINT, forecast_dates
from .baseline import EV_COLS, Baseline
from .cpm import critical_path_test
from .populations import (  # noqa: F401 - ACTIVITY_COLS, LINK_COLS re-exported
    ACTIVITY_COLS,
    EXCLUSIONS,
    LINK_COLS,
    Funnel,
    activity_funnel,
    actual_after,
    as_flag,
    at_grain,
    constrained_by,
    finish_driver,
    flagged_activities,
    flagged_relationships,
    has_driving_predecessor,
    has_driving_successor,
    invalid_date_reason,
    lag_flagged,
    open_end_reason,
    with_baseline,
    without,
)

Unit = Literal["%", "ratio", "count", "days", "pass/fail"]
Names = Sequence[str]  # TOML gives lists, defaults are tuples
Op = Literal["<", "<=", ">", ">="]
BandOp = Literal["<", "<=", ">", ">=", "between"]  # "between": value <= measured <= value_max
LinkPop = Literal["all", "not_both_complete", "succ_incomplete"]
Listed = Literal["others", "of_type"]  # which relationships a type rule lists: the others, or those of the type


@dataclass
class AnalysisContext:
    snapshot: Snapshot
    store: SnapshotStore | None = None
    baseline: Baseline | None = None


@dataclass
class RuleOutput:
    flagged: pd.DataFrame = field(default_factory=pd.DataFrame)
    numerator: int | None = None
    denominator: int | None = None
    value: float | None = None  # set by ratio / pass-fail rules; % and counts are derived
    note: str = ""
    checked: pd.DataFrame | None = None  # the rows behind the denominator
    funnel: Funnel | None = None  # how ``checked`` was cut from the file, step by step
    counted: pd.DataFrame | None = None  # the rows behind the numerator, when they are not ``flagged``
    status: Literal["info"] | None = None  # "info" when the rule reports a value for review, not against the target


COMPARE = {"<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge, "==": operator.eq}


@dataclass(frozen=True)
class Rule:
    name: str
    fn: Callable[..., RuleOutput]
    unit: Unit
    doc: str  # the method text: the docstring without its header
    needs_baseline: bool = False
    links: bool = False  # True when the flagged rows are relationships, not activities
    title: str = ""  # label of the flagged list, from the docstring header
    numerator_word: str = "flagged"
    denominator_word: str = "checked"
    population: tuple[str, ...] = ()  # fixed population lines, from the docstring header

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
        _check_band(self.name, {**self.params, **params})

    def _check_vocabulary(self, params: dict) -> None:
        for key in sorted(set(params) & set(ALLOWED)):
            bad = set(params[key]) - ALLOWED[key]
            if bad:
                what = "unknown" if key == "types" else "unknown value(s)"
                raise ValueError(f"{self.name}.{key}: {what} {sorted(bad)}; allowed {sorted(ALLOWED[key])}")


def is_read(name: str, params: dict) -> bool:
    """Whether a rule reads its parameter ``name`` with these ``params``: ``value_max`` bounds a band
    and nothing else (``_within``)."""
    return name != "value_max" or params.get("op") == "between"


def _check_band(rule_name: str, params: dict) -> None:
    """``op = "between"`` needs ``value_max`` at or above ``value``: reversed bounds flag nothing and
    would pass silently."""
    if params.get("op") == "between" and params["value_max"] < params["value"]:
        low, high = params["value"], params["value_max"]
        raise ValueError(f"{rule_name}: op 'between' needs value_max ({high}) >= value ({low})")


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
        if not math.isfinite(value):  # TOML nan / inf: every comparison with it is False, a silent pass
            raise ValueError(f"{where}: expected a finite number, got {value!r}")
    elif hint == Names and (isinstance(value, str) or not all(isinstance(name, str) for name in value)):
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


def rule(name: str, unit: Unit, needs_baseline: bool = False, links: bool = False):
    def register(function):
        fields = read_docstring(inspect.getdoc(function) or "")
        RULES[name] = Rule(name, function, unit, needs_baseline=needs_baseline, links=links, **fields)
        return function

    return register


# --- populations -------------------------------------------------------------------------


# Each closed vocabulary is declared once: key -> label for explain (exclusions: populations.EXCLUSIONS).
EXEMPT: dict[str, str] = {
    "started": "started tasks",
    "start_milestone": "start milestones",
    "finish_milestone": "finish milestones",
    "project_start": "the project's first task",
    "project_finish": "the project's last task",
    "single_project_start": "the project's first task, when it is the only one on the earliest start",
    "single_project_finish": "the project's last task, when it is the only one on the latest finish",
}
ALLOWED: dict[str, set[str]] = {
    "exclude": set(EXCLUSIONS),
    "pred_exempt": set(EXEMPT),
    "succ_exempt": set(EXEMPT),
    "types": set(CONSTRAINT),
}


def activities(context: AnalysisContext, exclude: Names) -> pd.DataFrame:
    return without(context.snapshot.activities, context.snapshot.data_date, exclude)


def activities_funnel(context: AnalysisContext, exclude: Names) -> Funnel:
    """The tasks of the file less each ``exclude`` key, one step per key, in the order given: the
    same rows as ``activities``, with what each step took out. The source of every step is xerscope's
    (a custom rule has no Oracle or DCMA page of its own for its exclusions)."""
    funnel = activity_funnel(context.snapshot)
    for key in exclude:
        funnel.exclude(key, "xerscope")
    return funnel


def link_funnel(
    context: AnalysisContext, links: str, exclude_loe: bool = False, exclude: Names = (), source: str = "model"
) -> Funnel:
    """Relationships into a scheduled task, with both names, narrowed by ``links`` (see LinkPop), step by
    step; ``source`` is the text the ``links`` step follows."""
    snapshot = context.snapshot
    tasks = snapshot.activities.set_index("task_code")
    funnel = Funnel(snapshot.relationships)
    funnel.keep("into a task", "model", lambda rows: rows["succ_code"].isin(tasks.index))

    def done(rows: pd.DataFrame, end: str) -> pd.Series:
        return as_flag(rows[end].map(tasks["is_complete"]))

    if links == "not_both_complete":
        funnel.keep("not both ends complete", source, lambda rows: ~(done(rows, "pred_code") & done(rows, "succ_code")))
    elif links == "succ_incomplete":
        funnel.keep("successor not complete", source, lambda rows: ~done(rows, "succ_code"))
    # DCMA PAM 200.1 section 4.0 reading: a link counts when its successor is a retained task; the
    # predecessor may itself be excluded (a link out of a milestone counts). One step per exclusion,
    # so the audit page shows what each one removed.
    for exclusion_key in exclude:
        exclusion = EXCLUSIONS[exclusion_key]
        excluded_task_codes = snapshot.activities.loc[
            as_flag(exclusion.removes(snapshot.activities, snapshot.data_date)), "task_code"
        ]
        # ``excluded`` binds this iteration's codes; the predicate is still called with the rows alone
        # (mypy cannot infer a lambda that has a defaulted second parameter)
        funnel.keep(
            f"successor {exclusion.label}",
            source,
            lambda links, excluded=excluded_task_codes: ~links["succ_code"].isin(excluded),  # type: ignore[misc]
        )
    if exclude_loe:
        loe = tasks["is_loe"]
        funnel.keep(
            "no level-of-effort end",
            source,
            lambda rows: ~(as_flag(rows["pred_code"].map(loe)) | as_flag(rows["succ_code"].map(loe))),
        )
    names = tasks["task_name"]
    rows = funnel.rows
    funnel.rows = rows.assign(pred_name=rows["pred_code"].map(names), succ_name=rows["succ_code"].map(names))
    return funnel


def _project_ends(context: AnalysisContext) -> tuple[set[str], set[str]]:
    """Tasks at the project's start (no predecessor, earliest start) and finish."""
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
    """One boolean mask per EXEMPT key: the tasks that pass the missing-logic test."""
    masks = {
        "started": population["is_started"],
        "start_milestone": population["is_start_milestone"],
        "finish_milestone": population["is_milestone"] & ~population["is_start_milestone"],
        "project_start": population["task_code"].isin(start_ids),
        "project_finish": population["task_code"].isin(finish_ids),
        "single_project_start": population["task_code"].isin(start_ids) & (len(start_ids) == 1),
        "single_project_finish": population["task_code"].isin(finish_ids) & (len(finish_ids) == 1),
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

    Tasks without a predecessor or a successor (open ends).

    ``pred_exempt`` / ``succ_exempt`` pass one side for: started, start_milestone,
    finish_milestone, project_start, project_finish (every task on the earliest start or the
    latest finish), single_project_start, single_project_finish (that task only when it is
    alone there: two tasks sharing the date are both flagged). ``external_passes`` counts links to
    other projects. ``dangling`` also flags a start not driven by any FS/SS predecessor
    or a finish that drives no FS/FF successor.
    """
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
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
        codes = population["task_code"]
        dangling_start = (
            has_predecessor
            & ~has_driving_predecessor(codes, relationships)
            & ~population["is_started"]
            & ~population["has_external_pred"]
            & ~exempt_mask["project_start"]
        )
        dangling_finish = (
            has_successor
            & ~has_driving_successor(codes, relationships)
            & ~population["has_external_succ"]
            & ~exempt_mask["project_finish"]
        )
        reason = reason.mask((reason == "") & dangling_start, "dangling start (no FS/SS predecessor)")
        reason = reason.mask((reason == "") & dangling_finish, "dangling finish (no FS/FF successor)")
    flagged = population[reason != ""]
    return RuleOutput(
        flagged_activities(flagged, reason=reason[reason != ""]),
        len(flagged),
        len(population),
        checked=population,
        funnel=funnel,
    )


@rule("dangling", "%")
def dangling(context, end: Literal["start", "finish"] = "finish", exclude: Names = ("complete",)) -> RuleOutput:
    """Logic that does not drive the task.
    Counts: dangling / checked

    Tasks with logic on one end that does not drive it.

    ``end = "start"``: has predecessors but none FS or SS (the start floats free).
    ``end = "finish"``: has successors but none FS or FF (the finish drives nothing).
    Tasks with no logic at all on that end are left to ``missing_logic``.
    """
    funnel = activities_funnel(context, exclude)
    if end == "start":
        funnel.exclude("started", "xerscope")
    population = funnel.rows
    relationships = context.snapshot.relationships
    if end == "start":
        has_logic = population["task_code"].isin(relationships["succ_code"])
        driving = has_driving_predecessor(population["task_code"], relationships)
    else:
        has_logic = population["task_code"].isin(relationships["pred_code"])
        driving = has_driving_successor(population["task_code"], relationships)
    flagged = population[has_logic & ~driving]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population), checked=population, funnel=funnel)


@rule("lag", "%", links=True)
def lag(
    context,
    op: Op = ">",
    value: float = 0,
    unit: Literal["hours", "days", "project_pct"] = "hours",
    links: LinkPop = "succ_incomplete",
    exclude_loe: bool = False,
    exclude: Names = (),
) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / relationships checked

    Relationships whose lag compares to ``value`` with ``op`` (<, >, <=, >=).

    Negative = lead (``op = "<"``, value 0); positive lag (``">"``, 0); long lag
    (``">"``, 352 hours). ``unit``: hours, or days on the lag calendar, or ``project_pct``:
    ``value`` is a percentage of the project's working hours (planned start to forecast finish
    on the project's default calendar) and the lag is compared in hours; a project without
    those dates gives no value.
    """
    funnel = link_funnel(context, links, exclude_loe, exclude)
    relationships = funnel.rows
    column, limit = _lag_limit(context.snapshot, unit, value)
    if math.isnan(limit):
        return RuleOutput(note="no planned start or forecast finish: the project's working hours are unknown")
    flagged = lag_flagged(relationships, COMPARE[op], limit, column)
    return RuleOutput(
        flagged_relationships(flagged), len(flagged), len(relationships), checked=relationships, funnel=funnel
    )


def _lag_limit(snapshot: Snapshot, unit: str, value: float) -> tuple[str, float]:
    """The lag column to read and the limit to compare it with, in that column's unit: ``value``
    itself in hours or days, or ``value`` % of the project's working hours (NaN without dates)."""
    if unit == "project_pct":
        return "lag_hr", value / 100 * snapshot.project_work_hours()
    return {"hours": "lag_hr", "days": "lag_d"}[unit], value


@rule("relationship_type", "%", links=True)
def relationship_type(
    context,
    type: Literal["FS", "SS", "FF", "SF"] = "FS",  # noqa: A002  the key a standard's TOML writes
    links: LinkPop = "succ_incomplete",
    exclude_loe: bool = False,
    exclude: Names = (),
    zero_lag: bool = False,
    listed: Listed = "others",
) -> RuleOutput:
    """Relationships of another type.
    Counts: of the required type / relationships checked

    Share of relationships of ``type`` (value), listing the others. ``zero_lag`` counts a
    relationship only when its lag is zero as well (blank = 0): "Finish-Start with 0d lag".
    ``listed = "of_type"`` lists the relationships of the type instead, for a type that is
    forbidden ("no Start-Finish").
    """
    funnel = link_funnel(context, links, exclude_loe, exclude)
    out = share_of_type(funnel.rows, type, zero_lag, listed)
    out.funnel = funnel
    return out


# --- constraints, float, duration ----------------------------------------------------------


@rule("constraints", "%")
def constraints(
    context, types: Names = (), exclude: Names = ("complete",), ignore_start_when_started: bool = True
) -> RuleOutput:
    """Constrained tasks.
    Counts: constrained / checked

    Tasks with a primary or secondary constraint in ``types`` (P6 codes, e.g. CS_MANDSTART).
    """
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
    flagged = population[constrained_by(population, types, ignore_start_when_started)]
    extra = {"constraint2": flagged["cstr_type2"].map(CONSTRAINT)}
    return RuleOutput(
        flagged_activities(flagged, **extra), len(flagged), len(population), checked=population, funnel=funnel
    )


@rule("float", "%")
def total_float(
    context,
    op: BandOp = ">",
    value: float = 44,
    unit: Literal["hours", "days"] = "days",
    exclude: Names = ("complete",),
    value_max: float = 0,
) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked

    Tasks whose total float compares to ``value`` (hours as stored, or working days).
    ``op = "between"`` flags a float from ``value`` to ``value_max``, both included.
    """
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
    column = {"hours": "total_float_hr_cnt", "days": "total_float_d"}[unit]
    flagged = population[as_flag(_within(population[column], op, value, value_max))]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population), checked=population, funnel=funnel)


def _within(measured: pd.Series, op: str, value: float, value_max: float) -> pd.Series:
    """``measured`` compared with ``op`` to ``value``; for "between", inside [value, value_max]."""
    if op == "between":
        return measured.between(value, value_max, inclusive="both")
    return COMPARE[op](measured, value)


@rule("duration", "%")
def duration(
    context,
    field: Literal["original", "remaining", "baseline"] = "original",
    op: Op = ">",
    value: float = 44,
    unit: Literal["hours", "days"] = "days",
    exclude: Names = ("complete",),
) -> RuleOutput:
    """Tasks outside the duration limit.
    Counts: flagged / checked

    Tasks whose ``original``, ``remaining`` or ``baseline`` duration compares to ``value``.

    ``baseline`` (DCMA-EA PAM 200.1 4.8) is the baseline's planned duration, matched by Task ID. In
    days it is divided by the task's current hours per day (the baseline calendar is not used). An
    task absent from the baseline has no baseline duration, so it is never flagged but stays in the
    denominator. Without a baseline the rule has no value (n/a).
    """
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
    if field == "baseline":
        if context.baseline is None:
            return RuleOutput(note="needs a baseline")
        hours = population["task_code"].map(context.baseline.frame["bl_duration_hr"])
        measured = hours if unit == "hours" else hours_to_days(hours, population["hours_per_day"])
    else:
        column = {
            ("original", "hours"): "target_drtn_hr_cnt",
            ("remaining", "hours"): "remain_drtn_hr_cnt",
            ("original", "days"): "original_d",
            ("remaining", "days"): "remaining_d",
        }[(field, unit)]
        measured = population[column]
    flagged = population[as_flag(COMPARE[op](measured, value))]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population), checked=population, funnel=funnel)


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
    """Progress dates on the wrong side of the status date.
    Counts: with invalid dates / checked

    Progress dates on the wrong side of the status date.

    ``forecast``: incomplete task scheduled before the status date (not-started start or
    finish; in-progress remaining finish, or remaining start with ``in_progress = "start"``,
    P6 Professional's reading). ``actual``: actual start or finish after it.
    ``denominator``: the population, or ``started`` (tasks with an actual start, as
    DECM 06A506a). ``include_data_date`` also flags a forecast exactly on the status date:
    off by default, P6's reading (101248: "start dates earlier than the data date"); DECM 06A506b
    reads "on or before the status date", the status date being the data date.
    """
    data_date = context.snapshot.data_date
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
    if data_date is None:
        return RuleOutput(note="no status date")
    before = operator.le if include_data_date else operator.lt
    is_open = ~population["is_complete"]
    early_start, early_finish = forecast_dates(population)  # the same reading as the model's Start / Finish
    if in_progress == "start":
        forecast = is_open & before(early_start, data_date)  # a finish before the data date has its start before it too
    else:
        not_started_early = (~population["is_started"]) & before(early_start, data_date)
        forecast = is_open & (not_started_early | before(early_finish, data_date))
    forecast, actual = as_flag(forecast), actual_after(population, data_date)
    hit = {"forecast": forecast, "actual": actual, "both": forecast | actual}[kind]
    flagged = population[hit]
    checked = population[population["act_start_date"].notna()] if denominator == "started" else population
    reasons = invalid_date_reason(forecast, actual)[hit]
    return RuleOutput(
        flagged_activities(flagged, reason=reasons),
        len(flagged),
        len(checked),
        checked=checked,
        funnel=funnel if denominator == "population" else None,  # "started" cuts the denominator outside the funnel
    )


@rule("on_data_date", "%")
def on_data_date(
    context, exclude: Names = ("complete",), date_grain: Literal["day", "timestamp"] = "day"
) -> RuleOutput:
    """Starting or finishing on the data date.
    Counts: on the data date / checked

    Tasks whose start (actual, else forecast) or finish (actual, else forecast) falls on the
    data date: the model's Start and Finish. ``date_grain = "day"`` compares calendar days, as a
    reader of the Gantt does; ``"timestamp"`` the stored date and time.
    """
    data_date = context.snapshot.data_date
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
    if data_date is None:
        return RuleOutput(note="no status date")
    status_day = at_grain(data_date, date_grain)
    starts = as_flag(at_grain(population["start"], date_grain) == status_day)
    finishes = as_flag(at_grain(population["finish"], date_grain) == status_day)
    reason = pd.Series("", index=population.index).mask(finishes, "finishes on the data date")
    reason = reason.mask(starts, "starts on the data date")
    flagged = population[starts | finishes]
    return RuleOutput(
        flagged_activities(flagged, reason=reason[starts | finishes]),
        len(flagged),
        len(population),
        checked=population,
        funnel=funnel,
    )


@rule("no_resource", "%")
def no_resource(
    context,
    exclude: Names = ("complete", "loe", "milestones"),
    expenses_count: bool = True,
    kind: Literal["any", "labour_units"] = "any",
) -> RuleOutput:
    """Tasks with no resource assignment.
    Counts: without resources / checked

    Tasks with no resource assignment (and, if ``expenses_count``, no expense).
    ``kind = "labour_units"`` asks for budgeted labour units above zero instead (P6's Budgeted
    Labor Units: TASK target_work_qty, else the labour and role assignments' target_qty): a
    material-only or a zero-hour assignment does not count.
    """
    funnel = activities_funnel(context, exclude)
    population = funnel.rows
    loaded = population["labor_budget_hr"].fillna(0) > 0 if kind == "labour_units" else population["has_resource"]
    has_cost = loaded | (population["has_expense"] if expenses_count else False)
    flagged = population[~has_cost]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(population), checked=population, funnel=funnel)


# --- baseline ---------------------------------------------------------------------------------


@rule("late_vs_baseline", "%", needs_baseline=True)
def late_vs_baseline(
    context,
    exclude: Names = ("complete", "milestones", "loe"),
    tolerance_hours: float = 0,
    no_baseline: Literal["pass", "planned"] = "pass",
) -> RuleOutput:
    """Forecast to finish after their baseline finish.
    Counts: late / checked

    Tasks forecast to finish later than their baseline finish.

    P6's finish variance is working time on the task's calendar, so a finish at
    17:00 against a baseline of 08:00 the next working morning is not late.
    ``no_baseline``: a task with no baseline finish passes, or (``"planned"``, P6
    Professional) is late when its finish is later than its planned finish.
    """
    funnel = activities_funnel(context, exclude)
    population = with_baseline(context.baseline, funnel.rows)
    if no_baseline == "planned":
        population["bl_finish"] = population["bl_finish"].combine_first(population["target_end_date"])
    output = late_output(context, population, tolerance_hours)
    output.funnel = funnel
    return output


@rule("bei", "ratio", needs_baseline=True)
def bei(
    context,
    exclude: Names = ("loe", "milestones"),
    missing_baseline: Literal["due", "ignore"] = "due",
    due_from: Literal["snapshot", "baseline"] = "snapshot",
) -> RuleOutput:
    """Due by the status date but not completed.
    Counts: completed / due by the status date

    Baseline Execution Index = tasks completed / tasks due by the status date.

    ``missing_baseline = "due"`` counts a task with no baseline finish as due (P6
    EPPM); ``"ignore"`` leaves it out. ``due_from = "baseline"`` (P6 Professional) counts
    the due tasks in the baseline itself, ``exclude`` applied there: a task
    added since is never due, one deleted since still is; ``missing_baseline`` is unused.
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = activities_funnel(context, exclude)
    population = with_baseline(context.baseline, funnel.rows)
    if due_from == "baseline":  # its due tasks are counted in the baseline, outside the file's funnel
        baseline_population = without(context.baseline.snapshot.activities, data_date, exclude)
        return bei_from_baseline(context, population, baseline_population)
    output = bei_from_snapshot(population, data_date, missing_baseline == "due")
    due_codes = output.checked["task_code"]  # type: ignore[index]  # bei_from_snapshot always sets it
    funnel.keep("due by the status date", "xerscope", lambda rows: rows["task_code"].isin(due_codes))
    output.funnel = funnel
    return output


# --- shared with the explicit checks -------------------------------------------------------------


def share_of_type(
    relationships: pd.DataFrame, link_type: str, zero_lag: bool = False, listed: Listed = "others"
) -> RuleOutput:
    """Share of relationships of ``link_type`` (value), and with a zero lag when ``zero_lag``;
    the flagged list holds the others, or those of the type (``listed``); the note is the type mix."""
    of_type = relationships["type"] == link_type
    if zero_lag:
        of_type &= relationships["lag_hr"].fillna(0) == 0
    share = 100.0 * of_type.sum() / len(relationships) if len(relationships) else None
    mix = ", ".join(f"{kind} {count}" for kind, count in relationships["type"].value_counts().items())
    shown = flagged_relationships(relationships[of_type if listed == "of_type" else ~of_type])
    return RuleOutput(
        shown,
        int(of_type.sum()),
        len(relationships),
        share,
        note=mix,
        checked=relationships,
        counted=relationships[of_type],
    )


def late_output(context: AnalysisContext, population: pd.DataFrame, tolerance_hours: float = 0) -> RuleOutput:
    """The tasks finishing later than ``bl_finish`` by more than the tolerance, in working time.

    ``finish_variance_wd`` has P6's sign, baseline finish minus finish: a late finish reads negative
    (Finish Variance of the Check Schedule report of P6 26, tests/test_p6_checksched.py)."""
    variance_hours = context.snapshot.work_hours(population["clndr_id"], population["bl_finish"], population["finish"])
    flagged = population[as_flag(variance_hours > tolerance_hours)]
    # 0.0 - x, not -x: a variance that rounds to 0.00 stays 0.0 and never prints as -0.0
    variance_days = 0.0 - (variance_hours[flagged.index] / flagged["hours_per_day"]).round(2)
    extra = {"bl_finish": flagged["bl_finish"], "finish_variance_wd": variance_days}
    # A task with no finish date (a file never scheduled, or a blank early_end_date) has no variance: it
    # cannot be judged late, yet stays in the denominator. Said in the note, so the reader sees the count.
    without_finish = int(population["finish"].isna().sum())
    note = f"{without_finish} task(s) without a finish date: not judged, still counted" if without_finish else ""
    return RuleOutput(
        flagged_activities(flagged, **extra), len(flagged), len(population), note=note, checked=population
    )


def bei_from_baseline(
    context: AnalysisContext, population: pd.DataFrame, baseline_population: pd.DataFrame
) -> RuleOutput:
    """BEI whose due tasks are counted in the baseline (``baseline_population``: its kept tasks):
    a task added since is never due, one deleted since still is."""
    baseline = context.baseline
    done = int(population["is_complete"].sum())
    kept = baseline.frame[baseline.frame.index.isin(baseline_population["task_code"])]
    due_codes = set(kept.index[kept["bl_finish"] <= context.snapshot.data_date])
    late = population[population["task_code"].isin(due_codes) & ~population["is_complete"]]
    gone = len(due_codes - set(context.snapshot.activities["task_code"]))
    note = f"{done} completed / {len(due_codes)} due in the baseline"
    if gone:
        note += f"; {gone} of them no longer in the schedule"
    index = done / len(due_codes) if due_codes else None
    # without the EV basis's columns: a check's result is the same whatever the EV basis (the app caches it so)
    checked = kept.loc[sorted(due_codes)].drop(columns=EV_COLS).rename_axis("task_code").reset_index()
    completed = population[population["is_complete"]]
    return RuleOutput(
        flagged_activities(late, bl_finish=late["bl_finish"]),
        done,
        len(due_codes),
        index,
        note,
        checked=checked,
        counted=completed,
    )


def bei_from_snapshot(
    population: pd.DataFrame,
    data_date,
    missing_baseline_is_due: bool,
    completed_by_data_date: bool = False,
    date_grain: str = "timestamp",
) -> RuleOutput:
    """BEI whose due tasks are the snapshot's own, ``population`` carrying its ``bl_finish``.

    Due: baseline finish on or before the status date, compared at ``date_grain``.
    ``completed_by_data_date``: only an actual finish on or before the status date counts as completed
    (DCMA-EA PAM 200.1 §3.1.2.4 step 5), compared at the same ``date_grain`` as due (step 2 applies
    the same filter to the baseline finish); P6's report counts every completed activity.
    """
    is_done = as_flag(population["is_complete"])
    finished_later = pd.Series(False, index=population.index)
    if completed_by_data_date:
        finished_later = is_done & as_flag(
            at_grain(population["act_end_date"], date_grain) > at_grain(data_date, date_grain)
        )
        is_done &= ~finished_later
    done = int(is_done.sum())
    without_baseline = population["bl_finish"].isna()
    is_due = as_flag(at_grain(population["bl_finish"], date_grain) <= at_grain(data_date, date_grain))
    if missing_baseline_is_due:
        is_due |= without_baseline
    due = population[is_due]
    late = due[~is_done[due.index]]
    note = f"{done} completed / {len(due)} due"
    if finished_later.any():
        note += f"; {int(finished_later.sum())} completed after the status date, not counted"
    if without_baseline.any():
        note += f"; {int(without_baseline.sum())} without baseline finish"
    index = done / len(due) if len(due) else None
    completed = population[is_done]
    return RuleOutput(
        flagged_activities(late, bl_finish=late["bl_finish"]),
        done,
        len(due),
        index,
        note,
        checked=due,
        counted=completed,
    )


def critical_path_output(context: AnalysisContext, slip_days: float) -> RuleOutput:
    """The critical path test: slip the first open critical task by ``slip_days``; the finish must follow."""
    if context.snapshot.data_date is None:
        return RuleOutput(note="no status date")
    if finish_driver(context.snapshot) is None:
        return RuleOutput(note="no remaining work")
    test = critical_path_test(context.snapshot, slip_days)
    return RuleOutput(value=1.0 if test.passed else 0.0, note=test.note, flagged=pd.DataFrame(test.blocking))
