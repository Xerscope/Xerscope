"""The tasks the Gantt page's filters keep (analysis/task_filters.py), on a schedule built by hand.

Five tasks under Eng (W1) > Design (W11) and Civil (W2), with the activity code Phase:

    A  complete     W11  "Pour béton"        Phase B1 / L1
    B  not started  W1   "Formwork"          Phase B1 / L2
    C  in progress  W2   "Beton slab"        Phase Béton
    D  not started  W2   "Site supervision"  level of effort
    E  not started  W2   "Rebar"
"""

import pandas as pd
from xerkit import active, done, snap, todo

from xerscope.analysis.task_filters import branch_tasks, filtered_tasks, matching_code_ids, search_mask
from xerscope.analysis.wbs import ROOT, path_to, rollup


def _node(wbs_id: str, parent: str, code: str, name: str) -> dict:
    is_project = "Y" if not parent else "N"
    return {
        "wbs_id": wbs_id,
        "proj_id": "1",
        "parent_wbs_id": parent,
        "proj_node_flag": is_project,
        "wbs_short_name": code,
        "wbs_name": name,
    }


WBS = [
    _node("W0", "", "P", "P"),
    _node("W1", "W0", "E", "Eng"),
    _node("W11", "W1", "D", "Design"),
    _node("W2", "W0", "C", "Civil"),
]
SCHEDULE = snap(
    [
        done("A", wbs_id="W11", task_name="Pour béton"),
        todo("B", wbs_id="W1", task_name="Formwork"),
        active("C", wbs_id="W2", task_name="Beton slab"),
        todo("D", wbs_id="W2", task_name="Site supervision", task_type="TT_LOE"),
        todo("E", wbs_id="W2", task_name="Rebar"),
    ],
    wbs=WBS,
    codes=[("A", "Phase", "B1/L1"), ("B", "Phase", "B1/L2"), ("C", "Phase", "Béton")],
)
# the float category is the caller's column: set by hand here
CATEGORY = {"A": "Complete", "B": "Normal", "C": "Critical", "D": "Normal", "E": "Near critical"}


def _codes(tasks: pd.DataFrame) -> list[str]:
    return sorted(tasks["task_code"])


def _with_category(tasks: pd.DataFrame) -> pd.DataFrame:
    return tasks.assign(category=tasks["task_code"].map(CATEGORY))


def _phase() -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    """The Phase values, their id by value ("L1" -> id) and by the label the page shows."""
    values = SCHEDULE.code_values
    by_value = dict(zip(values["value"], values["code_id"], strict=True))
    by_label = {f"{path} · {code_id}": code_id for code_id, path in SCHEDULE.code_paths("Phase").items()}
    return values, by_value, by_label


def test_branch_tasks_are_those_under_the_nodes_less_the_level_of_effort_on_request():
    assert _codes(branch_tasks(SCHEDULE, None)) == ["A", "B", "C", "D", "E"]
    assert _codes(branch_tasks(SCHEDULE, None, hide_loe=True)) == ["A", "B", "C", "E"]
    assert _codes(branch_tasks(SCHEDULE, {"W1", "W11"})) == ["A", "B"]  # Eng and Design under it
    assert _codes(branch_tasks(SCHEDULE, {"W1"})) == ["B"]  # the node's own tasks only: the caller names the branch
    assert _codes(branch_tasks(SCHEDULE, {"W2"}, hide_loe=True)) == ["C", "E"]


def test_filtered_tasks_keep_every_task_without_a_filter_and_intersect_those_given():
    tasks = _with_category(branch_tasks(SCHEDULE, None))
    assert _codes(filtered_tasks(tasks, SCHEDULE)) == ["A", "B", "C", "D", "E"]
    assert _codes(filtered_tasks(tasks, SCHEDULE, statuses=["Not started"])) == ["B", "D", "E"]
    assert _codes(filtered_tasks(tasks, SCHEDULE, categories=["Critical", "Near critical"])) == ["C", "E"]
    # in the name, case and accents ignored: "Pour béton" and "Beton slab"
    assert _codes(filtered_tasks(tasks, SCHEDULE, search="BETON")) == ["A", "C"]
    # in the Activity ID as well: no name holds a "c", the Activity ID C does
    assert _codes(filtered_tasks(tasks, SCHEDULE, search="c")) == ["C"]
    # three filters at once: not started, Normal float, "o" in the name: B (Formwork) and D (Site supervision)
    kept = filtered_tasks(tasks, SCHEDULE, statuses=["Not started"], categories=["Normal"], search="o")
    assert _codes(kept) == ["B", "D"]


def test_filtered_tasks_keep_the_tasks_assigned_one_of_the_code_values():
    tasks = _with_category(branch_tasks(SCHEDULE, None))
    _, by_value, _ = _phase()
    assert _codes(filtered_tasks(tasks, SCHEDULE, code_type="Phase", code_ids={by_value["L1"]})) == ["A"]
    assert _codes(filtered_tasks(tasks, SCHEDULE, code_type="Phase", code_ids={by_value["L2"], by_value["Béton"]})) == [
        "B",
        "C",
    ]
    # the parent value B1 is assigned to no task: P6's "equals" does not take its sub-values' tasks
    assert _codes(filtered_tasks(tasks, SCHEDULE, code_type="Phase", code_ids={by_value["B1"]})) == []
    # a text that matched no value: no task; no pick at all: no filter
    assert _codes(filtered_tasks(tasks, SCHEDULE, code_type="Phase", code_ids=set())) == []
    assert _codes(filtered_tasks(tasks, SCHEDULE, code_type="Phase", code_ids=None)) == ["A", "B", "C", "D", "E"]


def test_matching_code_ids_take_a_label_exactly_and_a_text_as_contained():
    values, by_value, by_label = _phase()
    l1_label = next(label for label, code_id in by_label.items() if code_id == by_value["L1"])
    assert matching_code_ids(values, by_label, [l1_label]) == {by_value["L1"]}
    # "l" is in L1 and L2, not in B1 nor in Béton
    assert matching_code_ids(values, by_label, ["l"]) == {by_value["L1"], by_value["L2"]}
    # accents and case ignored
    assert matching_code_ids(values, by_label, ["beton"]) == {by_value["Béton"]}
    # the text "b1" is the value B1 alone: L1 and L2 are under it but their own code does not hold it
    assert matching_code_ids(values, by_label, ["b1"]) == {by_value["B1"]}
    assert matching_code_ids(values, by_label, [l1_label, "beton"]) == {by_value["L1"], by_value["Béton"]}
    assert matching_code_ids(values, by_label, ["zzz"]) == set()
    assert matching_code_ids(values, by_label, []) == set()


def test_search_mask_reads_any_of_the_columns_without_case_or_accents():
    frame = pd.DataFrame({"code": ["A1", "B2", "C3"], "name": ["Béton", "acier", "Bois"]})
    assert search_mask(frame, ["code", "name"], "b").tolist() == [True, True, True]  # Béton, B2, Bois
    assert search_mask(frame, ["name"], "b").tolist() == [True, False, True]
    assert search_mask(frame, ["code", "name"], "BETON").tolist() == [True, False, False]


def test_path_to_goes_from_the_top_down_to_the_node():
    nodes = rollup(SCHEDULE)
    assert path_to(nodes, "W11") == [ROOT, "W1", "W11"]
    assert path_to(nodes, "W2") == [ROOT, "W2"]
    assert path_to(nodes, ROOT) == [ROOT]
