"""The baselines a P6 XML baseline file holds, as the Debug page lists them.

They are held against the baseline each update names: PROJECT.sum_base_proj_id is the ObjectId of
a BaselineProject of the export.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

import pandas as pd

from xerscope.xer.parser import XerError
from xerscope.xer.pmxml import DiskFile, XmlBaseline, is_pmxml, list_baselines


def file_baselines(baseline_files: Iterable[tuple[str, bytes | DiskFile]]) -> list[XmlBaseline] | None:
    """Return the baselines of the baseline file in use when it is a P6 XML export.

    ``baseline_files``: its name and contents. None for an XER, for no file, and for an export that
    cannot be read (the sidebar says so where the file is chosen).
    """
    exports = [(data, name) for name, data in baseline_files if is_pmxml(data)]
    try:
        return list_baselines(*exports[0])[0] if exports else None
    except XerError:
        return None


def xml_baselines_table(xml_baselines: list[XmlBaseline], named_baseline_ids: Iterable[str]) -> pd.DataFrame:
    """Return one row per baseline of the file, in the order of the file.

    Under the names of ``XmlBaseline``: its ObjectId, code, name and data date, the project it was
    taken from and its activities. ``updates_naming_it`` counts it in ``named_baseline_ids``, the
    sum_base_proj_id of each update of the series (0: a baseline no update is measured against).
    """
    named = list(named_baseline_ids)
    table = pd.DataFrame(xml_baselines, columns=[field.name for field in dataclasses.fields(XmlBaseline)])
    return table.assign(updates_naming_it=[named.count(object_id) for object_id in table["object_id"]])
