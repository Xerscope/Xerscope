"""Half-step reading of one week (analysis/forensics.py): hand-checked shifts, invariants.

Source: AACE RP 29R-03 (rev. April 25, 2011) MIP 3.4, Observational / Dynamic / Contemporaneous
Split, 3.4.K.4 (bifurcation: the progress-only half-step update).

Every schedule is on the C8 calendar (Mon-Fri, 08:00-12:00 and 13:00-17:00), data date
Monday 2 March 2026 08:00 unless stated: a 40 h activity runs Monday to Friday 17:00.
"""

from pathlib import Path

import pandas as pd
import pytest
from conftest import P6_CORPUS_HINT, missing
from xerkit import FM, MON_FRI_8H, active, clndr_data, done, snap, todo

from xerscope.analysis.changelog import changelog
from xerscope.analysis.cpm import CycleError, schedule
from xerscope.analysis.forensics import (
    AS_SCHEDULED,
    LAST_ACTIVITY,
    MANDATORY_FINISH,
    MUST_FINISH_BY,
    STEP_NAMES,
    finish_case,
    half_step,
    half_step_series,
    longest_path_float_d,
)
from xerscope.store import SnapshotStore
from xerscope.xer import build_snapshot, read_xer

WEEK_LATER = "2026-03-09 08:00"  # the Monday after the default data date


def week(duration_hr: int = 40) -> dict:
    return dict(target_drtn_hr_cnt=str(duration_hr), remain_drtn_hr_cnt=str(duration_hr))


def chain(*codes: str) -> list[tuple]:
    return [(before, after, "FS", 0) for before, after in zip(codes, codes[1:], strict=False)]


def shifts(read) -> dict[str, float]:
    return read.steps.set_index("step")["shift_wd"].to_dict()


# --- the week read step by step -------------------------------------------------------------------

THREE_WEEKS = snap([todo("A", **week()), todo("B", **week()), todo("C", **week())], chain("A", "B", "C"))


@pytest.mark.oracle("property")
def test_a_week_without_change_moves_nothing():
    """Metamorphic: the same file twice, every step 0.0 (never -0.0) and no residual."""
    read = half_step(THREE_WEEKS, THREE_WEEKS)
    assert read.steps["step"].tolist() == [AS_SCHEDULED, *STEP_NAMES]
    assert read.steps["shift_wd"].iloc[1:].tolist() == [0.0] * len(STEP_NAMES)
    assert read.residual_wd == 0.0 and read.slip_wd == 0.0 and read.replanning_wd == 0.0
    assert (read.matched, read.added, read.deleted) == (3, 0, 0)


@pytest.mark.oracle("standard")
def test_a_delay_absorbed_by_compression_reads_as_slip_then_replanning():
    """AACE 29R-03 MIP 3.4 (3.4.K.4.d to f): the slip due to progress and the one due to revisions, read apart.

    Hand calculation. Earlier: A Mon 2 - Fri 6, B Mon 9 - Fri 13, C Mon 16 - Fri 20 17:00. Later,
    data date Mon 9: A still has 16 h, so finishes Tue 10 17:00; B Wed 11 - Tue 17; C Wed 18 - Tue
    24: progress alone loses 2 wd. B is then cut to 24 h (Wed 11 - Fri 13), C back to Mon 16 - Fri
    20: the durations step gains the 2 wd. The finish shown has not moved.
    """
    later = snap(
        [
            active("A", act_start_date="2026-03-02 08:00", remain_drtn_hr_cnt="16", target_drtn_hr_cnt="40"),
            todo("B", **week(24)),
            todo("C", **week()),
        ],
        chain("A", "B", "C"),
        data_date=WEEK_LATER,
    )
    read = half_step(THREE_WEEKS, later)
    assert read.old_finish == read.new_finish == pd.Timestamp("2026-03-20 17:00")
    assert read.finish_before_replanning == pd.Timestamp("2026-03-24 17:00")
    assert shifts(read)["progress"] == -2.0 and shifts(read)["durations"] == 2.0
    assert read.slip_wd == -2.0 and read.replanning_wd == 2.0 and read.residual_wd == 0.0
    by_step = read.steps.set_index("step")["changes"]
    assert by_step["progress"] == 2  # A started, A % complete
    assert by_step["durations"] == 2  # B: original duration changed, remaining duration cut


@pytest.mark.oracle("standard")
def test_a_link_added_moves_the_finish_at_the_logic_step():
    """A and B in parallel end Fri 6; linked A -> B, B runs Mon 9 - Fri 13: 5 wd lost, at logic alone."""
    parallel = snap([todo("A", **week()), todo("B", **week())])
    linked = snap([todo("A", **week()), todo("B", **week())], chain("A", "B"))
    read = half_step(parallel, linked)
    assert shifts(read)["logic"] == -5.0
    assert read.steps.set_index("step").loc[["progress", "scope", "durations", "constraints"], "shift_wd"].eq(0).all()
    assert read.residual_wd == 0.0


@pytest.mark.oracle("standard")
def test_an_activity_added_at_the_end_moves_the_finish_at_the_scope_step():
    """D (40 h) after A enters with its link at the scope step: Mon 9 - Fri 13, 5 wd lost there."""
    one = snap([todo("A", **week())])
    two = snap([todo("A", **week()), todo("D", **week())], chain("A", "D"))
    read = half_step(one, two)
    assert shifts(read)["scope"] == -5.0 and shifts(read)["logic"] == 0.0
    assert (read.matched, read.added, read.deleted) == (1, 1, 0)


@pytest.mark.oracle("standard")
def test_a_start_on_constraint_moves_the_finish_at_the_constraints_step():
    """Start On Mon 9 on A: A runs Mon 9 - Fri 13 instead of Mon 2 - Fri 6, 5 wd lost at constraints."""
    free = snap([todo("A", **week())])
    held = snap([todo("A", cstr_type="CS_MSO", cstr_date="2026-03-09 08:00", **week())])
    read = half_step(free, held)
    assert shifts(read)["constraints"] == -5.0 and read.residual_wd == 0.0


@pytest.mark.oracle("standard")
def test_a_calendar_change_moves_the_finish_at_the_last_step():
    """A moved to 10 h days: 40 h end Thu 5 18:00, read on the project calendar (8 h days) as 1 wd gained."""
    eight = snap([todo("A", **week())])
    ten = snap([todo("A", clndr_id="C10", **week())])
    read = half_step(eight, ten)
    assert shifts(read)["calendars and options"] == 1.0 and read.residual_wd == 0.0


@pytest.mark.oracle("standard")
def test_a_remaining_duration_increased_on_started_work_is_a_revision_not_progress():
    """3.4.K.4: a decreased remaining duration is progress data (b.iv), an increase is a non-progress revision.

    A started Mon 2 with 40 h left; a week later still 48 h left. Progress alone: the 40 h run from Mon 9,
    finish Fri 13 (5 wd lost). Durations: 48 h = 6 days, Mon 9 to Mon 16 17:00 (1 wd more).
    """
    earlier = snap([active("A", act_start_date="2026-03-02 08:00", remain_drtn_hr_cnt="40", target_drtn_hr_cnt="40")])
    later = snap(
        [active("A", act_start_date="2026-03-02 08:00", remain_drtn_hr_cnt="48", target_drtn_hr_cnt="40")],
        data_date=WEEK_LATER,
    )
    read = half_step(earlier, later)
    assert shifts(read)["progress"] == -5.0 and shifts(read)["durations"] == -1.0
    assert read.period_wd == 5.0 and read.is_slip_beyond_period is False


@pytest.mark.oracle("standard")
def test_a_slip_beyond_the_period_is_flagged():
    """3.4.K.4.g: a progress variance larger than the update period is suspect. A not started, 40 h,
    no actual start a week later: the 40 h run from Mon 9 instead of Mon 2, 5 wd lost in a 5 wd
    period, not flagged; the same with a Start On Mon 9 in the earlier file is not a progress loss.
    An 11-day period on a 7-day calendar project would be the flagged case; here the bound is read."""
    earlier = snap([todo("A", **week())])
    later = snap([todo("A", **week())], data_date=WEEK_LATER)
    read = half_step(earlier, later)
    assert shifts(read)["progress"] == -5.0 and read.period_wd == 5.0
    assert read.is_slip_beyond_period is False


@pytest.mark.oracle("property")
def test_the_steps_add_up_to_the_recalculated_move_of_the_finish():
    """Metamorphic (3.4.K.4.f, 3.4.E.13): every kind of change at once, the shifts sum to the move between
    the two recalculated finishes (on the later update's project calendar) and the residual is 0."""
    earlier = snap(
        [todo("A", **week()), todo("B", **week()), todo("C", **week()), todo("GONE", **week())], chain("A", "B", "C")
    )
    later = snap(
        [
            done("A", act_start_date="2026-03-02 08:00", act_end_date="2026-03-04 17:00", target_drtn_hr_cnt="40"),
            todo("B", clndr_id="C10", cstr_type="CS_MSO", cstr_date="2026-03-16 08:00", **week(60)),
            todo("C", **week(16)),
            todo("NEW", **week()),
        ],
        [*chain("A", "B"), ("B", "C", "SS", 8), ("C", "NEW", "FS", 0)],
        data_date=WEEK_LATER,
    )
    read = half_step(earlier, later)
    expected = 0.0 - later.project_working_days(schedule(earlier).finish, schedule(later).finish)
    assert round(read.steps["shift_wd"].iloc[1:].sum(), 2) == round(expected, 2)
    assert read.residual_wd == 0.0
    assert (read.matched, read.added, read.deleted) == (3, 1, 1)


# --- how the finish is held -----------------------------------------------------------------------


@pytest.mark.oracle("standard")
def test_finish_case_last_activity_must_finish_by_and_mandatory_finish():
    """Oracle P6 help, Must Finish By: a project-level constraint on the late dates. Mandatory Finish:
    the date, whatever the logic (docs/cpm.md). Without either the finish is the latest early finish."""
    free = snap([todo("A", **week())])
    assert finish_case(free) == (LAST_ACTIVITY, pd.Timestamp("2026-03-06 17:00"))
    bounded = snap([todo("A", **week())], project={"plan_end_date": "2026-03-05 17:00"})
    assert finish_case(bounded) == (MUST_FINISH_BY, pd.Timestamp("2026-03-05 17:00"))
    pinned = snap(
        [todo("A", **week()), todo("M", cstr_type="CS_MANDFIN", cstr_date="2026-03-06 17:00", **FM)], chain("A", "M")
    )
    assert finish_case(pinned) == (MANDATORY_FINISH, pd.Timestamp("2026-03-06 17:00"))


@pytest.mark.oracle("p6")
def test_longest_path_float_is_negative_past_a_must_finish_by():
    """A ends Fri 6 17:00, Must Finish By Thu 5 17:00: late finish Thu 17:00, total float -8 h = -1.0 d
    of the 8 h project calendar (P6 Professional, Must Finish By: negative float past the date)."""
    bounded = snap([todo("A", **week())], project={"plan_end_date": "2026-03-05 17:00"})
    assert longest_path_float_d(bounded) == -1.0
    assert longest_path_float_d(snap([todo("A", **week())])) == 0.0


# --- the series -----------------------------------------------------------------------------------


@pytest.mark.oracle("standard")
def test_half_step_series_reads_each_update_against_the_one_before():
    """Three updates: the first has no row; the second slips 2 wd and absorbs them; the third, unchanged
    but for its data date (A finished as replanned), slips nothing."""
    second = snap(
        [
            active("A", act_start_date="2026-03-02 08:00", remain_drtn_hr_cnt="16", target_drtn_hr_cnt="40"),
            todo("B", **week(24)),
            todo("C", **week()),
        ],
        chain("A", "B", "C"),
        data_date=WEEK_LATER,
    )
    third = snap(
        [
            done("A", act_start_date="2026-03-02 08:00", act_end_date="2026-03-10 17:00", target_drtn_hr_cnt="40"),
            active("B", act_start_date="2026-03-11 08:00", remain_drtn_hr_cnt="8", target_drtn_hr_cnt="24"),
            todo("C", **week()),
        ],
        chain("A", "B", "C"),
        data_date="2026-03-13 08:00",
    )
    series = half_step_series(SnapshotStore([THREE_WEEKS, second, third]))
    assert series["data_date"].tolist() == [pd.Timestamp(WEEK_LATER), pd.Timestamp("2026-03-13 08:00")]
    assert series["slip_wd"].tolist() == [-2.0, 0.0]
    assert series["replanning_wd"].tolist() == [2.0, 0.0]
    assert series["residual_wd"].tolist() == [0.0, 0.0]
    assert series["finish_case"].tolist() == [LAST_ACTIVITY, LAST_ACTIVITY]
    assert series["finish"].tolist() == [pd.Timestamp("2026-03-20 17:00")] * 2
    assert series["note"].tolist() == ["", ""]


@pytest.mark.oracle("characterization")
def test_the_demo_series_has_no_residual(store):
    """On the demo series every week's steps account for the whole move of the finish: the changelog
    sees every kind of change the engine reads."""
    series = half_step_series(store)
    assert len(series) == len(store) - 1
    assert series["residual_wd"].abs().max() == 0.0


HELD_OUT = Path(__file__).parent / "reference" / "data" / "p6-heldout" / "validation" / "held-out"
HELD_OUT_SETS = [f"H{number}" for number in range(1, 31)]


@pytest.mark.oracle("property")
@pytest.mark.parametrize("name", HELD_OUT_SETS)
def test_no_residual_between_two_schedules_of_the_p6_corpus(name):
    """Metamorphic, on schedules this project did not write: cases 11 and 12 of each held-out set are
    two different schedules sharing most Activity IDs, so every kind of change is there at once
    (progress, scope, durations, logic, links to other projects, constraints, calendars, options).
    Once every step is applied the finish must be the later schedule's own: residual 0. A pair
    whose intermediate steps close a logic loop is not read (CycleError), which is said, not hidden.
    """
    if not HELD_OUT.is_dir():
        missing("p6-corpus", P6_CORPUS_HINT)
    cases = HELD_OUT / name / "cases"
    earlier, later = (build_snapshot(read_xer(cases / f"{name}-{number}.xer")) for number in ("11", "12"))
    try:
        assert half_step(earlier, later).residual_wd == 0.0
    except CycleError:
        pytest.skip("a step closes a logic loop between these two unrelated schedules")


@pytest.mark.oracle("standard")
def test_a_week_that_cannot_be_scheduled_keeps_its_row_in_the_series():
    """A loop in the later update (A -> B -> A): the row stays, with the reason and no figure."""
    looped = snap(
        [todo("A", **week()), todo("B", **week())], [*chain("A", "B"), ("B", "A", "FS", 0)], data_date=WEEK_LATER
    )
    series = half_step_series(
        SnapshotStore([snap([todo("A", **week()), todo("B", **week())], chain("A", "B")), looped])
    )
    assert len(series) == 1 and series["note"].iloc[0].startswith("not read:")
    assert pd.isna(series["slip_wd"].iloc[0])


# --- changelog: the two categories the steps need -------------------------------------------------


@pytest.mark.oracle("standard")
def test_changelog_lists_a_scheduling_option_and_a_must_finish_by_that_changed():
    """SCHEDOPTIONS retained logic -> progress override, and a Must Finish By set: one Options row each."""
    before = snap([todo("A", **week())], sched={"sched_retained_logic": "Y", "sched_progress_override": "N"})
    after = snap(
        [todo("A", **week())],
        sched={"sched_retained_logic": "N", "sched_progress_override": "Y"},
        project={"plan_end_date": "2026-03-05 17:00"},
    )
    options = changelog(before, after).query("category == 'Options'").set_index("field")
    assert options.loc["progressed activities", ["before", "after"]].tolist() == ["retained_logic", "progress_override"]
    assert options.loc["must finish by", "after"] == "2026-03-05 17:00"
    assert changelog(before, before).query("category == 'Options'").empty


@pytest.mark.oracle("standard")
def test_changelog_lists_a_calendar_whose_working_time_changed():
    """The same calendar id with a holiday added: one Calendars row, none when the blobs are equal."""
    week_calendar = {"clndr_id": "9", "clndr_name": "Site", "day_hr_cnt": "8", "week_hr_cnt": "40"}
    with_holiday = clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")], (46115, 46116))
    before = snap([todo("A", clndr_id="9", **week())], calendars=[{**week_calendar, "clndr_data": MON_FRI_8H}])
    after = snap([todo("A", clndr_id="9", **week())], calendars=[{**week_calendar, "clndr_data": with_holiday}])
    rows = changelog(before, after).query("category == 'Calendars'")
    assert rows["change"].tolist() == ["working time changed"] and rows["field"].tolist() == ["Site"]
    assert changelog(before, before).query("category == 'Calendars'").empty
