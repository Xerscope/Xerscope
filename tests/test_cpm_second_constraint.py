"""Only the primary constraint pins: what the second constraint does beside it (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the pinned corpus. Probes xf-mandatory, rule PC
(projects ZZ-CPP-XQR, -XQO, -XQN, activities Q7 to Q10): "only the primary constraint pins; a
second constraint caps the late dates, a Mandatory Start or Mandatory Finish in the second slot as
a Start On or Before or a Finish On or Before does". Held-out corpus, 140 activities with a
mandatory date in the second slot, e.g. H28-07 A1210 and H29-12 A1110 (Start On or After, then
Mandatory Finish), H27-08 A1250 (Start On or After, then Mandatory Start), H26-08 A1280 and H23-02
A1230 (Mandatory Start, then Mandatory Finish), H24-05 A1350 (two Mandatory Starts), H27-11 A1060
(Finish On or Before, then Mandatory Finish), and H24-04 A1210 (Mandatory Start, then a later Start
On or After). The project's reference, 26.8, is not measured.
Rule, for work not started:
- a Mandatory Start / Finish in the second slot does not pin. It bounds as a Start On / Finish On:
  not before the date in the forward pass, not after it in the backward pass;
- the second constraint bounds on top of a primary Mandatory Start: the early dates take the later
  of the two, the late dates the earlier of the two.
Work under way is not concerned: a mandatory date bounds none of its late dates, in either slot.
The expected values below are hand calculations from that rule, not P6 readings.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. P (8 h) -> T (16 h, tested) -> S (8 h), all finish-to-start, lag
0. Z (80 h, no link) ends Fri 13 Mar 17:00, the project finish. P ends Mon 2 Mar 17:00, so the
logic lets T start Tue 3 Mar 08:00. Backward: S finishes at the latest Fri 13 Mar 17:00 and starts
Fri 13 Mar 08:00, so the network lets T finish Thu 12 Mar 17:00 at the latest.
"""

import pandas as pd
import pytest
from xerkit import active, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")


def row_of_t(task: dict, successor: dict | None = None) -> pd.Series:
    """The schedule row of ``task`` (code T) in P -> T -> S, with Z setting the project finish."""
    tasks = [todo("P", **hours(8)), task, successor or todo("S", **hours(8)), todo("Z", **hours(80))]
    return schedule(snap(tasks, [("P", "T", "FS", 0), ("T", "S", "FS", 0)])).frame.loc["T"]


def dates_of(row: pd.Series) -> dict:
    """Early start, early finish, late start, late finish as text, and the total float in hours."""
    return {name: str(row[name])[5:16] for name in ("es", "ef", "ls", "lf")} | {"tf_hr": row["tf_hr"]}


def test_mandatory_finish_in_the_second_slot_does_not_hold_the_early_finish():
    """Start On or After Wed 4 Mar 08:00, then Mandatory Finish Wed 4 Mar 17:00 (shape of H28-07 A1210).

    Forward: T starts Wed 4 Mar 08:00 and its 16 h end Thu 5 Mar 17:00, after the mandatory date.
    Backward: the date caps the late finish, Wed 4 Mar 17:00; late start 16 h before = Tue 3 Mar
    08:00. Total float = Thu 5 Mar 17:00 back to Wed 4 Mar 17:00 = -8 h.
    """
    task = todo("T", cstr_type="CS_MSOA", cstr_date="2026-03-04 08:00", cstr_type2="CS_MANDFIN",
                cstr_date2="2026-03-04 17:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-04 08:00", "ef": "03-05 17:00", "ls": "03-03 08:00", "lf": "03-04 17:00", "tf_hr": -8,
    }  # fmt: skip


def test_mandatory_finish_in_the_second_slot_leaves_the_late_finish_to_the_successor():
    """Start On or After Wed 4 Mar 08:00, then Mandatory Finish Wed 11 Mar 17:00; S must finish
    on or before Tue 10 Mar 17:00 (probe Q10, shape of H29-12 A1110).

    Forward: 16 h from Wed 4 Mar 08:00 end Thu 5 Mar 17:00; not before the mandatory date, so the
    finish moves to Wed 11 Mar 17:00 and the start to 16 h before, Tue 10 Mar 08:00.
    Backward: S starts at the latest Tue 10 Mar 08:00, so T finishes at the latest Mon 9 Mar
    17:00, before the mandatory date, which pins nothing; late start Fri 6 Mar 08:00.
    Total float = Wed 11 Mar 17:00 back to Mon 9 Mar 17:00 = -16 h.
    """
    task = todo("T", cstr_type="CS_MSOA", cstr_date="2026-03-04 08:00", cstr_type2="CS_MANDFIN",
                cstr_date2="2026-03-11 17:00", **hours(16))  # fmt: skip
    successor = todo("S", cstr_type="CS_MEOB", cstr_date="2026-03-10 17:00", **hours(8))
    assert dates_of(row_of_t(task, successor)) == {
        "es": "03-10 08:00", "ef": "03-11 17:00", "ls": "03-06 08:00", "lf": "03-09 17:00", "tf_hr": -16,
    }  # fmt: skip


def test_finish_on_or_before_then_mandatory_finish_follows_the_logic_forward():
    """Finish On or Before Mon 9 Mar 17:00, then Mandatory Finish Tue 3 Mar 17:00 (shape of H27-11 A1060).

    Forward: the logic starts T Tue 3 Mar 08:00, its 16 h end Wed 4 Mar 17:00. Backward: the
    earliest cap is the mandatory date, Tue 3 Mar 17:00; late start Mon 2 Mar 08:00.
    Total float = Wed 4 Mar 17:00 back to Tue 3 Mar 17:00 = -8 h.
    """
    task = todo("T", cstr_type="CS_MEOB", cstr_date="2026-03-09 17:00", cstr_type2="CS_MANDFIN",
                cstr_date2="2026-03-03 17:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-03 08:00", "ef": "03-04 17:00", "ls": "03-02 08:00", "lf": "03-03 17:00", "tf_hr": -8,
    }  # fmt: skip


def test_mandatory_start_in_the_second_slot_caps_the_late_start_and_holds_no_early_date():
    """Start On or After Wed 4 Mar 08:00, then Mandatory Start Tue 3 Mar 08:00 (shape of H27-08 A1250).

    Forward: the later of the logic and the two dates, Wed 4 Mar 08:00 to Thu 5 Mar 17:00.
    Backward: the start not after the second date, late start Tue 3 Mar 08:00, late finish 16 h
    later = Wed 4 Mar 17:00. Total float = Thu 5 Mar 17:00 back to Wed 4 Mar 17:00 = -8 h.
    """
    task = todo("T", cstr_type="CS_MSOA", cstr_date="2026-03-04 08:00", cstr_type2="CS_MANDSTART",
                cstr_date2="2026-03-03 08:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-04 08:00", "ef": "03-05 17:00", "ls": "03-03 08:00", "lf": "03-04 17:00", "tf_hr": -8,
    }  # fmt: skip


def test_mandatory_start_then_an_earlier_mandatory_finish_caps_the_late_dates():
    """Mandatory Start Thu 5 Mar 08:00, then Mandatory Finish Wed 4 Mar 17:00 (shape of H26-08 A1280).

    Forward: pinned at Thu 5 Mar 08:00, 16 h end Fri 6 Mar 17:00. Backward: the second date caps
    the late finish, Wed 4 Mar 17:00; late start 16 h before = Tue 3 Mar 08:00, earlier than the pin.
    Total float = Fri 6 Mar 17:00 back to Wed 4 Mar 17:00 = -16 h.
    """
    task = todo("T", cstr_type="CS_MANDSTART", cstr_date="2026-03-05 08:00", cstr_type2="CS_MANDFIN",
                cstr_date2="2026-03-04 17:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-05 08:00", "ef": "03-06 17:00", "ls": "03-03 08:00", "lf": "03-04 17:00", "tf_hr": -16,
    }  # fmt: skip


def test_mandatory_start_then_a_later_mandatory_finish_moves_the_early_dates_only():
    """Mandatory Start Wed 4 Mar 08:00, then Mandatory Finish Fri 6 Mar 17:00 (shape of H23-02 A1230).

    Forward: from the pin the 16 h end Thu 5 Mar 17:00; not before the second date, so the finish
    moves to Fri 6 Mar 17:00 and the start to Thu 5 Mar 08:00. Backward: the pin holds the late
    start, Wed 4 Mar 08:00, late finish Thu 5 Mar 17:00; the second date caps nothing earlier.
    Total float = Fri 6 Mar 17:00 back to Thu 5 Mar 17:00 = -8 h.
    """
    task = todo("T", cstr_type="CS_MANDSTART", cstr_date="2026-03-04 08:00", cstr_type2="CS_MANDFIN",
                cstr_date2="2026-03-06 17:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-05 08:00", "ef": "03-06 17:00", "ls": "03-04 08:00", "lf": "03-05 17:00", "tf_hr": -8,
    }  # fmt: skip


@pytest.mark.parametrize("second_type", ["CS_MANDSTART", "CS_MSOA"])
def test_a_later_start_date_in_the_second_slot_moves_the_early_dates_of_a_pinned_start(second_type):
    """Mandatory Start Wed 4 Mar 08:00, then a Mandatory Start or a Start On or After Thu 5 Mar
    08:00 (H24-05 A1350, H24-04 A1210).

    Forward: the later of the two, Thu 5 Mar 08:00 to Fri 6 Mar 17:00. Backward: the pin, late
    start Wed 4 Mar 08:00 and late finish Thu 5 Mar 17:00. Total float = -8 h.
    """
    task = todo("T", cstr_type="CS_MANDSTART", cstr_date="2026-03-04 08:00", cstr_type2=second_type,
                cstr_date2="2026-03-05 08:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-05 08:00", "ef": "03-06 17:00", "ls": "03-04 08:00", "lf": "03-05 17:00", "tf_hr": -8,
    }  # fmt: skip


def test_an_earlier_start_on_or_after_leaves_the_pinned_start_where_it_is():
    """Mandatory Start Thu 5 Mar 08:00, then Start On or After Wed 4 Mar 08:00: the pin both ways.

    Thu 5 Mar 08:00 to Fri 6 Mar 17:00 early and late, total float 0.
    """
    task = todo("T", cstr_type="CS_MANDSTART", cstr_date="2026-03-05 08:00", cstr_type2="CS_MSOA",
                cstr_date2="2026-03-04 08:00", **hours(16))  # fmt: skip
    assert dates_of(row_of_t(task)) == {
        "es": "03-05 08:00", "ef": "03-06 17:00", "ls": "03-05 08:00", "lf": "03-06 17:00", "tf_hr": 0,
    }  # fmt: skip


def test_a_primary_mandatory_finish_still_pins_against_the_successor():
    """Mandatory Finish Wed 11 Mar 17:00 alone; S must finish on or before Tue 10 Mar 17:00.

    Pinned in both passes: Tue 10 Mar 08:00 to Wed 11 Mar 17:00, though S would need Mon 9 Mar
    17:00. Total float 0. The same dates in the second slot give -16 h (the test above).
    """
    task = todo("T", cstr_type="CS_MANDFIN", cstr_date="2026-03-11 17:00", **hours(16))
    successor = todo("S", cstr_type="CS_MEOB", cstr_date="2026-03-10 17:00", **hours(8))
    assert dates_of(row_of_t(task, successor)) == {
        "es": "03-10 08:00", "ef": "03-11 17:00", "ls": "03-10 08:00", "lf": "03-11 17:00", "tf_hr": 0,
    }  # fmt: skip


def test_work_under_way_gets_no_cap_from_a_mandatory_finish_in_the_second_slot():
    """Under way since Mon 23 Feb 08:00, 16 h left, Start On or After then Mandatory Finish Tue 3
    Mar 17:00 (corpus: H28-03 A1410, H28-04 A1510).

    Retained logic: the remaining 16 h wait for P and run Tue 3 Mar 08:00 to Wed 4 Mar 17:00. The
    late finish is the network's, Thu 12 Mar 17:00, not the date: late start Wed 11 Mar 08:00,
    total float = Wed 4 Mar 17:00 to Thu 12 Mar 17:00 = 6 days = 48 h.
    """
    task = active("T", cstr_type="CS_MSOA", cstr_date="2026-02-23 08:00", cstr_type2="CS_MANDFIN",
                  cstr_date2="2026-03-03 17:00", remain_drtn_hr_cnt="16")  # fmt: skip
    row = row_of_t(task)
    assert (str(row["ls"])[5:16], str(row["lf"])[5:16], row["tf_hr"]) == ("03-11 08:00", "03-12 17:00", 48)
