"""Half-step reading of one activity (analysis/activity_forensics.py): hand-checked shifts, invariants.

Source: AACE RP 29R-03 (rev. April 25, 2011) MIP 3.4.K.4, the half-stepped update analysis, read on
one activity's early finish.

Every schedule is on the C8 calendar (Mon-Fri, 08:00-12:00 and 13:00-17:00), data date
Monday 2 March 2026 08:00 unless stated: a 40 h activity runs Monday to Friday 17:00.
"""

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis.activity_forensics import (
    EARLIER_UPDATE,
    LATER_UPDATE,
    activity_half_step,
    activity_half_step_series,
)
from xerscope.store import SnapshotStore

WEEK_LATER = "2026-03-09 08:00"  # the Monday after the default data date


def week(duration_hr: int = 40) -> dict:
    return dict(target_drtn_hr_cnt=str(duration_hr), remain_drtn_hr_cnt=str(duration_hr))


def shifts(read) -> dict[str, float]:
    return read.steps.set_index("step")["shift_wd"].to_dict()


A_THEN_B = [("A", "B", "FS", 0)]


@pytest.mark.oracle("standard")
def test_progress_alone_moves_the_activity_at_the_progress_step():
    """B follows A, 40 h each, neither started a week later (status date Mon 9).

    Earlier: A Mon 2 - Fri 6, B Mon 9 - Fri 13 17:00. Later: A Mon 9 - Fri 13, B Mon 16 - Fri 20 17:00.
    B's finish moves 5 wd at progress and by nothing else; A drives B in both updates.
    """
    earlier = snap([todo("A", **week()), todo("B", **week())], A_THEN_B)
    later = snap([todo("A", **week()), todo("B", **week())], A_THEN_B, data_date=WEEK_LATER)
    read = activity_half_step(earlier, later, "B")
    assert read.old_finish == pd.Timestamp("2026-03-13 17:00")
    assert read.new_finish == pd.Timestamp("2026-03-20 17:00")
    assert shifts(read)["progress"] == -5.0 and read.replanning_wd == 0.0 and read.residual_wd == 0.0
    assert read.driving_before == read.driving_after == ["A"]


@pytest.mark.oracle("standard")
def test_the_engine_gap_tells_when_the_stored_finish_is_not_reproduced():
    """Boundary: A (40 h) recalculates to Fri 6 17:00. Stored Fri 6 18:00 (no working time after 17:00)
    is reproduced, gap 0; stored Fri 13 17:00 is 5 wd later than the recalculation, gap +5 (recalculated
    earlier reads positive), and the reading says its shifts may be the engine's."""
    reproduced = snap([todo("A", early_end_date="2026-03-06 18:00", **week())])
    stored_late = snap([todo("A", early_end_date="2026-03-13 17:00", **week())])
    same = activity_half_step(reproduced, reproduced, "A")
    assert same.old_engine_gap_wd == same.new_engine_gap_wd == 0.0 and same.is_finish_reproduced
    gapped = activity_half_step(reproduced, stored_late, "A")
    assert gapped.new_engine_gap_wd == 5.0 and not gapped.is_finish_reproduced


@pytest.mark.oracle("standard")
def test_a_remaining_duration_increased_without_percent_change_is_read_at_the_durations_step():
    """A started Mon 2 keeps 40 h left in the earlier update and has 48 h left a week later; B follows A.

    Progress alone: A's 40 h run from Mon 9 to Fri 13, B Mon 16 - Fri 20 17:00 (5 wd lost). Durations:
    48 h = 6 days, A ends Mon 16 17:00, B runs Tue 17 - Mon 23 17:00 (1 wd more).
    """
    started = dict(act_start_date="2026-03-02 08:00", target_drtn_hr_cnt="40")
    earlier = snap([active("A", remain_drtn_hr_cnt="40", **started), todo("B", **week())], A_THEN_B)
    later = snap([active("A", remain_drtn_hr_cnt="48", **started), todo("B", **week())], A_THEN_B, data_date=WEEK_LATER)
    read = activity_half_step(earlier, later, "B")
    assert shifts(read)["progress"] == -5.0 and shifts(read)["durations"] == -1.0
    assert read.new_finish == pd.Timestamp("2026-03-23 17:00") and read.residual_wd == 0.0
    assert read.steps.set_index("step").loc["durations", "changes"] == 0  # the revision is on A, not on B
    assert "A" in set(read.changes["task_code"])  # and the changelog rows of the driving predecessor say so


@pytest.mark.oracle("standard")
def test_a_link_added_that_becomes_driving_is_read_at_the_logic_step():
    """A and B in parallel end Fri 6; with A -> B added, B runs Mon 9 - Fri 13: 5 wd lost at logic alone.

    No driving predecessor before; A after. The added link is among the changelog rows of B.
    """
    earlier = snap([todo("A", **week()), todo("B", **week())])
    later = snap([todo("A", **week()), todo("B", **week())], A_THEN_B)
    read = activity_half_step(earlier, later, "B")
    assert shifts(read)["logic"] == -5.0 and shifts(read)["progress"] == 0.0 and read.residual_wd == 0.0
    assert read.driving_before == [] and read.driving_after == ["A"]
    assert read.steps.set_index("step").loc["logic", "changes"] == 1
    assert (read.changes["category"] == "Relationships").any()


@pytest.mark.oracle("standard")
def test_a_constraint_added_is_read_at_the_constraints_step():
    """Start On Mon 9 on A: A runs Mon 9 - Fri 13 instead of Mon 2 - Fri 6, 5 wd lost at constraints."""
    earlier = snap([todo("A", **week())])
    later = snap([todo("A", cstr_type="CS_MSO", cstr_date="2026-03-09 08:00", **week())])
    read = activity_half_step(earlier, later, "A")
    assert shifts(read)["constraints"] == -5.0 and read.slip_wd == 0.0 and read.residual_wd == 0.0


@pytest.mark.oracle("standard")
def test_an_activity_absent_from_the_later_update_is_a_result_not_a_crash():
    """B deleted in the later update: no figure, the update that lacks it named."""
    earlier = snap([todo("A", **week()), todo("B", **week())])
    later = snap([todo("A", **week())])
    read = activity_half_step(earlier, later, "B")
    assert read.missing_from == LATER_UPDATE and read.steps.empty and read.old_finish is None
    assert activity_half_step(later, earlier, "B").missing_from == EARLIER_UPDATE
    assert activity_half_step(earlier, later, "NOWHERE").missing_from == f"{EARLIER_UPDATE} and {LATER_UPDATE}"


@pytest.mark.oracle("property")
def test_the_steps_and_the_residual_add_up_to_the_move_of_the_activity():
    """Metamorphic (3.4.K.4.f): every kind of change at once on C, the shifts sum to the move between its
    two recalculated early finishes on its calendar in the later update."""
    earlier = snap(
        [todo("A", **week()), todo("B", **week()), todo("C", **week())], [("A", "B", "FS", 0), ("B", "C", "FS", 0)]
    )
    later = snap(
        [
            done("A", act_start_date="2026-03-02 08:00", act_end_date="2026-03-04 17:00", target_drtn_hr_cnt="40"),
            todo("B", cstr_type="CS_MSO", cstr_date="2026-03-16 08:00", **week(60)),
            todo("C", **week(16)),
        ],
        [("A", "B", "FS", 0), ("B", "C", "SS", 8)],
        data_date=WEEK_LATER,
    )
    read = activity_half_step(earlier, later, "C")
    move_wd = 0.0 - later.activity_working_days(None, read.old_finish, read.new_finish)
    assert read.total_shift_wd == pytest.approx(move_wd, abs=0.01)
    assert read.residual_wd == 0.0


@pytest.mark.oracle("standard")
def test_a_status_date_on_a_non_working_day_counts_the_week_in_working_days():
    """Boundary: status date Saturday 7 March 08:00. A (40 h, not started) runs from the next working
    time, Mon 9 - Fri 13 17:00, against Mon 2 - Fri 6: 5 wd lost, not the 7 calendar days of the gap."""
    earlier = snap([todo("A", **week())])
    later = snap([todo("A", **week())], data_date="2026-03-07 08:00")
    read = activity_half_step(earlier, later, "A")
    assert read.new_finish == pd.Timestamp("2026-03-13 17:00")
    assert shifts(read)["progress"] == -5.0 and read.residual_wd == 0.0


@pytest.mark.oracle("standard")
def test_the_series_has_one_row_per_pair_and_keeps_a_week_it_cannot_read():
    """Three updates: B read against the one before in each pair, a loop in the third has its row with the reason.

    First pair: B Fri 13 -> Fri 20 (progress, 5 wd lost). Second pair: B absent from the third update.
    """
    first = snap([todo("A", **week()), todo("B", **week())], A_THEN_B)
    second = snap([todo("A", **week()), todo("B", **week())], A_THEN_B, data_date=WEEK_LATER)
    third = snap([todo("A", **week())], data_date="2026-03-16 08:00")
    series = activity_half_step_series(SnapshotStore([first, second, third]), "B")
    assert len(series) == 2
    assert series.loc[0, "total_shift_wd"] == -5.0 and series.loc[0, "slip_wd"] == -5.0
    assert series.loc[0, "driving_predecessors"] == "A"
    assert series.loc[1, "note"] == f"missing from {LATER_UPDATE}" and pd.isna(series.loc[1, "finish"])
    looped = snap(
        [todo("A", **week()), todo("B", **week())], [*A_THEN_B, ("B", "A", "FS", 0)], data_date="2026-03-16 08:00"
    )
    broken = activity_half_step_series(SnapshotStore([first, looped]), "B")
    assert broken.loc[0, "note"].startswith("not read") and pd.isna(broken.loc[0, "finish"])


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(("finished", "driving"), [("2026-03-06 17:00", ["A"]), ("2026-03-04 17:00", [])])
def test_a_predecessor_that_finished_late_still_drives_its_successor(finished, driving):
    """Status date Mon 9 March 08:00; A is finished, B (40 h, not started) follows it FS.

    A finished Fri 6 17:00: no working time between A's finish and the status date, so A's link bounds
    B's start (Mon 9 08:00) and A drives B (Oracle P6 help, Driving relationships: the successor has no
    free float, no Start On / Finish On constraint, no actual finish; nothing excludes a finished
    predecessor). A finished Wed 4 17:00: B waits for the status date, not for A; A drives nothing.
    The longest path keeps its own rule: it traces unfinished work only.
    """
    earlier = snap([active("A", **week()), todo("B", **week())], A_THEN_B)
    a_done = done("A", act_start_date="2026-03-02 08:00", act_end_date=finished)
    later = snap([a_done, todo("B", **week())], A_THEN_B, data_date=WEEK_LATER)
    assert activity_half_step(earlier, later, "B").driving_after == driving


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(("retained", "override", "driving"), [("Y", "N", ["A"]), ("N", "Y", [])])
def test_work_under_way_has_no_driving_predecessor_under_progress_override(retained, override, driving):
    """B started (40 h left) out of sequence while A (40 h, not started) is still to come, A FS B.

    Retained Logic: B's remaining work waits for A (Mon 2 - Fri 6), A drives B. Progress Override:
    "network logic is ignored and the activity can progress without delay" (Oracle P6 Professional
    help, Schedule Options, General tab): B has no driving predecessor.
    """
    sched = {"sched_retained_logic": retained, "sched_progress_override": override}
    schedule_of = snap([todo("A", **week()), active("B")], A_THEN_B, sched=sched)
    assert activity_half_step(schedule_of, schedule_of, "B").driving_after == driving


@pytest.mark.oracle("standard")
def test_a_finished_activity_has_no_driving_predecessor():
    """B finished: nothing drives it any more (Oracle: a driving relationship's successor has no actual
    finish), whatever its predecessor."""
    finished = snap(
        [done("A"), done("B", act_start_date="2026-02-16 08:00", act_end_date="2026-02-20 17:00")], A_THEN_B
    )
    assert activity_half_step(finished, finished, "B").driving_after == []
