"""Characterization (golden) test: freeze what every built-in standard reports today.

A refactor must change no number. Each metric of each built-in standard is run on the demo
series (no baseline, then with the planned-dates baseline, then with the first update as
baseline: the three ways `xerscope check` can be called) and on the pinned third-party XER
files; status, counts, value and the identifiers of the flagged items are compared with
tests/golden/standards.json. Activity names are never stored. After an intended change,
regenerate with XERSCOPE_UPDATE_GOLDEN=1 (that run always fails, by design) and review the diff.
"""

import json
import math
import os
from pathlib import Path

import pytest
from conftest import REFERENCE_HINT, missing
from reference.sources import FILES

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.xer import load_snapshot

GOLDEN = Path(__file__).parent / "golden" / "standards.json"
REFERENCE_DATA = Path(__file__).parent / "reference" / "data"
# 4,217 activities: would dominate the runtime, and the CPM tests already cover it.
EXCLUDED_REFERENCE = frozenset({"p6viewer/Hotel Project.xer"})
SHOWN_DIFFS = 20
# Float noise below this is not a behaviour change.
VALUE_DECIMALS = 6


def flagged_identifiers(flagged) -> list[str]:
    """Task codes, or "pred->succ" for relationship rows; never names."""
    if "pred_code" in flagged and "succ_code" in flagged:
        pairs = zip(flagged["pred_code"], flagged["succ_code"], strict=True)
        return sorted(f"{p}->{s}" for p, s in pairs)
    if "task_code" in flagged:
        return sorted(str(c) for c in flagged["task_code"])
    # Counts still pin a rule whose rows carry neither id column.
    return []


def plain_number(number):
    """numpy scalar -> Python scalar, NaN -> None, so the JSON round-trip is exact."""
    if number is None:
        return None
    if hasattr(number, "item"):
        number = number.item()
    if isinstance(number, float) and math.isnan(number):
        return None
    return number


def plain_value(value):
    value = plain_number(value)
    return None if value is None else round(float(value), VALUE_DECIMALS)


def entry_of(result) -> dict:
    return {
        "status": result.status,
        "numerator": plain_number(result.numerator),
        "denominator": plain_number(result.denominator),
        "value": plain_value(result.value),
        "flagged": flagged_identifiers(result.flagged),
        # Only an error carries a note worth freezing: a changed exception must show.
        "note": result.note if result.status == "error" else None,
    }


def observe(snapshot, store=None, baseline=None) -> dict:
    """{standard id/metric id: entry} for one snapshot."""
    observed = {}
    for std_id, std in builtin_standards().items():
        for result in run_standard(std, AnalysisContext(snapshot, store, baseline)):
            observed[f"{std_id}/{result.metric.id}"] = entry_of(result)
    return observed


def observe_series(store, baseline_of=lambda snapshot: None) -> dict:
    """Every snapshot of the demo series, with the series so previous-update checks run."""
    return {Path(s.source).name: observe(s, store, baseline_of(s)) for s in store}


def reference_names() -> list[str]:
    return sorted(name for name in FILES if name.endswith(".xer") and name not in EXCLUDED_REFERENCE)


def observe_reference_files(names: list[str]) -> dict:
    return {name: observe(load_snapshot(REFERENCE_DATA / name)) for name in names}


def flatten(observed: dict) -> dict:
    return {f"{file}/{key}": entry for file, per_file in observed.items() for key, entry in per_file.items()}


def differences(expected: dict, actual: dict) -> list[str]:
    exp, act = flatten(expected), flatten(actual)
    return [
        f"{key}: golden={exp.get(key)} now={act.get(key)}"
        for key in sorted(exp.keys() | act.keys())
        if exp.get(key) != act.get(key)
    ]


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}


def update_requested() -> bool:
    return os.environ.get("XERSCOPE_UPDATE_GOLDEN") == "1"


def update_golden(section: str, observed: dict) -> None:
    """Write the section, prove it reads back unchanged, and fail so it never passes green."""
    golden = load_golden()
    golden[section] = observed
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(golden, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    assert load_golden()[section] == observed, f"section {section!r} does not survive the JSON round-trip"
    pytest.fail(
        f"golden section {section!r} rewritten in {GOLDEN.name}; rerun without XERSCOPE_UPDATE_GOLDEN",
        pytrace=False,
    )


def assert_matches_golden(section: str, observed: dict) -> None:
    diffs = differences(load_golden().get(section, {}), observed)
    shown = "\n".join(diffs[:SHOWN_DIFFS])
    assert not diffs, f"{len(diffs)} entries differ from {GOLDEN.name} (first {SHOWN_DIFFS}):\n{shown}"


def check_against_golden(section: str, observed: dict) -> None:
    if update_requested():
        update_golden(section, observed)
    else:
        assert_matches_golden(section, observed)


def test_demo_series_matches_golden(store):
    check_against_golden("demo", observe_series(store))


def test_demo_planned_baseline_matches_golden(store):
    check_against_golden("demo-planned", observe_series(store, Baseline.planned))


def test_demo_first_as_baseline_matches_golden(store):
    first = Baseline.from_snapshot(store.first)
    check_against_golden("demo-first-as-baseline", observe_series(store, lambda _snapshot: first))


def test_reference_files_match_golden():
    names = reference_names()
    if not all((REFERENCE_DATA / name).exists() for name in names):
        missing("reference", REFERENCE_HINT)
    check_against_golden("reference", observe_reference_files(names))
