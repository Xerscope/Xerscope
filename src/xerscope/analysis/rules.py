"""Rule library: every schedule check is one parameterised function.

A standard is a TOML profile (``xerscope/standards/*.toml`` or your own file) that picks
rules, sets their parameters and a target. One rule serves several standards: P6's
"Large Float" and DCMA-06 are both ``float``, one in hours with P6's population, the
other in working days with DCMA's. So P6, DCMA and a company standard share the code
and differ only in data.

Each rule returns a :class:`RuleOutput`; the profile's target turns it into pass/fail.
Populations always exclude WBS-summary rows (``Snapshot.activities``).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from ..xer.model import CONSTRAINT, START_CONSTRAINTS, forecast_dates

if TYPE_CHECKING:
    from .checks import AnalysisContext

Unit = Literal["%", "ratio", "count", "days", "pass/fail"]
Names = tuple[str, ...] | list[str]  # TOML gives lists, defaults are tuples

ACTIVITY_COLS = [
    "task_code",
    "task_name",
    "wbs_code",
    "type",
    "status",
    "start",
    "finish",
    "total_float_d",
    "total_float_hr_cnt",
    "remaining_d",
    "original_d",
    "constraint",
]
LINK_COLS = ["pred_code", "pred_name", "succ_code", "succ_name", "type", "lag_hr", "lag_d"]


@dataclass
class RuleOutput:
    flagged: pd.DataFrame = field(default_factory=pd.DataFrame)
    numerator: int | None = None
    denominator: int | None = None
    value: float | None = None  # set by ratio / pass-fail rules; % and counts are derived
    note: str = ""


@dataclass(frozen=True)
class Rule:
    name: str
    fn: Callable[..., RuleOutput]
    unit: Unit
    doc: str
    needs_baseline: bool = False

    @property
    def params(self) -> dict[str, object]:
        sig = inspect.signature(self.fn)
        return {k: p.default for k, p in list(sig.parameters.items())[1:]}

    def validate(self, params: dict) -> None:
        unknown = set(params) - set(self.params)
        if unknown:
            raise ValueError(
                f"rule {self.name!r} has no parameter(s) {sorted(unknown)}; allowed: {sorted(self.params)}"
            )
        for key in ("exclude", "pred_exempt", "succ_exempt"):
            bad = set(params.get(key, [])) - ALLOWED[key]
            if bad:
                raise ValueError(f"{self.name}.{key}: unknown value(s) {sorted(bad)}; allowed {sorted(ALLOWED[key])}")
        if "links" in params and params["links"] not in LINK_POPULATIONS:
            raise ValueError(f"{self.name}.links must be one of {sorted(LINK_POPULATIONS)}")


RULES: dict[str, Rule] = {}


def rule(name: str, unit: Unit, needs_baseline: bool = False):
    def deco(fn):
        RULES[name] = Rule(name, fn, unit, inspect.getdoc(fn) or "", needs_baseline)
        return fn

    return deco


# --- populations -------------------------------------------------------------------------

EXCLUDE = {
    "complete": lambda t, dd: t["is_complete"],
    "complete_before_data_date": lambda t, dd: t["act_end_date"] < dd if dd is not None else t["is_complete"],
    "started": lambda t, dd: t["is_started"],
    "loe": lambda t, dd: t["is_loe"],
    "milestones": lambda t, dd: t["is_milestone"],
    "no_duration": lambda t, dd: ~(t["target_drtn_hr_cnt"].fillna(0) > 0),
}
EXEMPT = {"started", "start_milestone", "finish_milestone", "project_start", "project_finish"}
ALLOWED = {"exclude": set(EXCLUDE), "pred_exempt": EXEMPT, "succ_exempt": EXEMPT}
LINK_POPULATIONS = {"all", "not_both_complete", "succ_incomplete"}


def activities(ctx: AnalysisContext, exclude: list[str]) -> pd.DataFrame:
    t = ctx.snapshot.activities
    mask = pd.Series(False, index=t.index)
    for key in exclude:
        mask |= EXCLUDE[key](t, ctx.snapshot.data_date).fillna(False).astype(bool)
    return t[~mask]


def link_population(ctx: AnalysisContext, population: str, exclude_loe: bool = False) -> pd.DataFrame:
    s = ctx.snapshot
    t = s.activities.set_index("task_code")
    r = s.relationships.copy()
    r = r[r["succ_code"].isin(t.index)]
    done = t["is_complete"]
    pred_done = r["pred_code"].map(done).fillna(False).astype(bool)
    succ_done = r["succ_code"].map(done).fillna(False).astype(bool)
    if population == "not_both_complete":
        r = r[~(pred_done & succ_done)]
    elif population == "succ_incomplete":
        r = r[~succ_done]
    if exclude_loe:
        loe = t["is_loe"]
        r = r[
            ~(r["pred_code"].map(loe).fillna(False).astype(bool) | r["succ_code"].map(loe).fillna(False).astype(bool))
        ]
    name = t["task_name"]
    return r.assign(pred_name=r["pred_code"].map(name), succ_name=r["succ_code"].map(name))


def _act(df: pd.DataFrame, **extra) -> pd.DataFrame:
    out = df[[c for c in ACTIVITY_COLS if c in df.columns]].copy()
    for k, v in extra.items():
        out[k] = v
    return out


def _lnk(df: pd.DataFrame) -> pd.DataFrame:
    return df[[c for c in LINK_COLS if c in df.columns]].copy()


def _project_ends(ctx: AnalysisContext) -> tuple[set[str], set[str]]:
    """Activities at the project's start (no predecessor, earliest start) and finish."""
    t = ctx.snapshot.activities
    rel = ctx.snapshot.relationships
    no_pred = t[~t["task_code"].isin(rel["succ_code"])]
    no_succ = t[~t["task_code"].isin(rel["pred_code"])]
    first = no_pred["start"].min()
    last = no_succ["finish"].max()
    return (
        set(no_pred.loc[no_pred["start"] == first, "task_code"]),
        set(no_succ.loc[no_succ["finish"] == last, "task_code"]),
    )


# --- logic -------------------------------------------------------------------------------


@rule("missing_logic", "%")
def missing_logic(
    ctx,
    exclude: Names = ("complete",),
    pred_exempt: Names = (),
    succ_exempt: Names = (),
    external_passes: bool = True,
    dangling: bool = False,
) -> RuleOutput:
    """Activities without a predecessor or a successor (open ends).

    ``pred_exempt`` / ``succ_exempt`` pass one side for: started, start_milestone,
    finish_milestone, project_start, project_finish. ``external_passes`` counts links to
    other projects. ``dangling`` also flags a start not driven by any FS/SS predecessor
    or a finish that drives no FS/FF successor.
    """
    pop = activities(ctx, exclude)
    rel = ctx.snapshot.relationships
    own = rel[~rel["is_external"].astype(bool)]  # links within the project; the others are optional
    has_pred = pop["task_code"].isin(own["succ_code"])
    has_succ = pop["task_code"].isin(own["pred_code"])
    if external_passes:
        has_pred |= pop["has_external_pred"]
        has_succ |= pop["has_external_succ"]
    start_ids, finish_ids = _project_ends(ctx)
    exempt_mask = {
        "started": pop["is_started"],
        "start_milestone": pop["is_start_milestone"],
        "finish_milestone": pop["is_milestone"] & ~pop["is_start_milestone"],
        "project_start": pop["task_code"].isin(start_ids),
        "project_finish": pop["task_code"].isin(finish_ids),
    }
    for k in pred_exempt:
        has_pred |= exempt_mask[k]
    for k in succ_exempt:
        has_succ |= exempt_mask[k]
    reason = np.where(
        ~has_pred & ~has_succ,
        "no predecessor, no successor",
        np.where(~has_pred, "no predecessor", np.where(~has_succ, "no successor", "")),
    )
    reason = pd.Series(reason, index=pop.index)
    if dangling:
        drives_start = set(rel.loc[rel["type"].isin(["FS", "SS"]), "succ_code"])
        driven_by_finish = set(rel.loc[rel["type"].isin(["FS", "FF"]), "pred_code"])
        d_start = (
            has_pred
            & ~pop["task_code"].isin(drives_start)
            & ~pop["is_started"]
            & ~pop["has_external_pred"]
            & ~exempt_mask["project_start"]
        )
        d_finish = (
            has_succ
            & ~pop["task_code"].isin(driven_by_finish)
            & ~pop["has_external_succ"]
            & ~exempt_mask["project_finish"]
        )
        reason = reason.mask((reason == "") & d_start, "dangling start (no FS/SS predecessor)")
        reason = reason.mask((reason == "") & d_finish, "dangling finish (no FS/FF successor)")
    bad = pop[reason != ""]
    return RuleOutput(_act(bad, reason=reason[reason != ""]), len(bad), len(pop))


@rule("dangling", "%")
def dangling(ctx, end: str = "finish", exclude: Names = ("complete",)) -> RuleOutput:
    """Activities with logic on one end that does not drive it.

    ``end = "start"``: has predecessors but none FS or SS (the start floats free).
    ``end = "finish"``: has successors but none FS or FF (the finish drives nothing).
    Activities with no logic at all on that end are left to ``missing_logic``.
    """
    if end not in ("start", "finish"):
        raise ValueError("dangling.end must be 'start' or 'finish'")
    pop = activities(ctx, exclude)
    rel = ctx.snapshot.relationships
    if end == "start":
        pop = pop[~pop["is_started"]]
        has = pop["task_code"].isin(rel["succ_code"])
        driving = pop["task_code"].isin(rel.loc[rel["type"].isin(["FS", "SS"]), "succ_code"])
    else:
        has = pop["task_code"].isin(rel["pred_code"])
        driving = pop["task_code"].isin(rel.loc[rel["type"].isin(["FS", "FF"]), "pred_code"])
    bad = pop[has & ~driving]
    return RuleOutput(_act(bad), len(bad), len(pop))


@rule("lag", "%")
def lag(
    ctx, op: str = ">", value: float = 0, unit: str = "hours", links: str = "succ_incomplete", exclude_loe: bool = False
) -> RuleOutput:
    """Relationships whose lag compares to ``value`` with ``op`` (<, >, <=, >=).

    Negative = lead (``op = "<"``, value 0); positive lag (``">"``, 0); long lag
    (``">"``, 352 hours). ``unit``: hours, or days on the lag calendar.
    """
    r = link_population(ctx, links, exclude_loe)
    col = {"hours": "lag_hr", "days": "lag_d"}[unit]
    ops = {"<": np.less, ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal}
    bad = r[ops[op](r[col].fillna(0), value)]
    return RuleOutput(_lnk(bad), len(bad), len(r))


@rule("relationship_type", "%")
def relationship_type(ctx, type: str = "FS", links: str = "succ_incomplete", exclude_loe: bool = False) -> RuleOutput:
    """Share of relationships of ``type`` (value), listing the others."""
    r = link_population(ctx, links, exclude_loe)
    ok = r["type"] == type
    share = 100.0 * ok.sum() / len(r) if len(r) else None
    mix = ", ".join(f"{k} {v}" for k, v in r["type"].value_counts().items())
    return RuleOutput(_lnk(r[~ok]), int(ok.sum()), len(r), share, note=mix)


# --- constraints, float, duration ----------------------------------------------------------


@rule("constraints", "%")
def constraints(
    ctx, types: Names = (), exclude: Names = ("complete",), ignore_start_when_started: bool = True
) -> RuleOutput:
    """Activities with a primary or secondary constraint in ``types`` (P6 codes, e.g. CS_MANDSTART)."""
    unknown = set(types) - set(CONSTRAINT)
    if unknown:
        raise ValueError(f"constraints.types: unknown {sorted(unknown)}; allowed {sorted(CONSTRAINT)}")
    pop = activities(ctx, exclude)
    hits = pd.Series(False, index=pop.index)
    for col in ("cstr_type", "cstr_type2"):
        c = pop[col].isin(types)
        if ignore_start_when_started:
            c &= ~(pop[col].isin(START_CONSTRAINTS) & pop["is_started"])
        hits |= c
    bad = pop[hits]
    return RuleOutput(_act(bad, constraint2=bad["cstr_type2"].map(CONSTRAINT)), len(bad), len(pop))


_OPS = {"<": np.less, ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal}


@rule("float", "%")
def total_float(
    ctx, op: str = ">", value: float = 44, unit: str = "days", exclude: Names = ("complete",)
) -> RuleOutput:
    """Activities whose total float compares to ``value`` (hours as stored, or working days)."""
    pop = activities(ctx, exclude)
    col = {"hours": "total_float_hr_cnt", "days": "total_float_d"}[unit]
    bad = pop[_OPS[op](pop[col], value).fillna(False).astype(bool)]
    return RuleOutput(_act(bad), len(bad), len(pop))


@rule("duration", "%")
def duration(
    ctx, field: str = "original", op: str = ">", value: float = 44, unit: str = "days", exclude: Names = ("complete",)
) -> RuleOutput:
    """Activities whose ``original`` or ``remaining`` duration compares to ``value``."""
    pop = activities(ctx, exclude)
    col = {
        ("original", "hours"): "target_drtn_hr_cnt",
        ("remaining", "hours"): "remain_drtn_hr_cnt",
        ("original", "days"): "original_d",
        ("remaining", "days"): "remaining_d",
    }[(field, unit)]
    bad = pop[_OPS[op](pop[col], value).fillna(False).astype(bool)]
    return RuleOutput(_act(bad), len(bad), len(pop))


# --- progress --------------------------------------------------------------------------


@rule("invalid_dates", "%")
def invalid_dates(
    ctx,
    kind: str = "both",
    exclude: Names = ("loe", "complete_before_data_date"),
    denominator: str = "population",
    include_data_date: bool = False,
) -> RuleOutput:
    """Progress dates on the wrong side of the data date.

    ``forecast``: incomplete activity scheduled before the data date (not-started start or
    finish, in-progress remaining finish). ``actual``: actual start or finish after it.
    ``denominator``: the population, or ``started`` (activities with an actual start, as
    DECM 06A506a). ``include_data_date`` also flags a forecast exactly on the data date:
    off by default, because P6's data date is the first instant of remaining work (DECM's
    "on or before the status date", the end of the reported period, is "before" it).
    """
    dd = ctx.snapshot.data_date
    pop = activities(ctx, exclude)
    if dd is None:
        return RuleOutput(note="no data date")
    if denominator not in ("population", "started"):
        raise ValueError("invalid_dates.denominator must be 'population' or 'started'")
    before = np.less_equal if include_data_date else np.less
    open_ = ~pop["is_complete"]
    early_s, early_f = forecast_dates(pop)  # the same reading as the model's Start / Finish (R10)
    fc = open_ & (((~pop["is_started"]) & before(early_s, dd)) | before(early_f, dd))
    ac = (pop["act_start_date"] > dd) | (pop["act_end_date"] > dd)
    fc, ac = fc.fillna(False).astype(bool), ac.fillna(False).astype(bool)
    hit = {"forecast": fc, "actual": ac, "both": fc | ac}[kind]
    reason = np.where(
        fc & ac,
        "forecast before and actual after data date",
        np.where(fc, "forecast before data date", "actual after data date"),
    )
    bad = pop[hit]
    total = int(pop["act_start_date"].notna().sum()) if denominator == "started" else len(pop)
    return RuleOutput(_act(bad, reason=pd.Series(reason, index=pop.index)[hit]), len(bad), total)


@rule("no_resource", "%")
def no_resource(ctx, exclude: Names = ("complete", "loe", "milestones"), expenses_count: bool = True) -> RuleOutput:
    """Activities with no resource assignment (and, if ``expenses_count``, no expense)."""
    pop = activities(ctx, exclude)
    ok = pop["has_resource"] | (pop["has_expense"] if expenses_count else False)
    bad = pop[~ok]
    return RuleOutput(_act(bad), len(bad), len(pop))


# --- baseline ---------------------------------------------------------------------------------


def _with_baseline(ctx, pop: pd.DataFrame) -> pd.DataFrame:
    bl = ctx.baseline.frame
    return pop.join(bl[["bl_start", "bl_finish"]], on="task_code")


@rule("late_vs_baseline", "%", needs_baseline=True)
def late_vs_baseline(ctx, exclude: Names = ("complete", "milestones", "loe"), tolerance_hours: float = 0) -> RuleOutput:
    """Activities forecast to finish later than their baseline finish.

    P6's finish variance is working time on the activity's calendar, so a finish at
    17:00 against a baseline of 08:00 the next working morning is not late.
    """
    pop = _with_baseline(ctx, activities(ctx, exclude))
    var_h = ctx.snapshot.work_hours(pop["clndr_id"], pop["bl_finish"], pop["finish"])
    late = var_h > tolerance_hours
    bad = pop[late.fillna(False).astype(bool)]
    var_d = (var_h[bad.index] / bad["hours_per_day"]).round(2)
    return RuleOutput(_act(bad, bl_finish=bad["bl_finish"], finish_variance_wd=var_d), len(bad), len(pop))


@rule("missed_tasks", "%", needs_baseline=True)
def missed_tasks(ctx, exclude: Names = ("loe",)) -> RuleOutput:
    """Of the activities due by the data date (baseline finish), those not finished or finished late."""
    dd = ctx.snapshot.data_date
    pop = _with_baseline(ctx, activities(ctx, exclude))
    due = pop[pop["bl_finish"] <= dd]
    # finished late = on a later date than the baseline finish (DCMA compares dates; an
    # actual on a non-working day is still late)
    late = due["act_end_date"].dt.normalize() > due["bl_finish"].dt.normalize()
    missed = ~due["is_complete"] | late.fillna(False).astype(bool)
    bad = due[missed]
    return RuleOutput(_act(bad, bl_finish=bad["bl_finish"]), len(bad), len(due))


@rule("bei", "ratio", needs_baseline=True)
def bei(ctx, exclude: Names = ("loe", "milestones"), missing_baseline: str = "due") -> RuleOutput:
    """Baseline Execution Index = activities completed / activities due by the data date.

    ``missing_baseline = "due"`` counts an activity with no baseline finish as due (P6);
    ``"ignore"`` leaves it out.
    """
    dd = ctx.snapshot.data_date
    pop = _with_baseline(ctx, activities(ctx, exclude))
    done = int(pop["is_complete"].sum())
    due_mask = pop["bl_finish"] <= dd
    if missing_baseline == "due":
        due_mask |= pop["bl_finish"].isna()
    elif missing_baseline != "ignore":
        raise ValueError("bei.missing_baseline must be 'due' or 'ignore'")
    due = pop[due_mask]
    late = due[~due["is_complete"]]
    no_bl = int(pop["bl_finish"].isna().sum())
    note = f"{done} completed / {len(due)} due" + (f"; {no_bl} without baseline finish" if no_bl else "")
    return RuleOutput(
        _act(late, bl_finish=late["bl_finish"]), done, len(due), done / len(due) if len(due) else None, note
    )


# --- critical path -------------------------------------------------------------------------------


def _finish_driver(ctx) -> pd.Series | None:
    t = ctx.snapshot.activities
    open_ = t[~t["is_complete"] & ~t["is_loe"]]
    return None if open_.empty else open_.loc[open_["finish"].idxmax()]


@rule("cpli", "ratio")
def cpli(ctx) -> RuleOutput:
    """Critical Path Length Index = (CPL + TF) / CPL.

    CPL = working days from the data date to the forecast finish, TF = total float of the
    activity that sets the finish, both on the project calendar. TF comes from the
    schedule, so it measures the distance to the project's Must Finish By date: without
    one P6 gives the last activity a float of 0 and the index is 1.0 by construction.
    """
    s = ctx.snapshot
    end = _finish_driver(ctx)
    if end is None or s.data_date is None:
        return RuleOutput(note="no remaining work")
    cal = s.calendar()
    cpl = cal.working_days(s.data_date, end["finish"])
    tf_hr = float(end["total_float_hr_cnt"]) if pd.notna(end["total_float_hr_cnt"]) else 0.0
    tf = tf_hr / cal.hours_per_day if cal.hours_per_day else 0.0
    if cpl <= 0:
        return RuleOutput(note="critical path length is 0")
    note = f"CPL {cpl:g} wd to {end['task_code']}, total float {tf:g} wd"
    if s.options.get("must_finish_by") is None:
        note += "; no Must Finish By date: the float is 0 by construction"
    return RuleOutput(value=(cpl + tf) / cpl, note=note)


@rule("critical_path_test", "pass/fail")
def critical_path_test(ctx, delay_days: float = 600) -> RuleOutput:
    """Add ``delay_days`` to the first open critical activity; the finish must slip as much."""
    from .cpm import critical_path_test as run

    res = run(ctx.snapshot, delay_days)
    return RuleOutput(value=1.0 if res.passed else 0.0, note=res.note, flagged=pd.DataFrame(res.blocking))


# --- integrity: is the file what P6 would calculate? ------------------------------------------


@rule("recalculated", "%")
def recalculated(
    ctx,
    fields: Names = ("early_start_date", "early_end_date", "late_start_date", "late_end_date", "total_float_hr_cnt"),
) -> RuleOutput:
    """Open activities whose stored dates or float differ from a P6-style recalculation.

    A difference means the file was edited after the last F9, or uses a scheduling
    feature xerscope does not model (see analysis/cpm.py). Exact to the minute.
    """
    from .cpm import CycleError, compare_with_stored

    try:
        cmp = compare_with_stored(ctx.snapshot)
    except CycleError as exc:
        return RuleOutput(note=f"cannot schedule: {exc}")
    cmp = cmp[cmp["field"].isin(fields) & cmp["stored"].notna()]
    if cmp.empty:
        return RuleOutput(numerator=0, denominator=0, note="no stored dates to compare")
    diffs: dict[str, list[str]] = {}
    for c, f, st, co, ok in cmp[["task_code", "field", "stored", "computed", "agree"]].itertuples(index=False):
        if not ok:
            diffs.setdefault(c, []).append(f"{f}: {st} -> {co}")
    t = ctx.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    bad = t.loc[sorted(diffs)].reset_index()
    flagged = _act(bad, differences=["; ".join(diffs[c]) for c in bad["task_code"]])
    n_bad = sum(len(v) for v in diffs.values())
    return RuleOutput(
        flagged,
        len(diffs),
        cmp["task_code"].nunique(),
        note=f"{len(cmp) - n_bad} of {len(cmp)} stored values reproduced",
    )


@rule("out_of_sequence", "count")
def out_of_sequence(ctx, exclude: Names = ("loe",), method: str = "actuals") -> RuleOutput:
    """Progress out of logic sequence.

    ``method = "actuals"``: started activities whose FS predecessor had not finished, or
    SS predecessor not started, at their actual start (P6 lists them in its scheduling
    log). Counts activities.

    ``method = "decm"`` (DECM 06A212a): counts relationships into incomplete work where
    FS: (S.AS or S.FS) < P.FF; SS: (S.AS or S.FS) < P.FS; FF: (S.AF or S.FF) < P.FF;
    SF: (S.AF or S.FF) < P.FS. Actual dates first, else forecast; lags are not added,
    so a lead that lets work overlap is also an out-of-sequence condition.
    """
    pop = activities(ctx, exclude)
    t = ctx.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    rel = ctx.snapshot.relationships
    if method == "decm":
        succ = pop[~pop["is_complete"]].drop_duplicates("task_code").set_index("task_code")
        r = rel[rel["succ_code"].isin(succ.index) & rel["pred_code"].isin(t.index)].copy()
        p_s, p_f = r["pred_code"].map(t["start"]), r["pred_code"].map(t["finish"])
        s_s, s_f = r["succ_code"].map(succ["start"]), r["succ_code"].map(succ["finish"])
        cond = np.select(
            [r["type"] == "FS", r["type"] == "SS", r["type"] == "FF", r["type"] == "SF"],
            [s_s < p_f, s_s < p_s, s_f < p_f, s_f < p_s],
            default=False,
        )
        bad = r[cond.astype(bool)]
        out = _lnk(
            bad.assign(pred_name=bad["pred_code"].map(t["task_name"]), succ_name=bad["succ_code"].map(t["task_name"]))
        )
        for name, col in (("pred_start", p_s), ("pred_finish", p_f), ("succ_start", s_s), ("succ_finish", s_f)):
            out[name] = col[bad.index]
        return RuleOutput(out, len(bad), len(r))
    if method != "actuals":
        raise ValueError("out_of_sequence.method must be 'actuals' or 'decm'")
    started = pop[pop["is_started"]].drop_duplicates("task_code").set_index("task_code")
    rel = rel[rel["succ_code"].isin(started.index) & rel["pred_code"].isin(t.index)]
    ahead: dict[str, list[str]] = {}
    for p, c, typ in rel[["pred_code", "succ_code", "type"]].itertuples(index=False):
        start = started.at[c, "act_start_date"]
        p_fin, p_start = t.at[p, "act_end_date"], t.at[p, "act_start_date"]
        if (typ == "FS" and (pd.isna(p_fin) or p_fin > start)) or (
            typ == "SS" and (pd.isna(p_start) or p_start > start)
        ):
            ahead.setdefault(c, []).append(f"{p} ({typ})")
    bad = started.loc[sorted(ahead)].reset_index()
    return RuleOutput(_act(bad, ahead_of=[", ".join(ahead[c]) for c in bad["task_code"]]), len(bad), len(started))


@rule("assignments_recalculated", "%")
def assignments_recalculated(ctx) -> RuleOutput:
    """Open resource assignments whose stored remaining early/late dates differ from a recalculation.

    Same idea as ``recalculated``, on TASKRSRC: activity dates + assignment lag, duration
    = remaining units / units per hour, on the resource's calendar for resource-dependent
    activities.
    """
    from .cpm import CycleError, compare_assignments

    try:
        cmp = compare_assignments(ctx.snapshot)
    except CycleError as exc:
        return RuleOutput(note=f"cannot schedule: {exc}")
    cmp = cmp[cmp["stored"].notna()]
    if cmp.empty:
        return RuleOutput(numerator=0, denominator=0, note="no stored assignment dates to compare")
    bad = cmp[~cmp["agree"]]
    by = bad.groupby("taskrsrc_id")
    flagged = (
        pd.DataFrame(
            {
                "task_code": by["task_code"].first(),
                "resource": by["rsrc"].first(),
                "differences": by.apply(
                    lambda g: "; ".join(
                        f"{f}: {a} -> {b}" for f, a, b in g[["field", "stored", "computed"]].itertuples(index=False)
                    ),
                    include_groups=False,
                ),
            }
        ).reset_index()
        if not bad.empty
        else pd.DataFrame()
    )
    return RuleOutput(
        flagged,
        bad["taskrsrc_id"].nunique(),
        cmp["taskrsrc_id"].nunique(),
        note=f"{len(cmp) - len(bad)} of {len(cmp)} stored assignment dates reproduced",
    )


# --- DCMA DECM v8.0, Guideline 6 (schedule) -------------------------------------------------------


def _incomplete(ctx, loe: bool) -> pd.DataFrame:
    """DECM population: incomplete (no actual finish) tasks and milestones, LOE optional."""
    t = ctx.snapshot.activities
    pop = t[~t["is_complete"]]
    return pop if loe else pop[~pop["is_loe"]]


@rule("open_ends", "%")
def open_ends(ctx, exempt_ends: str = "baseline") -> RuleOutput:
    """DECM 06A204b dangling logic: incomplete non-LOE tasks and milestones with an open start or finish.

    Open start: a task whose predecessors are only FF / SF, or none; a milestone with no
    predecessor. Open finish: a task whose successors are only SS / SF, or none; a
    milestone with no successor. Started tasks are included (incomplete = no actual
    finish). ``exempt_ends``: the earliest-baseline-start activities pass the start test
    and the latest-baseline-finish ones the finish test (``baseline``; the snapshot's
    planned dates when no baseline is loaded), or ``none``.
    """
    pop = _incomplete(ctx, loe=False)
    rel = ctx.snapshot.relationships
    preds = rel.groupby("succ_code")["type"].agg(set)
    succs = rel.groupby("pred_code")["type"].agg(set)
    p_types = pop["task_code"].map(preds)
    s_types = pop["task_code"].map(succs)
    has_p = p_types.notna() | pop["has_external_pred"]
    has_s = s_types.notna() | pop["has_external_succ"]
    drives_start = p_types.map(lambda x: isinstance(x, set) and bool(x & {"FS", "SS"})) | pop["has_external_pred"]
    finish_drives = s_types.map(lambda x: isinstance(x, set) and bool(x & {"FS", "FF"})) | pop["has_external_succ"]
    ms = pop["is_milestone"]
    open_start = np.where(ms, ~has_p, ~drives_start.astype(bool))
    open_finish = np.where(ms, ~has_s, ~finish_drives.astype(bool))
    note = ""
    if exempt_ends == "baseline":
        # the project's first start and last finish are looked up over every activity,
        # finished ones included: once the first activity is done, the next one in line
        # is not the project start
        if ctx.baseline is not None:
            bl = ctx.baseline.frame
            all_s, all_f = bl["bl_start"], bl["bl_finish"]
            b_s, b_f = pop["task_code"].map(all_s), pop["task_code"].map(all_f)
            note = "first/last by baseline dates"
        else:
            t_all = ctx.snapshot.activities
            all_s, all_f = t_all["target_start_date"], t_all["target_end_date"]
            b_s, b_f = pop["target_start_date"], pop["target_end_date"]
            note = "no baseline: first/last by planned dates"
        open_start &= ~(b_s == all_s.min()).fillna(False).to_numpy(bool)
        open_finish &= ~(b_f == all_f.max()).fillna(False).to_numpy(bool)
    elif exempt_ends != "none":
        raise ValueError("open_ends.exempt_ends must be 'baseline' or 'none'")
    reason = np.where(
        open_start & open_finish,
        "open start and finish",
        np.where(
            open_start,
            "open start (no FS/SS predecessor)",
            np.where(open_finish, "open finish (no FS/FF successor)", ""),
        ),
    )
    hit = reason != ""
    bad = pop[hit]
    return RuleOutput(_act(bad, reason=reason[hit]), len(bad), len(pop), note=note)


@rule("lagged_activities", "%")
def lagged_activities(ctx, loe: bool = True) -> RuleOutput:
    """DECM 06A205a: incomplete tasks and milestones with at least one lag in their predecessor logic."""
    pop = _incomplete(ctx, loe)
    rel = ctx.snapshot.relationships
    lagged = rel[rel["lag_hr"].fillna(0) > 0].groupby("succ_code")["pred_code"].agg(lambda x: ", ".join(sorted(x)))
    bad = pop[pop["task_code"].isin(lagged.index)]
    return RuleOutput(_act(bad, lagged_from=bad["task_code"].map(lagged)), len(bad), len(pop))


@rule("summary_logic", "count")
def summary_logic(ctx) -> RuleOutput:
    """DECM 06A208a: summary activities (P6 WBS summary) with a predecessor or successor."""
    t = ctx.snapshot.tasks
    summ = t[t["is_wbs_summary"]]
    rel = ctx.snapshot.relationships
    bad = summ[summ["task_code"].isin(rel["pred_code"]) | summ["task_code"].isin(rel["succ_code"])]
    return RuleOutput(_act(bad), len(bad), len(summ))


@rule("loe_successors", "%")
def loe_successors(ctx) -> RuleOutput:
    """DECM 06A210a: incomplete LOE activities with a discrete (non-LOE) successor."""
    t = ctx.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    pop = _incomplete(ctx, loe=True)
    pop = pop[pop["is_loe"]]
    rel = ctx.snapshot.relationships
    r = rel[rel["pred_code"].isin(pop["task_code"]) & rel["succ_code"].isin(t.index)]
    discrete = r[~r["succ_code"].map(t["is_loe"]).fillna(False).astype(bool)]
    succ = discrete.groupby("pred_code")["succ_code"].agg(lambda x: ", ".join(sorted(x)))
    bad = pop[pop["task_code"].isin(succ.index)]
    return RuleOutput(_act(bad, drives=bad["task_code"].map(succ)), len(bad), len(pop))


@rule("missing_baseline", "%", needs_baseline=True)
def missing_baseline(ctx) -> RuleOutput:
    """DECM 06A501a: tasks and milestones without a baseline start or finish (summaries excluded)."""
    pop = _with_baseline(ctx, ctx.snapshot.activities)
    bad = pop[pop["bl_start"].isna() | pop["bl_finish"].isna()]
    return RuleOutput(_act(bad), len(bad), len(pop))


@rule("actuals_changed", "%")
def actuals_changed(ctx, field: str = "start") -> RuleOutput:
    """DECM 06A504a / 06A504b: actual start (or finish) different from the previous update's.

    X = activities whose actual date differs from (or was removed since) the one the
    previous update reported; Y = activities with that actual date in either update, so
    a removed date counts on both sides and the share never exceeds 100 %. Needs the
    previous update (the weekly series, or two files).
    """
    col = {"start": "act_start_date", "finish": "act_end_date"}[field]
    prev = ctx.previous
    if prev is None:
        return RuleOutput(note="needs the previous update")
    now = ctx.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    before = prev.activities.drop_duplicates("task_code").set_index("task_code")[col].dropna()
    common = before.index.intersection(now.index)
    changed = [c for c in common if now.at[c, col] != before[c]]
    bad = now.loc[changed].reset_index()
    out = _act(bad, previous=[before[c] for c in changed], now=bad.get(col))
    dated = set(now.index[now[col].notna()]) | set(common)
    return RuleOutput(out, len(bad), len(dated))


@rule("progress_actuals", "%")
def progress_actuals(ctx, kind: str = "in_progress") -> RuleOutput:
    """DECM 06A505a / 06A505b: progress without the matching actual date.

    ``in_progress``: % complete > 0 (or status in progress) but no actual start, of the
    activities showing progress. ``complete``: 100 % (or status complete) but no actual
    finish, of the activities at 100 %.
    """
    t = ctx.snapshot.activities
    if kind == "in_progress":
        pop = t[(t["pct_complete"] > 0) | t["is_started"]]
        bad = pop[pop["act_start_date"].isna()]
    elif kind == "complete":
        pop = t[(t["pct_complete"] >= 100) | t["is_complete"]]
        bad = pop[pop["act_end_date"].isna()]
    else:
        raise ValueError("progress_actuals.kind must be 'in_progress' or 'complete'")
    return RuleOutput(_act(bad), len(bad), len(pop))


@rule("riding_status_date", "%")
def riding_status_date(
    ctx, window_wd: float = 3, remaining_tolerance_wd: float = 2, period_days: int = 28
) -> RuleOutput:
    """DECM 06A506c: forecasts riding the status date over two consecutive (monthly) updates.

    Compared with the latest update at least ``period_days`` older. A not-started activity
    rides when its forecast start is within ``window_wd`` working days of the data date in
    both; a started one when its remaining duration has moved by no more than
    ``remaining_tolerance_wd`` (its finish slides with the data date). Y = incomplete
    activities.
    """
    snap = ctx.snapshot
    store = ctx.store
    if store is None or snap.data_date is None:
        return RuleOutput(note="needs the series of updates")
    earlier = [
        s for s in store if s.data_date is not None and s.data_date <= snap.data_date - pd.Timedelta(days=period_days)
    ]
    if not earlier:
        return RuleOutput(note=f"needs an update {period_days} days older")
    prev = earlier[-1]
    pop = _incomplete(ctx, loe=False)
    p = prev.activities.drop_duplicates("task_code").set_index("task_code")
    pop = pop[pop["task_code"].isin(p.index)]

    def near(s, frame):
        h = s.work_hours(frame["clndr_id"], pd.Series(s.data_date, index=frame.index), frame["start"])
        return (h >= 0) & (h <= window_wd * frame["hours_per_day"])

    start_now = near(snap, pop) & ~pop["is_started"]
    pp = p.loc[pop["task_code"]].set_index(pop.index)
    start_prev = near(prev, pp) & ~pp["is_started"]
    rd_change = (pop["remaining_d"] - pp["remaining_d"]).abs()
    finish_ride = pop["is_started"] & pp["is_started"] & (rd_change <= remaining_tolerance_wd)
    hit = ((start_now & start_prev) | finish_ride).fillna(False).astype(bool)
    bad = pop[hit]
    why = np.where(
        finish_ride[hit],
        "remaining duration unchanged",
        f"start within {window_wd:g} wd of the data date in both updates",
    )
    return RuleOutput(_act(bad, reason=why), len(bad), len(pop), note=f"vs update of {prev.data_date:%Y-%m-%d}")
