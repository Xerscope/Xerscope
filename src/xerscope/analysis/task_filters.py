"""The tasks a set of filters keeps: WBS branch, status, float category, text, P6 activity code.

    tasks = branch_tasks(snapshot, branch_ids, hide_loe=True)   # the tasks under a WBS node
    kept = filtered_tasks(tasks, snapshot, statuses=["In progress"], search="pump")

The Gantt page's filters, and the activity code filter of the PPC page (`CodeFilter`). Each filter
left empty keeps every task; the filters given are intersected. The float category is the
caller's column (``viz.gantt.categorise`` reads the settings, which this layer does not import).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

import pandas as pd

from ..xer import Snapshot
from .ask.text import fold


def search_mask(frame: pd.DataFrame, columns: Sequence[str], text: str) -> pd.Series:
    """Rows where any of ``columns`` contains ``text``, ignoring case and accents."""
    needle = fold(text)
    hits = {column: frame[column].map(fold).str.contains(needle, regex=False) for column in columns}
    return pd.DataFrame(hits).any(axis=1)


def code_value_labels(snapshot: Snapshot, code_type: str) -> dict[str, str]:
    """Map each value label of the code type ``code_type`` (the file's label) to its ``code_id``.

    A value label is its path in the code's hierarchy, then its description ("B1/L1 · Level 1").
    """
    values = snapshot.code_values[snapshot.code_values["code_type"] == code_type]
    description = dict(zip(values["code_id"], values["name"], strict=True))
    return {f"{path} · {description[code_id]}": code_id for code_id, path in snapshot.code_paths(code_type).items()}


def matching_code_ids(values: pd.DataFrame, by_label: dict[str, str], picks: Iterable[str]) -> set[str]:
    """Values of one activity code type that ``picks`` name (``code_id``).

    A pick that is a label of ``by_label`` (label -> ``code_id``) is that value exactly, as P6's
    filter "equals"; any other pick is a text, and keeps every value of ``values`` (the type's
    rows of ``Snapshot.code_values``) whose code contains it, case and accents ignored, as P6's
    "contains".
    """
    short_values = dict(zip(values["code_id"], values["value"], strict=True))
    code_ids: set[str] = set()
    for pick in picks:
        if pick in by_label:
            code_ids.add(by_label[pick])
        else:
            code_ids |= {code_id for code_id, value in short_values.items() if fold(pick) in fold(value)}
    return code_ids


def branch_tasks(snapshot: Snapshot, branch_ids: Collection[str] | None, hide_loe: bool = False) -> pd.DataFrame:
    """Tasks of the WBS nodes ``branch_ids`` (None: the whole project), level of effort left out when ``hide_loe``."""
    tasks = snapshot.activities
    if branch_ids is not None:
        tasks = tasks[tasks["wbs_id"].isin(branch_ids)]
    return tasks[~tasks["is_loe"]] if hide_loe else tasks


def filtered_tasks(
    tasks: pd.DataFrame,
    snapshot: Snapshot,
    statuses: Collection[str] = (),
    categories: Collection[str] = (),
    search: str = "",
    code_type: str | None = None,
    code_ids: Collection[str] | None = None,
) -> pd.DataFrame:
    """Rows of ``tasks`` (`branch_tasks`) that every given filter keeps.

    One of ``statuses``, one of the float ``categories`` (the column ``category``), ``search`` in the Activity ID or the
    name (case and accents ignored), one of the values ``code_ids`` of the activity code
    ``code_type`` (assigned exactly: `Snapshot.tasks_with_codes`). ``code_ids`` None: no code
    filter; empty: no task.
    """
    if statuses:
        tasks = tasks[tasks["status"].isin(statuses)]
    if categories:
        tasks = tasks[tasks["category"].isin(categories)]
    if search:
        tasks = tasks[search_mask(tasks, ["task_code", "task_name"], search)]
    if code_type and code_ids is not None:
        tasks = tasks[tasks["task_code"].isin(snapshot.tasks_with_codes(code_type, code_ids))]
    return tasks


@dataclass(frozen=True)
class CodeFilter:
    """The tasks assigned some values of a P6 activity code, whichever file they are read in.

    ``type_name`` is the P6 name of the code type ("Discipline"), not the file's label of it: a label
    gains the scope or the id when two types of a file share a name, so it differs between exports.
    ``picks`` are the picks of the Gantt picker: a label of `code_value_labels` is that value exactly,
    any other text keeps every value containing it (`matching_code_ids`). Two types of one file with
    this name are both read. No pick keeps no task: the caller applies no filter instead.
    """

    type_name: str
    picks: tuple[str, ...]

    def tasks(self, snapshot: Snapshot) -> set[str]:
        """Activity IDs of ``snapshot`` assigned a value picked; none when it has no such code type."""
        values = snapshot.code_values
        tasks: set[str] = set()
        for code_type in values.loc[values["type_name"] == self.type_name, "code_type"].unique():
            type_values = values[values["code_type"] == code_type]
            code_ids = matching_code_ids(type_values, code_value_labels(snapshot, code_type), self.picks)
            tasks |= snapshot.tasks_with_codes(code_type, code_ids)
        return tasks

    def keep(self, rows: pd.DataFrame, snapshot: Snapshot) -> pd.DataFrame:
        """Return the rows of ``rows`` (column ``task_code``) whose task `tasks` holds, in their order."""
        return rows[rows["task_code"].isin(self.tasks(snapshot))]
