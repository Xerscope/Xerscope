"""The baselines a P6 XML baseline file holds, as the Debug page lists them.

They are held against the baseline each update names (PROJECT.sum_base_proj_id is the ObjectId of a
BaselineProject of the export), and the baseline each update would be measured against is looked for
among them (``analysis.baseline_resolution``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable

import pandas as pd

from xerscope.analysis.baseline import content_digest
from xerscope.analysis.baseline_resolution import Export, resolutions
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot, load_snapshot
from xerscope.xer.parser import XerError
from xerscope.xer.pmxml import DiskFile, PmxmlIndex, XmlBaseline


def xml_baselines_table(index: PmxmlIndex, named_baseline_ids: Iterable[str]) -> pd.DataFrame:
    """Return one row per baseline of the file, in the order of the file.

    Under the names of ``XmlBaseline``: its ObjectId, code, name and data date, the project it was
    taken from and its activities. ``project_baseline``: that project names it as its Project
    Baseline. ``updates_naming_it`` counts it in ``named_baseline_ids``, the sum_base_proj_id of
    each update of the series (0: a baseline no update names).
    """
    named = list(named_baseline_ids)
    project_baselines = {project.current_baseline_id for project in index.projects}
    table = pd.DataFrame(index.baselines, columns=[field.name for field in dataclasses.fields(XmlBaseline)])
    return table.assign(
        project_baseline=[object_id in project_baselines for object_id in table["object_id"]],
        updates_naming_it=[named.count(object_id) for object_id in table["object_id"]],
    )


PROJECT_COLUMNS = [
    "object_id", "data_date", "date_added", "current_baseline_id", "baseline_in_export", "updates_from_it",
    "updates_same_status_date",
]  # fmt: skip


def xml_projects_table(index: PmxmlIndex, updates: Iterable[Snapshot]) -> pd.DataFrame:
    """Return the projects of a P6 XML baseline file, in the order of the file, held against the updates.

    ``object_id``: the id an XER exported from that project carries (PROJECT.proj_id). ``data_date`` and
    ``date_added``: its status date and the date it was added to the database. ``current_baseline_id``: the
    Project Baseline it names; ``baseline_in_export``: the file holds that baseline. ``updates_from_it``
    counts the updates read from that project; ``updates_same_status_date`` those whose status date falls
    on the same day, whatever project they were read from.
    """
    updates = list(updates)
    status_days = [update.data_date.strftime("%Y-%m-%d") for update in updates if update.data_date is not None]
    project_ids = [update.project_id for update in updates]
    rows = [
        {
            "object_id": project.object_id,
            "data_date": project.data_date,
            "date_added": project.date_added,
            "current_baseline_id": project.current_baseline_id,
            "baseline_in_export": project.current_baseline_id in index.baseline_spans,
            "updates_from_it": project_ids.count(project.object_id),
            "updates_same_status_date": status_days.count(project.data_date[:10]) if project.data_date else 0,
        }
        for project in index.projects
    ]
    return pd.DataFrame(rows, columns=PROJECT_COLUMNS)


class BaselineContents:
    """Whether two baselines of an export are copies of one baseline, each digested once at most.

    Two baselines listed with different status dates or counts of activities are not copies: the
    index says so and neither is read. Otherwise each is read and their ``content_digest`` compared.
    """

    def __init__(self, index: PmxmlIndex, read: Callable[[str], Snapshot]) -> None:
        """Keep what the index lists of each baseline and how one is read, by ObjectId; nothing is read yet."""
        self.read = read
        self.listed = {baseline.object_id: (baseline.data_date, baseline.activities) for baseline in index.baselines}
        self.digests: dict[str, str] = {}

    def digest(self, object_id: str) -> str:
        """Return the content digest of one baseline, reading it the first time."""
        if object_id not in self.digests:
            self.digests[object_id] = content_digest(self.read(object_id))
        return self.digests[object_id]

    def same(self, one: str, other: str) -> bool:
        """Tell whether two baselines have the same content; one that cannot be read proves no copy."""
        if self.listed[one] != self.listed[other]:
            return False
        try:
            return self.digest(one) == self.digest(other)
        except XerError:
            return False


def export_of(
    name: str, data: bytes | DiskFile, index: PmxmlIndex, read: Callable[[str], Snapshot] | None = None
) -> Export:
    """Return what the resolution reads of an export.

    Its baselines and, for each project that names one of them as its Project Baseline, that baseline.
    ``read``: how the caller reads one baseline, by ObjectId, when it keeps what it reads: a baseline
    compared here and measured against afterwards is then read once. Read from ``data`` otherwise.
    """
    project_baselines = {
        project.object_id: project.current_baseline_id
        for project in index.projects
        if project.current_baseline_id in index.baseline_spans
    }
    contents = BaselineContents(
        index, read or (lambda object_id: load_snapshot(data, name=name, project_id=object_id, pmxml_index=index))
    )
    return Export(frozenset(index.baseline_spans), project_baselines, contents.same)


RESOLUTION_COLUMNS = [
    "file", "data_date", "proj_id", "sum_base_proj_id", "found_by", "baseline", "version_before", "version_after",
    "note",
]  # fmt: skip


def resolution_table(store: SnapshotStore, export: Export | None) -> pd.DataFrame:
    """Return one row per update, by status date: the baseline it would be measured against.

    ``found_by``: what finds it (``analysis.baseline_resolution``). ``baseline``: its id in the file
    or in the export, or the project of a loaded update. ``version_before`` / ``version_after``: the
    projects of the export created around the update's, when they were looked at.
    """
    rows = [
        {
            "file": update.source,
            "data_date": update.data_date,
            "proj_id": update.project_id,
            "sum_base_proj_id": update.file_baseline.proj_id,
            "found_by": found.found_by,
            "baseline": found.baseline_id,
            "version_before": found.version_before,
            "version_after": found.version_after,
            "note": found.note,
        }
        for update, found in zip(store, resolutions(store, export), strict=True)
    ]
    return pd.DataFrame(rows, columns=RESOLUTION_COLUMNS)
