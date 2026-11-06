"""Value checks on the tables of one file, before the model types them or right after.

One function per rule. Each repairs the frame the way the rule says (a duplicate key keeps
its first row, an unusable number reads as 0, an unknown link type is dropped...) and adds
one line to the snapshot's warnings, so a file that P6 would never write still loads, and
says what was done to it. The CPM engine, the checks and the pages then receive values that
are unique, finite and bounded. Nothing here reads P6 semantics: the model does.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

MAX_HOURS = 1e6  # a duration or lag above this (114 years of 24 h days) is not a schedule value
MAX_SEQUENCE = 10**6 - 1  # PROJWBS.seq_num is formatted on six digits in the WBS sort key
LISTED = 5  # how many offending ids a warning names
# An ISO 8601 offset or "Z" at the end of a date cell: P6 writes naive local times only, and one
# such cell among naive ones makes pandas refuse the whole column ("Mixed timezones").
TIMEZONE_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})\s*$")
NAIVE_DATE_LENGTH = 16  # "YYYY-MM-DD HH:MM": only a longer cell can carry an offset (checked with the regex)
RELATIONSHIP_TYPES = frozenset({"PR_FS", "PR_SS", "PR_FF", "PR_SF"})


def _listed(values) -> list[str]:
    return [str(v) for v in list(values)[:LISTED]]


def unique_rows(frame: pd.DataFrame, key: str, table: str, source: str, warnings: list[str]) -> pd.DataFrame:
    """``frame`` with one row per ``key`` (the first), and a warning naming the repeated keys."""
    repeated = frame[key][frame[key].duplicated()]
    if repeated.empty:
        return frame
    warnings.append(
        f"{source}: {len(repeated)} {table} row(s) repeat a {key} {_listed(repeated.unique())}; the first row is kept"
    )
    return frame.drop_duplicates(key, keep="first")


def timezone_cells(values: pd.Series) -> pd.Series:
    """True for the cells that end with a time-zone offset or "Z"."""
    text = values.astype(str)
    suspect = text.str.len() > NAIVE_DATE_LENGTH
    mask = pd.Series(False, index=values.index)
    if suspect.any():
        mask[suspect] = text[suspect].str.contains(TIMEZONE_SUFFIX, regex=True)
    return mask


def blank_timezones(
    frame: pd.DataFrame, columns: list[str], table: str, source: str, warnings: list[str]
) -> pd.DataFrame:
    """The date ``columns`` of ``frame`` with time-zoned cells blanked (they read as NaT), and a warning."""
    count = 0
    for column in columns:
        mask = timezone_cells(frame[column])
        if mask.any():
            count += int(mask.sum())
            frame[column] = frame[column].mask(mask, "")
    if count:
        warnings.append(f"{source}: {count} {table} date cell(s) carry a time zone; read as blank")
    return frame


def bounded_sequence(values: pd.Series, table: str, source: str, warnings: list[str]) -> pd.Series:
    """``seq_num`` as integers in [0, MAX_SEQUENCE]: blank or text is 0, beyond the bound is clipped."""
    numbers = pd.to_numeric(values, errors="coerce").fillna(0)
    clipped = (numbers < 0) | (numbers > MAX_SEQUENCE)
    if clipped.any():
        warnings.append(f"{source}: {int(clipped.sum())} {table} seq_num value(s) outside 0..{MAX_SEQUENCE}; clipped")
    return numbers.clip(0, MAX_SEQUENCE).astype(int)


def usable_hours(values: pd.Series, what: str, names: pd.Series, source: str, warnings: list[str]) -> pd.Series:
    """``values`` (hours) with the infinite ones and those beyond ``MAX_HOURS`` read as 0; blank stays blank."""
    unusable = values.notna() & (~np.isfinite(values) | (values.abs() > MAX_HOURS))
    if not unusable.any():
        return values
    warnings.append(
        f"{source}: {int(unusable.sum())} {what}(s) not finite or above {MAX_HOURS:g} h "
        f"{_listed(names[unusable])}; read as 0"
    )
    return values.mask(unusable, 0.0)


def nonnegative_remaining(values: pd.Series, source: str, warnings: list[str]) -> pd.Series:
    """Remaining durations below zero read as 0."""
    negative = values < 0
    if not negative.any():
        return values
    warnings.append(f"{source}: {int(negative.sum())} activities with a negative remaining duration, read as 0")
    return values.mask(negative, 0.0)


def known_relationship_types(relationships: pd.DataFrame, source: str, warnings: list[str]) -> pd.DataFrame:
    """TASKPRED rows whose ``pred_type`` is one of FS, SS, FF, SF; the others are dropped and named."""
    unknown = ~relationships["pred_type"].isin(RELATIONSHIP_TYPES)
    if not unknown.any():
        return relationships
    kinds = _listed(relationships.loc[unknown, "pred_type"].astype(str).unique())
    warnings.append(f"{source}: {int(unknown.sum())} relationship(s) with an unknown type {kinds}; ignored")
    return relationships[~unknown]


def placeholder_clashes(local_codes: pd.Series, placeholders: pd.Series, source: str, warnings: list[str]) -> None:
    """Warn when an Activity ID of the project is written like an external placeholder ``[ext]<task_id>``
    that the relationships also use: the two read as one predecessor."""
    clashes = sorted(set(local_codes) & set(placeholders))
    if clashes:
        warnings.append(
            f"{source}: activity ID(s) {clashes[:LISTED]} are also the placeholder names of external "
            "predecessors; those links cannot be told apart"
        )
