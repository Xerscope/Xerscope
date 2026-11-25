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


@pytest.mark.oracle("property")
def test_the_toml_block_is_written_as_the_standard_files_are():
    """The block is pasted into a standard file, which is UTF-8 (TOML v1.0.0, "a TOML file must be a
    valid UTF-8 encoded Unicode document"): the section sign of "PAM 200.1 §4.2" is written as
    itself, as in dcma.toml, not as a \\u00a7 escape."""
    from xerscope.analysis.audit import toml_block

    leads = next(metric for metric in builtin_standards()["DCMA"].metrics if metric.id == "DCMA-02")
    assert "§4.2" in leads.source
    block = toml_block(leads)
    assert "§4.2" in block and "\\u" not in block


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
                # the note of the table ends with the baseline the check read (DCMA-13 without a Must Finish By)
                expected = result.note_with_baseline
                assert len(rows) == 1 and rows["set"].iloc[0] == "" and rows["note"].iloc[0] == expected, name
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


# --- what the Audit page shows of a population built step by step ---------------------------------


def _funnel():
    """Five tasks A to E. "not complete" (Oracle 101248) removes A and B: 3 left. "has hours"
    (model) removes none: 3 left. "in the report" (R1) removes C: 2 left."""
    from xerscope.analysis.populations import Funnel

    rows = pd.DataFrame({"task_code": list("ABCDE"), "task_name": list("abcde"), "scratch": range(5)})
    funnel = Funnel(rows)
    funnel.keep("not complete", "101248", lambda tasks: ~tasks["task_code"].isin(["A", "B"]))
    funnel.keep("has hours", "model", lambda tasks: tasks["task_code"].notna())
    funnel.keep("in the report", "R1", lambda tasks: tasks["task_code"] != "C")
    return funnel


def test_funnel_table_lists_the_start_each_step_and_the_counted_items():
    from xerscope.analysis.audit import funnel_table, step_rows

    steps = [(row["step"], row["source"], row["removed"], row["left"]) for row in step_rows(_funnel())]
    assert steps == [
        ("start", "", None, 5),
        ("not complete", "101248", 2, 3),
        ("has hours", "model", 0, 3),
        ("in the report", "R1", 1, 2),
    ]
    table = funnel_table(_funnel(), 1)  # the check counts 1 of the 2 tasks left
    assert table["step"].tolist() == ["start", "not complete", "has hours", "in the report", "counted"]
    assert table["left"].tolist() == [5, 3, 3, 2, 1]
    assert pd.isna(table["removed"].iloc[0]) and pd.isna(table["removed"].iloc[-1])


def test_step_sources_name_each_source_once_and_removing_steps_those_that_took_rows_out():
    from xerscope.analysis.audit import removing_steps, step_sources

    funnel = _funnel()
    funnel.keep("started", "101248", lambda tasks: tasks["task_code"] != "E")  # a source already used
    assert step_sources(funnel) == ["101248", "R1", "model"]
    assert [step.label for step in removing_steps(funnel)] == ["not complete", "in the report", "started"]


def test_removed_set_shows_tasks_or_links_in_their_standard_columns():
    """The first step removed tasks A and B: "activities", their ID and name, the scratch column
    left out. A step that removed the link P -> S: "relationships", its two ends and type."""
    from xerscope.analysis.audit import removed_set, removing_steps
    from xerscope.analysis.populations import Step

    subject, tasks = removed_set(removing_steps(_funnel())[0])
    assert subject == "activities" and tasks.columns.tolist() == ["task_code", "task_name"]
    assert tasks["task_code"].tolist() == ["A", "B"]
    link = pd.DataFrame({"pred_code": ["P"], "succ_code": ["S"], "type": ["FS"], "scratch": [0]})
    subject, links = removed_set(Step("driving", "model", link, 0))
    assert subject == "relationships" and "scratch" not in links.columns
    assert links[["pred_code", "succ_code", "type"]].iloc[0].tolist() == ["P", "S", "FS"]


def test_counted_count_is_the_numerator_and_the_counted_rows_without_one():
    """A numerator of 7: 7. A numerator of 0 with three rows listed: 0, the check's own count.
    No numerator and three rows: 3."""
    from xerscope.analysis import CheckResult, Metric
    from xerscope.analysis.audit import AuditSets, counted_count

    metric = Metric(id="T-01", name="check", standard="T", rule="p6_01_logic")
    three_rows = pd.DataFrame({"task_code": ["A", "B", "C"]})
    sets = AuditSets(counted=three_rows, not_counted=three_rows.iloc[0:0], excluded=None)
    assert counted_count(CheckResult(metric, "fail", numerator=7), sets) == 7
    assert counted_count(CheckResult(metric, "pass", numerator=0), sets) == 0
    assert counted_count(CheckResult(metric, "info"), sets) == 3


# --- what the Audit page asks of the settings picked on it ------------------------------------------


def _dangling(**params):
    """A check on the rule "dangling", whose defaults are end = "finish" and exclude = ("complete",)."""
    from xerscope.analysis import Metric

    return Metric(id="T-01", name="check", standard="T", rule="dangling", params=params)


def test_kept_params_are_those_that_differ_from_the_rule_or_that_the_standard_sets():
    from xerscope.analysis.audit import kept_params

    # the rule's own values picked again, the list as the page's widget returns it: nothing to hold
    assert kept_params(_dangling(), {"end": "finish", "exclude": ["complete"]}) == {}
    # both changed: both held, the names as a list
    assert kept_params(_dangling(), {"end": "start", "exclude": ("complete", "loe")}) == {
        "end": "start",
        "exclude": ["complete", "loe"],
    }
    # the standard sets end to the rule's default: held although it equals the default
    assert kept_params(_dangling(end="finish"), {"end": "finish", "exclude": ["complete"]}) == {"end": "finish"}
    # nothing excluded any more: an empty list differs from ("complete",)
    assert kept_params(_dangling(), {"end": "finish", "exclude": []}) == {"exclude": []}


def test_has_same_settings_compares_the_parameters_and_the_target():
    """P6-04 as the standard sets it: 352 hours, target < 5%. Typed again as it is: the same.
    264 hours, or < 3%, or the target "info": another check."""
    from xerscope.analysis.audit import has_same_settings, with_settings

    metric = builtin_standards()["P6"]["P6-04"]
    assert (metric.params, metric.threshold_label) == ({"limit_hours": 352}, "< 5%")
    assert has_same_settings(with_settings(metric, "< 5%", {"limit_hours": 352}), metric)
    assert not has_same_settings(with_settings(metric, "< 5%", {"limit_hours": 264}), metric)
    assert not has_same_settings(with_settings(metric, "< 3%", {"limit_hours": 352}), metric)
    assert not has_same_settings(with_settings(metric, "info", {"limit_hours": 352}), metric)


def test_settings_table_gives_each_setting_now_by_default_and_what_it_accepts():
    """P6-04 audited at 264 hours and < 3%: the target reads < 3% for a standard at < 5%, the limit
    264 for a rule at 352. A closed list names its values, a yes / no parameter says so."""
    from xerscope.analysis.audit import TARGET_FORMS, settings_table, with_settings

    standard_metric = builtin_standards()["P6"]["P6-04"]
    audited = with_settings(standard_metric, "< 3%", {"limit_hours": 264})
    table = settings_table(audited, standard_metric).set_index("setting")
    assert table.index.tolist() == ["target", "limit_hours"]
    assert table.loc["target"].tolist() == ["< 3%", "< 5%", TARGET_FORMS]
    assert table.loc["limit_hours"].tolist() == ["264", "352", "a number"]
    dangling = settings_table(_dangling(), _dangling()).set_index("setting")
    assert dangling.loc["end"].tolist() == ["finish", "finish", "start, finish"]
    yes_no = builtin_standards()["P6"]["P6-17"]
    assert (
        settings_table(yes_no, yes_no).set_index("setting").loc["ignore_soft_constraints", "accepts"] == "true / false"
    )


def _float(target=None, unit="%", **params):
    """A check on the rule "float" (defaults: op ">", value 44, unit "days", value_max 0)."""
    from xerscope.analysis import Metric
    from xerscope.analysis.standards import parse_target

    comparator, threshold = parse_target(target, unit)
    return Metric(
        id="T-02",
        name="check",
        standard="T",
        rule="float",
        unit=unit,
        comparator=comparator,
        threshold=threshold,
        params=params,
    )


@pytest.mark.oracle("property")
def test_the_form_puts_what_a_measure_is_compared_with_on_one_row():
    """``op``, ``value``, ``value_max`` and ``unit`` are one question (flagged when the float is from
    0 to 20 days): one row, in that order, where the rule's signature puts ``op``. Every other
    parameter is a row of its own, and a rule that compares nothing has no such row."""
    from xerscope.analysis.audit import form_rows
    from xerscope.analysis.rules import RULES

    assert form_rows("float") == [("op", "value", "value_max", "unit"), ("exclude",)]
    assert form_rows("duration") == [("field",), ("op", "value", "unit"), ("exclude",)]
    assert form_rows("lag") == [("op", "value", "unit"), ("links",), ("exclude_loe",), ("exclude",)]
    assert form_rows("dcma_06_high_float") == [("limit_days",)]
    assert form_rows("dcma_01_logic") == []
    for name, rule in RULES.items():  # no parameter lost, none twice, the rule's order kept between rows
        drawn = [parameter for row in form_rows(name) for parameter in row]
        assert sorted(drawn) == sorted(rule.params), name


@pytest.mark.oracle("property")
def test_a_band_bound_is_read_only_by_a_band():
    """``rules._within`` reads ``value_max`` for ``op = "between"`` alone: a form that asked for it
    under another operator would take a number the check ignores."""
    from xerscope.analysis.rules import is_read

    assert is_read("value_max", {"op": "between"})
    assert not any(is_read("value_max", {"op": op}) for op in ("<", "<=", ">", ">="))
    assert not is_read("value_max", {})  # the operator is not picked yet
    assert all(is_read(name, {"op": ">"}) for name in ("op", "value", "unit", "exclude"))


@pytest.mark.oracle("property")
def test_the_settings_are_said_in_sentences_the_parameters_then_the_target():
    """The two comparisons of a check read apart: what flags a task, then the result that passes,
    in the words of the formula under it (flagged / checked)."""
    from xerscope.analysis.explain import settings_lines

    assert settings_lines(_float("< 5%", op="<=", value=40)) == [
        "Excludes: completed tasks.",
        "Flagged when total float ≤ 40 days.",
        "Passes when flagged / checked is < 5 %.",
    ]
    band = settings_lines(_float("< 5%", op="between", value=0, value_max=20, exclude=[]))
    assert band == ["Flagged when total float is from 0 to 20 days (both included).", band[-1]]
    assert settings_lines(_float("<= 0", unit="count", op="<", value=0))[-1] == "Passes when the number flagged is ≤ 0."
    assert settings_lines(_float(None))[-1] == "No target: the result is reported for review."
    built_in = builtin_standards()
    assert (
        settings_lines(built_in["DCMA"]["DCMA-14"])[-1] == "Passes when completed / due by the status date is ≥ 0.95."
    )
    assert settings_lines(built_in["DCMA"]["DCMA-12"])[-1] == "Passes when the test passes."
    # P6-08 counts "flagged / checked" relationships: the sentence names them, as the formula does
    assert settings_lines(built_in["P6"]["P6-08"])[-1] == "Passes when flagged / relationships checked is < 5 %."


def test_every_built_in_metric_has_its_settings_in_sentences():
    from xerscope.analysis.explain import _population, settings_lines
    from xerscope.analysis.rules import RULES

    for standard in builtin_standards().values():
        for metric in standard.metrics:
            lines = settings_lines(metric)
            rule = RULES[metric.rule]
            # the sentences of the parameters are those the Calculation block lists under "Population"
            assert [*rule.population, *lines[:-1]] == _population(rule, {**rule.params, **metric.params}), metric.id
            assert lines[-1].endswith("."), metric.id
