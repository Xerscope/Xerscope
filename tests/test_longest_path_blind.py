"""Longest path compared in working time, as P6 Professional defines it.

P6 Professional, Schedule Options, "Define critical activities as: Longest Path"
(https://docs.oracle.com/cd/G18296_01/client_help/en_US/): the longest path is the chain of
activities driving the project finish through driving relationships; a relationship drives
when the successor cannot start (or finish) earlier because of it, i.e. its relationship free
float is zero in working time.

Calendar C8 (tests/xerkit.py): Mon-Fri 08:00-12:00 / 13:00-17:00, holiday Fri 2026-04-03.
Fri 17:00 and the next Mon 08:00 are the same working instant: no working minute between them.
"""

import pandas as pd
from xerkit import FM, hours, snap, todo

from xerscope.analysis.cpm import schedule

T = pd.Timestamp


def frame(tasks, preds, **kw):
    return schedule(snap(tasks, preds, **kw)).frame


def test_fs_over_weekend_is_driving():
    """A (40 h) from Mon 2026-03-02 08:00 finishes Fri 03-06 17:00 (5 days x 8 h).
    B (8 h) FS 0 starts at the first working instant after Fri 17:00: Mon 03-09 08:00,
    finishes Mon 17:00; Z (finish milestone) Mon 17:00.
    Working minutes between A.EF (Fri 17:00) and B.ES (Mon 08:00) on C8: 0 -> A->B drives.
    B.EF = Z.EF -> B->Z drives. Longest path: A, B, Z."""
    f = frame(
        [todo("A", **hours(40)), todo("B", **hours(8)), todo("Z", **FM)],
        [("A", "B", "FS", 0), ("B", "Z", "FS", 0)],
    )
    assert f.loc["A", "ef"] == T("2026-03-06 17:00")
    assert f.loc["B", "es"] == T("2026-03-09 08:00")
    assert f.loc[["A", "B", "Z"], "longest_path"].tolist() == [True, True, True]


def test_one_hour_gap_is_not_driving():
    """Same chain, B held by Start On or After Mon 03-09 09:00 (CS_MSOA).
    A.EF Fri 17:00; B.ES Mon 09:00. Working time between them on C8: Mon 08:00-09:00 = 1 h.
    Relationship free float A->B = 1 h > 0 -> A->B does not drive; B is driven by its
    constraint. B 8 h from Mon 09:00: 09-12 (3 h) + 13-17 (4 h) + Tue 08-09 (1 h) -> Tue 09:00.
    Longest path: B, Z; A off it."""
    f = frame(
        [
            todo("A", **hours(40)),
            todo("B", cstr_type="CS_MSOA", cstr_date="2026-03-09 09:00", **hours(8)),
            todo("Z", **FM),
        ],
        [("A", "B", "FS", 0), ("B", "Z", "FS", 0)],
    )
    assert f.loc["A", "ef"] == T("2026-03-06 17:00")
    assert f.loc["B", "es"] == T("2026-03-09 09:00")
    assert f.loc[["A", "B", "Z"], "longest_path"].tolist() == [False, True, True]


def test_fs_over_holiday_is_driving():
    """Data date Thu 2026-04-02 08:00. A (8 h) finishes Thu 04-02 17:00. Fri 04-03 is a C8
    holiday, then the weekend: B (8 h) FS 0 starts Mon 04-06 08:00.
    Working minutes between Thu 17:00 and Mon 08:00 on C8: 0 -> A->B drives.
    Longest path: A, B, Z."""
    f = frame(
        [todo("A", **hours(8)), todo("B", **hours(8)), todo("Z", **FM)],
        [("A", "B", "FS", 0), ("B", "Z", "FS", 0)],
        data_date="2026-04-02 08:00",
    )
    assert f.loc["A", "ef"] == T("2026-04-02 17:00")
    assert f.loc["B", "es"] == T("2026-04-06 08:00")
    assert f.loc[["A", "B", "Z"], "longest_path"].tolist() == [True, True, True]


def test_finish_milestone_at_next_morning_is_driven():
    """A (8 h) from Mon 2026-03-02 08:00 finishes Mon 17:00. Z (finish milestone) carries
    Finish On or After Tue 03-03 08:00 (CS_MEOA), so its finish is written Tue 08:00 or
    Mon 17:00, the same working instant on C8.
    Working minutes between A.EF (Mon 17:00) and Z.EF (Tue 08:00): 0 -> A->Z drives
    (the constraint ties with the relationship, it does not hold Z later).
    Longest path: A, Z."""
    f = frame(
        [todo("A", **hours(8)), todo("Z", cstr_type="CS_MEOA", cstr_date="2026-03-03 08:00", **FM)],
        [("A", "Z", "FS", 0)],
    )
    assert f.loc["A", "ef"] == T("2026-03-02 17:00")
    assert f.loc["Z", "ef"] in (T("2026-03-02 17:00"), T("2026-03-03 08:00"))
    assert f.loc[["A", "Z"], "longest_path"].tolist() == [True, True]


def test_predecessor_on_other_calendar_read_on_successor_calendar():
    """A on C7D (7 days, 08:00-16:00), 48 h from Mon 2026-03-02 08:00: 6 days -> Sat 03-07 16:00.
    B on C8 (8 h) FS 0: first C8 working instant after Sat 16:00 is Mon 03-09 08:00.
    On B's calendar (C8) Sat 16:00 -> Mon 08:00 holds 0 working minutes -> A->B drives.
    (On A's calendar C7D the gap would be Sun 08:00-16:00 = 8 h, i.e. not driving: the
    definition "B cannot start earlier because of A" settles it, B has no other driver.)
    Longest path: A, B, Z."""
    f = frame(
        [todo("A", clndr_id="C7D", **hours(48)), todo("B", **hours(8)), todo("Z", **FM)],
        [("A", "B", "FS", 0), ("B", "Z", "FS", 0)],
    )
    assert f.loc["A", "ef"] == T("2026-03-07 16:00")
    assert f.loc["B", "es"] == T("2026-03-09 08:00")
    assert f.loc[["A", "B", "Z"], "longest_path"].tolist() == [True, True, True]


def test_two_open_ends_at_same_working_instant_both_drive():
    """Two chains, no common successor. A (40 h, C8) alone, from Mon 2026-03-02 08:00:
    EF Fri 03-06 17:00. B (40 h, C8, same start) EF Fri 17:00 -> M (finish milestone) FS 0:
    EF Fri 17:00 (or Mon 03-09 08:00, the same working instant on C8).
    Project finish = latest EF = Fri 17:00 = Mon 08:00 in working time.
    The longest path starts from every activity whose EF is the project finish, compared in
    working time: A (0 working minutes before it) and M both qualify; B drives M (0 gap).
    Longest path: A, B, M."""
    f = frame(
        [todo("A", **hours(40)), todo("B", **hours(40)), todo("M", **FM)],
        [("B", "M", "FS", 0)],
    )
    assert f.loc["A", "ef"] == T("2026-03-06 17:00")
    assert f.loc["B", "ef"] == T("2026-03-06 17:00")
    assert f.loc["M", "ef"] in (T("2026-03-06 17:00"), T("2026-03-09 08:00"))
    assert f.loc[["A", "B", "M"], "longest_path"].tolist() == [True, True, True]


# Maintainer reading (08/11), to test in P6 (plan, P6 measurement 6.5).
def test_open_end_at_friday_evening_drives_milestone_written_monday_morning():
    """Same two chains, M held by Finish On or After Mon 2026-03-09 08:00 (CS_MEOA), so its
    finish may be written Mon 08:00. A EF Fri 03-06 17:00, B EF Fri 17:00.
    Project finish = Mon 08:00 = Fri 17:00 in working time on C8 (0 working minutes between).
    A finishes at the project finish in working time -> A on the longest path; B->M gap 0 ->
    B drives M. Longest path: A, B, M."""
    f = frame(
        [
            todo("A", **hours(40)),
            todo("B", **hours(40)),
            todo("M", cstr_type="CS_MEOA", cstr_date="2026-03-09 08:00", **FM),
        ],
        [("B", "M", "FS", 0)],
    )
    assert f.loc["A", "ef"] == T("2026-03-06 17:00")
    assert f.loc["B", "ef"] == T("2026-03-06 17:00")
    assert f.loc["M", "ef"] in (T("2026-03-06 17:00"), T("2026-03-09 08:00"))
    assert f.loc[["A", "B", "M"], "longest_path"].tolist() == [True, True, True]


# Maintainer reading (08/11), to test in P6 (plan, P6 measurement 6.5).
def test_open_end_before_a_finish_milestone_on_another_calendar_is_read_as_driving_with_a_warning():
    """A on C8 finishes Fri 2026-03-06 17:00 (open end). M, the finish milestone, is on C7D and
    held to Mon 03-09 08:00: no working minute between on A's calendar, Sat-Sun on M's. The gap
    is read as 0 on A's calendar, A is on the longest path, and a warning names both calendars."""
    result = schedule(
        snap(
            [
                todo("A", **hours(40)),
                todo("B", **hours(40)),
                todo("M", clndr_id="C7D", cstr_type="CS_MEOA", cstr_date="2026-03-09 08:00", **FM),
            ],
            [("B", "M", "FS", 0)],
        )
    )
    f = result.frame
    assert f.loc["A", "ef"] == T("2026-03-06 17:00")
    assert f.loc["M", "ef"] == T("2026-03-09 08:00")
    assert f.loc["A", "longest_path"]
    warned = [w for w in result.warnings if w.startswith("A: on the longest path")]
    assert len(warned) == 1 and "to test in P6" in warned[0] and "M" in warned[0]


def test_open_end_before_a_finishing_task_needs_the_same_minute():
    """The project finish set by a task: equality to the minute only. A ends Fri 17:00; C ends
    Mon 03-09 09:00 (1 h after Mon 08:00): A is off the longest path, no warning."""
    result = schedule(
        snap(
            [todo("A", **hours(40)), todo("C", **hours(41))],
            [],
        )
    )
    f = result.frame
    assert f.loc["C", "ef"] == T("2026-03-09 09:00")
    assert not f.loc["A", "longest_path"] and f.loc["C", "longest_path"]
    assert not any(w.startswith("A: on the longest path") for w in result.warnings)
