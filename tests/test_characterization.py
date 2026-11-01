"""Characterization (golden) test: freeze what every built-in standard reports today.

A refactor must change no number. Each metric of each built-in standard is run on the demo
series and on the pinned third-party XER files; status, counts, value and the identifiers of
the flagged items are compared with tests/golden/standards.json. Activity names are never
stored. After an intended change, regenerate with XERSCOPE_UPDATE_GOLDEN=1 and review the diff.
"""

import json
import os
from pathlib import Path

from conftest import REFERENCE_HINT, missing

from xerscope.analysis import AnalysisContext, builtin_standards, run_standard
from xerscope.xer import load_snapshot

GOLDEN = Path(__file__).parent / "golden" / "standards.json"
REFERENCE_DATA = Path(__file__).parent / "reference" / "data"
REFERENCE_FOLDERS = ("mpxj", "xerlock")
SHOWN_DIFFS = 20


def flagged_identifiers(flagged) -> list[str]:
    """Task codes, or "pred->succ" for relationship rows; never names."""
    if "pred_code" in flagged and "succ_code" in flagged:
        pairs = zip(flagged["pred_code"], flagged["succ_code"], strict=True)
        return sorted(f"{p}->{s}" for p, s in pairs)
    if "task_code" in flagged:
        return sorted(str(c) for c in flagged["task_code"])
    return []


def entry_of(result) -> dict:
    return {
        "status": result.status,
        "numerator": result.numerator,
        "denominator": result.denominator,
        "value": None if result.value is None else round(float(result.value), 6),
        "flagged": flagged_identifiers(result.flagged),
    }


def observe(snapshot, store=None) -> dict:
    """{standard id/metric id: entry} for one snapshot.

    No baseline, as `xerscope check` does by default (its --planned-baseline is opt-in).
    """
    observed = {}
    for std_id, std in builtin_standards().items():
        for result in run_standard(std, AnalysisContext(snapshot, store)):
            observed[f"{std_id}/{result.metric.id}"] = entry_of(result)
    return observed


def observe_series(store) -> dict:
    """Every snapshot of the demo series, with the series so previous-update checks run."""
    return {Path(s.source).name: observe(s, store) for s in store}


def reference_files() -> list[Path]:
    return sorted(p for folder in REFERENCE_FOLDERS for p in (REFERENCE_DATA / folder).glob("*.xer"))


def observe_reference_files() -> dict:
    return {path.name: observe(load_snapshot(path)) for path in reference_files()}


def flatten(observed: dict) -> dict:
    return {f"{file}/{key}": entry for file, per_file in observed.items() for key, entry in per_file.items()}


def differences(expected: dict, actual: dict) -> list[str]:
    exp, act = flatten(expected), flatten(actual)
    return [
        f"{key}: golden={exp.get(key)} now={act.get(key)}"
        for key in sorted(exp.keys() | act.keys())
        if exp.get(key) != act.get(key)
    ]


def write_golden(observed: dict) -> None:
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(observed, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def check_against_golden(section: str, observed: dict) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    if os.environ.get("XERSCOPE_UPDATE_GOLDEN") == "1":
        golden[section] = observed
        write_golden(golden)
        return
    diffs = differences(golden.get(section, {}), observed)
    shown = "\n".join(diffs[:SHOWN_DIFFS])
    assert not diffs, f"{len(diffs)} entries differ from {GOLDEN.name} (first {SHOWN_DIFFS}):\n{shown}"


def test_demo_series_matches_golden(store):
    check_against_golden("demo", observe_series(store))


def test_reference_files_match_golden():
    if not reference_files():
        missing("reference", REFERENCE_HINT)
    check_against_golden("reference", observe_reference_files())
