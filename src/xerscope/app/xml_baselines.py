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
from xerscope.analysis.baseline_resolution import (
    IN_EXPORT,
    LOADED_UPDATE,
    SAME_GENERATION,
    Export,
    Resolution,
    Version,
    resolutions,
    versions_of_the_same_date,
)
from xerscope.app import ui
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
    status_days = [ui.stamp(update.data_date) for update in updates if update.data_date is not None]
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
    "note", "version_same_date", "its_baseline", "listed_as_applied",
]  # fmt: skip


def _date_added(update: Snapshot) -> str:
    """Return the date the project of an update was added to the database (PROJECT.add_date), blank when unknown."""
    added = update.file_projects.set_index("proj_id").loc[update.project_id]["add_date"]
    return added if isinstance(added, str) else ""


def _listing_applied(store: SnapshotStore, found: Resolution, listings: dict) -> tuple[str, int] | None:
    """Return the status day and the number of activities of the baseline found for an update.

    None when none is applied, or when it is the baseline of the update's own file.
    """
    if found.found_by in (IN_EXPORT, SAME_GENERATION):
        return listings[found.baseline_id]
    if found.found_by == LOADED_UPDATE:
        baseline = [update for update in store if update.project_id == found.baseline_id][-1]
        if baseline.data_date is not None:
            return ui.stamp(baseline.data_date), len(baseline.activities)
    return None


def _same_date_columns(store: SnapshotStore, update: Snapshot, found: Resolution, index: PmxmlIndex | None) -> dict:
    """Return what the export holds of an update's own status date (``versions_of_the_same_date``).

    The versions, the baseline each names, and whether those baselines are listed as the one applied
    (status day and number of activities; nothing is read to tell).
    """
    if index is None or update.data_date is None:
        return {"version_same_date": "", "its_baseline": "", "listed_as_applied": ""}
    versions = [
        Version(
            project.object_id,
            project.data_date,
            project.date_added,
            project.current_baseline_id if project.current_baseline_id in index.baseline_spans else "",
        )
        for project in index.projects
    ]
    kept = versions_of_the_same_date(f"{update.data_date:%Y-%m-%d %H:%M}", _date_added(update), versions)
    listings = {baseline.object_id: (baseline.data_date[:10], baseline.activities) for baseline in index.baselines}
    applied = _listing_applied(store, found, listings)
    listed_as_applied = ""
    if kept and applied is not None:
        listed_as_applied = "yes" if all(listings[version.baseline_id] == applied for version in kept) else "no"
    return {
        "version_same_date": ", ".join(version.object_id for version in kept),
        "its_baseline": ", ".join(version.baseline_id for version in kept),
        "listed_as_applied": listed_as_applied,
    }


def resolution_table(store: SnapshotStore, export: Export | None, index: PmxmlIndex | None = None) -> pd.DataFrame:
    """Return one row per update, by status date: the baseline it would be measured against.

    ``found_by``: what finds it (``analysis.baseline_resolution``). ``baseline``: its id in the file
    or in the export, or the project of a loaded update. ``version_before`` / ``version_after``: the
    projects of the export created around the update's, when they were looked at. With the ``index``
    of the export, the versions of the update's own status date (``_same_date_columns``).
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
            **_same_date_columns(store, update, found, index),
        }
        for update, found in zip(store, resolutions(store, export), strict=True)
    ]
    return pd.DataFrame(rows, columns=RESOLUTION_COLUMNS)
