"""The sets behind each check: the rows of the denominator (``checked``) and of the numerator.

An auditor recounts a check from these sets, so they must be the ones the rule counted:
len(checked) == denominator, the numerator's rows number the numerator, and every listed item
is among the checked ones. Run on every built-in metric of the demo series (with the first
update as baseline, so the baseline checks run) and the pinned third-party files.
"""

import pandas as pd
import pytest
from conftest import REFERENCE_HINT, missing
from test_characterization import REFERENCE_DATA, reference_names

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.xer import load_snapshot

LINK_KEY = ["pred_code", "succ_code", "type"]


def identifiers(frame) -> set:
    """Activity IDs, (predecessor, successor, type) for relationships, assignment ids."""
    if "taskrsrc_id" in frame.columns:
        return set(frame["taskrsrc_id"])
    if "pred_code" in frame.columns:
        return set(frame[LINK_KEY].itertuples(index=False, name=None))
    return set(frame["task_code"])


def problems(result) -> list[str]:
    name = f"{result.metric.standard} {result.metric.id}"
    if result.status == "error":
        return [f"{name}: {result.note}"]
    found = []
    if result.denominator is not None:
        if result.checked is None:
            return [f"{name}: denominator {result.denominator} without its rows"]
        if len(result.checked) != result.denominator:
            found.append(f"{name}: {len(result.checked)} rows checked, denominator {result.denominator}")
    if result.numerator is not None:
        rows = result.counted if result.counted is not None else result.flagged
        counted = len(identifiers(rows)) if not rows.empty else 0
        if counted != result.numerator:
            found.append(f"{name}: {counted} rows counted, numerator {result.numerator}")
    if result.checked is not None and not result.flagged.empty:
        outside = identifiers(result.flagged) - identifiers(result.checked)
        if outside:
            found.append(f"{name}: listed but not checked: {sorted(outside)[:3]}")
    return found


def all_problems(snapshot, store=None, baseline=None) -> list[str]:
    found = []
    for standard in builtin_standards().values():
        for result in run_standard(standard, AnalysisContext(snapshot, store, baseline)):
            found += problems(result)
    return found


def test_sets_match_the_counts_on_the_demo_series(store):
    first = Baseline.from_snapshot(store.first)
    found = [f"{snapshot.source}: {p}" for snapshot in store for p in all_problems(snapshot, store, first)]
    assert not found, found[:20]


def test_sets_match_the_counts_on_the_reference_files():
    names = reference_names()
    if not names or not (REFERENCE_DATA / names[0]).exists():
        missing("reference", REFERENCE_HINT)
    found = [f"{name}: {p}" for name in names for p in all_problems(load_snapshot(REFERENCE_DATA / name))]
    assert not found, found[:20]


@pytest.mark.parametrize("bad", ["denominator", "numerator", "outside"])
def test_problems_catches_a_set_that_disagrees(store, bad):
    """The check above would not pass by accident: each kind of disagreement is caught."""
    import dataclasses

    result = next(
        r
        for r in run_standard(builtin_standards()["P6"], AnalysisContext(store.latest, store))
        if r.metric.id == "P6-01" and len(r.flagged) > 1
    )
    if bad == "denominator":
        result = dataclasses.replace(result, checked=result.checked.iloc[1:])
    elif bad == "numerator":
        result = dataclasses.replace(result, flagged=result.flagged.iloc[1:])
    else:
        listed = result.checked["task_code"].isin(result.flagged["task_code"])
        result = dataclasses.replace(result, checked=result.checked[~listed])
    assert problems(result)


# --- the Audit page's analysis: audited settings, sets, TOML ---------------------------------


def test_every_built_in_metric_round_trips_through_its_toml_block():
    """The block the page offers to copy loads back into the same metric (target, params, unit)."""
    import tomllib

    from xerscope.analysis.audit import toml_block, with_settings
    from xerscope.analysis.standards import parse_standard

    for standard in builtin_standards().values():
        for metric in standard.metrics:
            for edited in (
                metric,
                with_settings(metric, params={"limit_hours": 264}) if metric.id == "P6-04" else metric,
            ):
                data = {
                    "standard": {"id": "T", "name": standard.name},
                    "metric": [tomllib.loads(toml_block(edited))["metric"][0]],
                }
                assert parse_standard(data).metrics[0] == edited, edited.id
                assert parse_standard(data).metrics[0].params == edited.params, edited.id


@pytest.mark.parametrize(
    ("target", "params", "message"),
    [
        ("< 5", {}, None),
        ("<< 5%", {}, "target"),
        ("< 5%", {"limit_hours": "x"}, "expected a number"),
        ("< 5%", {"limit_days": 10}, "no parameter"),
    ],
)
def test_audited_settings_are_checked_like_a_standard_file(target, params, message):
    from xerscope.analysis.audit import with_settings

    metric = builtin_standards()["P6"]["P6-04"]
    if message is None:
        audited = with_settings(metric, target, params)
        assert (audited.comparator, audited.threshold) == ("<", 5.0)
        assert metric.threshold == 5.0 and metric.params == {"limit_hours": 352}  # the loaded standard is untouched
    else:
        with pytest.raises(ValueError, match=message):
            with_settings(metric, target, params)


def test_sets_partition_the_file(store):
    """Counted + checked-not-counted = checked, and checked + excluded = the file's activities
    (or relationships), for every check whose counted rows are checked rows."""
    from xerscope.analysis.audit import _key, split

    snapshot = store.latest
    for standard in builtin_standards().values():
        for result in run_standard(standard, AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first))):
            sets = split(result, snapshot)
            if sets is None or sets.excluded is None or sets.counted_outside:
                continue
            name = f"{standard.id} {result.metric.id}"
            counted = set(_key(sets.counted, sets.subject)) if not sets.counted.empty else set()
            assert len(counted) + len(sets.not_counted) == result.denominator, name
            universe = snapshot.activities if sets.subject == "activities" else snapshot.relationships
            assert result.denominator + len(sets.excluded) == len(universe), name


def test_bei_counts_completions_outside_the_due_set(store):
    """DCMA-14: early completions count in the numerator but are not due: shown apart, not lost."""
    from xerscope.analysis.audit import split

    snapshot = store.latest
    result = run_standard(
        builtin_standards()["DCMA"], AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first))
    )
    bei = next(r for r in result if r.metric.id == "DCMA-14")
    sets = split(bei, snapshot)
    assert len(sets.counted) == bei.numerator


# --- sets_long: every check's sets in one table -------------------------------------------------


def _long_cases(store):
    """(standard id, results, long table) of every built-in standard on the latest demo update."""
    from xerscope.analysis.audit import sets_long

    snapshot = store.latest
    for standard in builtin_standards().values():
        results = run_standard(standard, AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first)))
        yield standard.id, results, sets_long(results, snapshot)


def test_the_long_table_counts_each_check_as_the_check_does(store):
    """Per check: `counted` rows number the numerator, `counted` + `checked` rows the denominator; a
    numerator row outside the checked set (BEI) is the one case where the two differ, and is told."""
    from xerscope.analysis.audit import split

    assert {sid for sid, _, _ in _long_cases(store)} == {"P6", "DCMA", "DECM", "INTEGRITY"}
    for sid, results, table in _long_cases(store):
        assert list(table.columns[:3]) == ["check_id", "set", "note"]
        assert list(dict.fromkeys(table["check_id"])) == [r.metric.id for r in results]
        for result in results:
            rows = table[table["check_id"] == result.metric.id]
            name = f"{sid} {result.metric.id}"
            if result.checked is None:
                assert len(rows) == 1 and rows["set"].iloc[0] == "" and rows["note"].iloc[0] == result.note, name
                continue
            outside = split(result, store.latest).counted_outside
            counted, checked = (rows["set"] == "counted").sum(), (rows["set"] == "checked").sum()
            if result.numerator is not None:
                assert counted == result.numerator, name
            if result.denominator is not None:
                assert counted - outside + checked == result.denominator, name


def test_the_long_table_is_the_audit_page_sets(store):
    """Same items as `split` gives the Audit page, set by set; nothing rebuilt."""
    from xerscope.analysis.audit import _key, split

    for sid, results, table in _long_cases(store):
        for result in results:
            sets = split(result, store.latest)
            if sets is None:
                continue
            rows = table[table["check_id"] == result.metric.id]
            for name, frame in (("counted", sets.counted), ("checked", sets.not_counted), ("excluded", sets.excluded)):
                shown = rows[rows["set"] == name]
                expected = [] if frame is None or frame.empty else sorted(_key(frame, sets.subject))
                got = [] if shown.empty else sorted(_key(shown, sets.subject))
                assert got == expected, f"{sid} {result.metric.id} {name}"


def test_a_relationship_carries_the_fields_of_both_activities(store):
    from xerscope.analysis.audit import PREFIXED_FIELDS

    snapshot = store.latest
    activities = snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    results = run_standard(
        builtin_standards()["P6"], AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first))
    )
    from xerscope.analysis.audit import sets_long

    table = sets_long(results, snapshot)
    links = table[table["check_id"] == "P6-07"]
    assert len(links) > 10
    for end in ("pred", "succ"):
        for field in PREFIXED_FIELDS:
            expected = links[f"{end}_code"].map(activities[field])
            pd.testing.assert_series_equal(links[f"{end}_{field}"], expected, check_names=False)
    assert {"pred_code", "succ_code", "type", "lag_hr"} <= set(links.columns)


def test_by_check_cuts_the_long_table_without_losing_a_row(store):
    from xerscope.analysis.audit import by_check

    for _, results, table in _long_cases(store):
        parts = by_check(table)
        assert list(parts) == [r.metric.id for r in results]
        assert sum(len(part) for part in parts.values()) == len(table)
        for part in parts.values():
            assert list(part.columns[:3]) == ["check_id", "set", "note"] and not part.isna().all().any()
