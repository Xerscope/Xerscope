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


def unreadable_cells(
    written: pd.Series, typed: pd.Series, where: str, codes: pd.Series, source: str, warnings: list[str]
) -> None:
    """Warn of the cells of ``where`` ("TABLE.column") the file fills but typing read as blank.

    ``written``: the column as the file holds it; ``typed``: the same once typed (a number or a date).
    A text that is no number or date, an infinite number, or a date outside the range the model reads
    (``model.EARLIEST_DATE`` to ``LATEST_DATE``) is read as blank, as a cell left empty: the warning says
    which tasks, by ``codes``, so that the value is not mistaken for an absent one.
    """
    filled = written.notna() & (written.astype(str).str.strip() != "")
    lost = filled & typed.isna()
    if lost.any():
        warnings.append(
            f"{source}: {where}: {int(lost.sum())} value(s) unreadable or out of range, read as blank "
            f"{_listed(codes[lost])}"
        )


def unreadable_status_date(project_row: pd.Series, taken_from: str, source: str, warnings: list[str]) -> None:
    """Warn when PROJECT.last_recalc_date is filled but unreadable, so that the status date comes from
    ``taken_from`` (plan_start_date, or "" for none) instead of the date P6 last scheduled the project."""
    written = str(project_row.get("last_recalc_date") or "").strip()
    if not written or taken_from == "last_recalc_date":
        return
    instead = {"": "none read"}.get(taken_from, f"taken from {taken_from}")
    warnings.append(f"{source}: PROJECT.last_recalc_date {written!r} unreadable or out of range: status date {instead}")


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


def placeholder_clashes(local_codes: pd.Series, placeholders: pd.Series, source: str, warnings: list[str]) -> None:
    """Warn when an Activity ID of the project is written like an external placeholder ``[ext]<task_id>``
    that the relationships also use: the two read as one predecessor."""
    clashes = sorted(set(local_codes) & set(placeholders))
    if clashes:
        warnings.append(
            f"{source}: activity ID(s) {clashes[:LISTED]} are also the placeholder names of external "
            "predecessors; those links cannot be told apart"
        )
