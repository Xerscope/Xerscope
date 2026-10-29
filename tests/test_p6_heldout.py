"""xerscope's CPM against P6 Professional 23.12.1 on the held-out corpus (cpp-cpm-engine).

The strongest evidence this project has on progressed, constrained and resource-loaded
work: P6's own early/late dates and floats, read back from its database after F9, on
schedules frozen before P6 saw them (tests/reference/fetch_p6_heldout.py).

The engine does not yet reproduce P6 on every shape the corpus draws. FLOORS records the
share of values identical at the last measurement, per set: a change that lowers one
fails here, and a change that raises one should raise the floor. The aim is 1.0 everywhere.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pandas as pd
import pytest

HELD_OUT = Path(__file__).parent / "reference" / "data" / "p6-heldout" / "validation" / "held-out"

FLOORS = {
    "H1": 0.81,
    "H2": 0.80,
    "H3": 0.94,
    "H4": 0.84,
    "H5": 0.89,
    "H6": 0.95,
    "H7": 0.91,
    "H8": 0.80,
    "H9": 0.86,
    "H10": 0.63,
    "H11": 0.70,
    "H12": 0.54,
    "H13": 0.68,
    "H14": 0.54,
    "H15": 0.60,
    "H16": 0.54,
    "H17": 0.69,
    "H18": 0.76,
    "H19": 0.74,
    "H20": 0.71,
    "H21": 0.61,
    "H22": 0.46,
    "H23": 0.55,
    "H24": 0.41,
    "H25": 0.50,
    "H26": 0.48,
    "H27": 0.49,
    "H28": 0.48,
    "H29": 0.48,
    "H30": 0.57,
}

DATES = ["early_start", "early_finish", "late_start", "late_finish"]


@pytest.fixture(scope="module")
def corpus():
    if not HELD_OUT.is_dir():
        pytest.skip("P6 held-out corpus missing: uv run python tests/reference/fetch_p6_heldout.py")
    return HELD_OUT


@functools.cache
def _score(name: str) -> pd.DataFrame:
    from xerscope.crosscheck import p6_heldout_score

    return p6_heldout_score(HELD_OUT / name)


@pytest.mark.reference
@pytest.mark.parametrize("name", list(FLOORS))
def test_share_of_values_identical_to_p6_never_drops(corpus, name):
    d = _score(name)
    errors = d[d["field"] == "error"]
    assert errors.empty, errors[["case", "xerscope"]].to_string()
    rate = d["agree"].mean()
    assert rate >= FLOORS[name] - 1e-9, f"{name}: {rate:.4f} < floor {FLOORS[name]}"


def _p6_results(set_dir: Path) -> pd.DataFrame:
    res = pd.read_csv(set_dir / "p6-results.csv")
    for c in DATES:
        res[c] = pd.to_datetime(res[c])
    return res


@pytest.mark.reference
def test_float_type_codes_read_as_p6_does(corpus):
    """Which float P6 reports under each ``sched_float_type`` code, measured on P6's own
    dates (nothing of xerscope's CPM is involved), on the resource-dependent work of
    H8-H30, the only place start float and finish float differ. ``FT_FF`` is the finish
    float, ``FT_SS`` (the code the Schedule Options dialog writes for "Start Float") the
    start float, ``FT_Min`` the smaller; ``FT_Start``, an imported code P6 keeps, comes out
    as the finish float most of the time. The engine's FLOAT_TYPE table must say the same."""
    from xerscope.analysis.cpm import FLOAT_TYPE, _Axes, _date_range
    from xerscope.xer import load_snapshot

    hits: dict[str, dict[str, int]] = {}
    for i in range(8, 31):
        set_dir = corpus / f"H{i}"
        for case, g in _p6_results(set_dir).groupby("case"):
            snap = load_snapshot(set_dir / "cases" / f"{case}.xer")
            code = (snap.options.get("sched") or {}).get("sched_float_type") or "FT_FF"
            axes = _Axes(snap, *_date_range(snap))
            t = snap.activities.drop_duplicates("task_code").set_index("task_code")
            for r in g.itertuples():
                if r.task_code not in t.index or r.status == "TK_Complete":
                    continue
                if t.at[r.task_code, "task_type"] != "TT_Rsrc":
                    continue
                ax = axes.of(t.at[r.task_code, "clndr_id"])
                fin = ax.between(r.early_finish, r.late_finish) / 60
                st = ax.between(r.early_start, r.late_start) / 60
                h = hits.setdefault(code, {"n": 0, "finish": 0, "start": 0, "min": 0})
                h["n"] += 1
                for name, v in (("finish", fin), ("start", st), ("min", min(fin, st))):
                    h[name] += abs(v - float(r.total_float_hr)) < 0.01
    share = {code: {k: v / h["n"] for k, v in h.items() if k != "n"} for code, h in hits.items()}
    assert share["FT_FF"]["finish"] == 1.0, share["FT_FF"]
    assert share["FT_SS"]["start"] == 1.0, share["FT_SS"]
    assert share["FT_Min"]["min"] >= 0.96 and share["FT_Min"]["min"] == max(share["FT_Min"].values()), share["FT_Min"]
    assert share["FT_Start"]["finish"] == max(share["FT_Start"].values()), share["FT_Start"]
    for code, best in {"FT_FF": "finish", "FT_SS": "start", "FT_Min": "min", "FT_Start": "finish"}.items():
        assert FLOAT_TYPE[code] == best


@pytest.mark.reference
def test_total_float_agrees_wherever_the_four_dates_do(corpus):
    """An activity whose early and late dates are P6's has P6's total float too, under
    FT_FF and FT_SS (the codes P6 itself writes). The float-type reading is then the only
    thing between the dates and the float, and it must be right. (FT_Min, FT_Start and
    FT_Total on resource-dependent work still differ in a few cases: register R7.)"""
    d = pd.concat([_score(f"H{i}") for i in range(1, 31)], ignore_index=True)
    d = d[d["field"] != "error"]
    w = d.pivot_table(index=["set", "case", "task_code", "options"], columns="field", values="agree", aggfunc="first")
    w = w.reset_index()
    code = w["options"].str.split().str[1]
    w = w[code.isin(["FT_FF", "FT_SS"]) & w[DATES].all(axis=1)]
    assert len(w) > 2000
    bad = w[~w["total_float_hr"].astype(bool)]
    assert bad.empty, bad[["set", "case", "task_code", "options"]].to_string(index=False)


# One corpus activity per rule the engine took from P6 against MPXJ or its own earlier
# reading (docs/review-2026-10-29.md, R1-R9): the value named must be P6's. The ratchet above
# would absorb a regression on one activity; this names it.
PINNED = {
    "R2 SF from a started predecessor applies": [("H1", "H1-08", "A1240", "early_start")],
    "R3 expected finish before the early start: remaining 0": [("H1", "H1-02", "A1170", "early_finish")],
    "R3 expected finish with an FF predecessor, later than its bound": [("H4", "H4-10", "A1040", "early_finish")],
    "R3 FF bound later than the expected finish wins, remaining kept": [("H24", "H24-07", "A1210", "early_start")],
    "R5 Mandatory Finish before the data date: early dates at the data date, late pinned": [
        ("H3", "H3-04", "A1100", "early_start"),
        ("H3", "H3-04", "A1100", "late_finish"),
    ],
    "R5 Mandatory Start before the data date: early start at the data date": [("H2", "H2-06", "A1130", "early_start")],
    "R5 Mandatory Start pins the early start over later logic": [("H2", "H2-07", "A1120", "early_start")],
    "R5 expected finish earlier than the Mandatory Finish is the late finish": [
        ("H22", "H22-06", "A1120", "late_finish")
    ],
    "R9a FS lag to a finished successor passes back in full": [("H1", "H1-08", "A1020", "late_finish")],
    "R9a SS lag to a finished successor passes back unexpired only": [("H6", "H6-07", "A1030", "late_start")],
    "R9a lag between two finished activities does not pass back": [("H1", "H1-08", "A1050", "late_finish")],
    "R9b progress override: FS into a started successor binds no late date": [("H5", "H5-06", "A1030", "late_finish")],
    "R9b progress override: FF into a started successor still binds": [("H3", "H3-03", "A1030", "late_finish")],
    "R6 progress override: free float of started work runs past finished successors": [
        ("H2", "H2-05", "A1030", "free_float_hr")
    ],
    "R6 progress override: free float of started work runs past its SS links": [
        ("H2", "H2-04", "A1110", "free_float_hr")
    ],
}


@pytest.mark.reference
@pytest.mark.parametrize("rule", list(PINNED))
def test_rule_reproduces_p6_on_its_corpus_witness(corpus, rule):
    for set_name, case, code, field in PINNED[rule]:
        d = _score(set_name)
        row = d[(d["case"] == case) & (d["task_code"] == code) & (d["field"] == field)]
        assert len(row) == 1, (case, code, field)
        r = row.iloc[0]
        assert r["agree"], f"{rule}: {case} {code} {field}: P6 {r['p6']}, xerscope {r['xerscope']}"
