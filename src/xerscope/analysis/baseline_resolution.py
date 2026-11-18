"""Which baseline an update is measured against when its file does not hold the one it names.

P6 Professional exports no baseline in an XER; the update only names its Project Baseline
(PROJECT.sum_base_proj_id). Where the planner keeps one copy of the project per version, each
copy carries its own copy of the baseline in force, under a new id (Oracle, P6 Professional help,
"Copy Project Options dialog box": "Baselines: Mark this checkbox to copy baselines to the new
project"). A P6 XML export of the versions still in the database then holds the same baseline
several times, and may not hold the copy an older update names.

``resolution`` looks for the baseline of one update, in this order:

1. in the update's own file (``IN_FILE``);
2. in the export, under the id the update names (``IN_EXPORT``);
3. among the loaded updates: the id names the project another file was exported from, which was
   made a baseline since (``LOADED_UPDATE``; Oracle, "Create a baseline": a project converted to a
   baseline leaves the project hierarchy);
4. in the export, between the version created just before the update's project and the one
   created just after: when their Project Baselines have the same content, the baseline did not
   change around the update, and the copy of the version before is taken (``SAME_GENERATION``).

Only the first two are what P6 itself measured against. The versions are ordered by ObjectId: a
P6 database gives its ids out in the order of creation. Oracle does not document that order; it is
what the databases seen so far show.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..xer import Snapshot

IN_FILE = "in its file"
IN_EXPORT = "in the export, by id"
LOADED_UPDATE = "a loaded update, by id"
SAME_GENERATION = "in the export, the same baseline before and after"
UNDECIDED = "undecided"
NOT_FOUND = "not found"


@dataclass(frozen=True)
class Export:
    """What the resolution reads of a P6 XML export of baselines."""

    baseline_ids: frozenset[str]  # ObjectId of each baseline of the export
    project_baselines: dict[str, str]  # ObjectId of a project -> its Project Baseline, one of ``baseline_ids``
    same_content: Callable[[str, str], bool]  # whether two baselines of the export are copies of one baseline


@dataclass(frozen=True)
class Resolution:
    """The baseline found for an update, and what found it."""

    found_by: str  # IN_FILE, IN_EXPORT, LOADED_UPDATE, SAME_GENERATION, UNDECIDED or NOT_FOUND
    baseline_id: str = ""  # the baseline to read: an id of the file or of the export, or a loaded project
    version_before: str = ""  # the project of the export created just before the update's, when looked for
    version_after: str = ""  # the one created just after
    note: str = ""  # why nothing was taken

    @property
    def is_exact(self) -> bool:
        """Whether the baseline is the one the update names, as P6 measured against it."""
        return self.found_by in (IN_FILE, IN_EXPORT)


@dataclass(frozen=True)
class Version:
    """A project of the export, as ``versions_of_the_same_date`` reads it.

    A date is written as the XER writes one ("2026-03-02 08:00"), blank when the export does not give it.
    """

    object_id: str
    status_date: str
    date_added: str
    baseline_id: str  # its Project Baseline when the export holds it, blank otherwise


def versions_of_the_same_date(status_date: str, project_added: str, versions: Iterable[Version]) -> list[Version]:
    """Return the versions of the export that can be copies of an update's project made at its status date.

    Where the planner keeps a copy of the project for each period, the copy carries a copy of the
    baseline then in force (Oracle, "Copy Project Options dialog box", Baselines). Kept: a version of
    the same status day, added to the database (DateAdded) once the update's project was
    (PROJECT.add_date; a version added before it cannot be a copy of it), whose Project Baseline the
    export holds. Shown by the Debug page; ``resolution`` does not read it.
    """
    if not status_date or not project_added:
        return []
    return [
        version
        for version in versions
        if version.baseline_id and version.status_date[:10] == status_date[:10] and version.date_added >= project_added
    ]


def resolution(
    pointer: str, project_id: str, in_file: bool, loaded_project_ids: frozenset[str], export: Export | None
) -> Resolution:
    """Find the baseline of an update whose project is ``project_id`` and that names ``pointer``.

    ``in_file``: its own file holds that baseline. ``loaded_project_ids``: the projects the loaded
    updates were read from. ``export``: the P6 XML export of baselines, None without one.
    """
    if in_file:
        return Resolution(IN_FILE, pointer)
    if not pointer:
        return Resolution(NOT_FOUND, note="the update names no baseline")
    if export is not None and pointer in export.baseline_ids:
        return Resolution(IN_EXPORT, pointer)
    if pointer in loaded_project_ids:
        return Resolution(LOADED_UPDATE, pointer)
    if export is None:
        return Resolution(NOT_FOUND, note="no P6 XML export of baselines")
    return _between_versions(project_id, export)


def resolutions(snapshots: Iterable[Snapshot], export: Export | None) -> list[Resolution]:
    """Find the baseline of each update of a series, in the order given (``resolution``).

    An update is not looked for among the other updates of its own project: a pointer to that
    project names the update itself.
    """
    updates = list(snapshots)
    project_ids = frozenset(update.project_id for update in updates)
    return [
        resolution(
            update.file_baseline.proj_id,
            update.project_id,
            update.file_baseline.usable,
            project_ids - {update.project_id},
            export,
        )
        for update in updates
    ]


def _between_versions(project_id: str, export: Export) -> Resolution:
    """Find, the fourth way, the baseline the versions of the export hold on both sides of the project."""
    if not export.project_baselines:
        return Resolution(NOT_FOUND, note="no project of the export names a baseline it holds")
    before, after = versions_around(project_id, export.project_baselines)
    if not before and not after:
        return Resolution(NOT_FOUND, note="the project id is not a number: no order of creation to read")
    if not before or not after:
        side = "before" if not before else "after"
        return Resolution(UNDECIDED, "", before, after, f"no version of the export {side} it")
    baseline_before, baseline_after = export.project_baselines[before], export.project_baselines[after]
    if not export.same_content(baseline_before, baseline_after):
        return Resolution(UNDECIDED, "", before, after, "the versions around it hold different baselines")
    return Resolution(SAME_GENERATION, baseline_before, before, after)


def versions_around(project_id: str, version_ids: Iterable[str]) -> tuple[str, str]:
    """Return the version created just before ``project_id`` and the one created just after.

    By ObjectId read as a number; blank where there is none. The project itself and the ids that
    are no number are left out.
    """
    if not project_id.isdecimal():
        return "", ""
    number = int(project_id)
    numbers = sorted(int(version_id) for version_id in version_ids if version_id.isdecimal())
    earlier = [candidate for candidate in numbers if candidate < number]
    later = [candidate for candidate in numbers if candidate > number]
    return (str(earlier[-1]) if earlier else "", str(later[0]) if later else "")
