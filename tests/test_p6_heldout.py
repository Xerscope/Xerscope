"""xerscope's CPM against P6 Professional 23.12.1 on the held-out corpus (cpp-cpm-engine).

The strongest evidence this project has on progressed, constrained and resource-loaded
work: P6's own early/late dates and floats, read back from its database after F9, on
schedules frozen before P6 saw them (tests/reference/fetch_p6_heldout.py).

The engine does not yet reproduce P6 on every shape the corpus draws. FLOORS records the
share of values identical at the last measurement, per set: a change that lowers one
fails here, and a change that raises one should raise the floor. The aim is 1.0 everywhere.
"""

from __future__ import annotations

from pathlib import Path

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


@pytest.fixture(scope="module")
def corpus():
    if not HELD_OUT.is_dir():
        pytest.skip("P6 held-out corpus missing: uv run python tests/reference/fetch_p6_heldout.py")
    return HELD_OUT


@pytest.mark.reference
@pytest.mark.parametrize("name", list(FLOORS))
def test_share_of_values_identical_to_p6_never_drops(corpus, name):
    from xerscope.crosscheck import p6_heldout_score

    d = p6_heldout_score(corpus / name)
    errors = d[d["field"] == "error"]
    assert errors.empty, errors[["case", "xerscope"]].to_string()
    rate = d["agree"].mean()
    assert rate >= FLOORS[name] - 1e-9, f"{name}: {rate:.4f} < floor {FLOORS[name]}"
