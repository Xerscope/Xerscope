"""Anonymised downloads: the anonymisers, the held bytes and the download buttons."""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from xerscope.anonymize import Anonymizer, LeakError
from xerscope.app.baselines import anonymous_exports, baseline_files_tag, baseline_items
from xerscope.app.session import ANONYMISED, PREPARE_LABEL
from xerscope.export import csv_bytes
from xerscope.xer import RawXer, is_pmxml
from xerscope.xer.parser import parse_bytes
from xerscope.xer.pmxml import DiskFile, index_pmxml, read_pmxml_baseline


def source_raws(name: str, data: bytes | DiskFile) -> list[RawXer]:
    """Return the XER tables of a source file: an XER as read; a P6 XML export, each of its baselines."""
    if is_pmxml(data):
        index = index_pmxml(data, name)  # one pass through the file for all its baselines
        return [read_pmxml_baseline(data, name, baseline.object_id, index) for baseline in index.baselines]
    return [parse_bytes(data[:], source=name)]  # an XER is read whole


def anonymizers_built(session: MutableMapping | None = None) -> dict[frozenset[str], Anonymizer]:
    """Return the anonymizers of the session, by the set of file names each one read."""
    session = st.session_state if session is None else session
    built_anonymizers = session.get("_anonymizers")
    return (
        built_anonymizers[1]
        if built_anonymizers is not None and built_anonymizers[0] == _anonymizers_key(session)
        else {}
    )


def _anonymizers_key(session: MutableMapping) -> tuple:
    """Return the files the session's anonymizers read: a baseline file replaced under the same name is new text."""
    return (session.get("signature"), baseline_files_tag(session))


def anonymizer(
    prepare: bool = False, sources: Iterable[str] | None = None, session: MutableMapping | None = None
) -> Anonymizer | None:
    """Return new codes for ``sources`` (file names; None = every loaded file), kept in the session only.

    Built on request, from those files only: it reads them again. The codes come from one key per
    session (HMAC), so an anonymizer of one update and one of the whole series name an activity
    the same way. One built from more files also serves a download of fewer.
    """
    session = st.session_state if session is None else session
    files_key = _anonymizers_key(session)
    # the updates and the separate baseline file: a name found only in the baseline is a secret too
    items = [*(session.get("items") or []), *baseline_items(session)]
    wanted = frozenset(name for name, _ in items if sources is None or name in set(sources))
    built_anonymizers = session.get("_anonymizers")
    if built_anonymizers is None or built_anonymizers[0] != files_key:
        built_anonymizers = (files_key, {})
        session["_anonymizers"] = built_anonymizers
    built = built_anonymizers[1]
    for names, anonymous in built.items():
        if wanted <= names:
            return anonymous
    if not prepare:
        return None
    key = session.setdefault("_anon_key", secrets.token_bytes(32))
    with st.spinner(f"Reading {len(wanted)} file(s) for the anonymized downloads…"):
        anonymous = Anonymizer.from_raws(
            (raw for name, data in items if name in wanted for raw in source_raws(name, data)), key=key
        )
    if len(built) >= 4:  # a few sets per session: each holds the text values of its files
        built.pop(next(iter(built)))
    built[wanted] = anonymous
    return anonymous


def downloads_ready(sources: Iterable[str] | None = None, session: MutableMapping | None = None) -> bool:
    """Return whether a download of ``sources`` can be offered now: the switch is off, or its anonymizer is built."""
    session = st.session_state if session is None else session
    return not anonymous_exports(session) or anonymizer(sources=sources, session=session) is not None


@dataclass(frozen=True)
class Fetched:
    """Hold the bytes of a download, or why it was refused (a leak of original values)."""

    data: bytes | None
    refused: str
    anonymised: bool


def fetch(
    session: MutableMapping,
    plain: Callable[[], bytes] | None,
    anonymised: Callable[[Anonymizer], bytes],
    sources: Iterable[str] | None = None,
    *,
    prepare: bool = False,
    anonymous: bool | None = None,
) -> Fetched | None:
    """Return the bytes of one download under the sidebar switch (``anonymous`` overrides it).

    Switch off: ``plain()``. On: ``anonymised(anonymizer)`` only, never ``plain``; None while the
    anonymizer for ``sources`` is not built and ``prepare`` is false. A ``LeakError`` is a refusal.
    """
    if anonymous is None:
        anonymous = anonymous_exports(session)
    if not anonymous:
        return Fetched(plain(), "", False)
    try:
        built = anonymizer(prepare=prepare, sources=sources, session=session)
        if built is None:
            return None
        return Fetched(anonymised(built), "", True)
    except LeakError as exc:
        return Fetched(None, str(exc), True)


def hold(session: MutableMapping, slot: str, tag: object, fetched: Fetched) -> None:
    """Keep a built download in the session for the loaded files and ``tag`` (what it was built for)."""
    session[slot] = (session.get("signature"), tag, fetched)


def held(session: MutableMapping, slot: str, tag: object) -> Fetched | None:
    """Return the download kept by ``hold`` if it is for the loaded files and this ``tag``."""
    kept = session.get(slot)
    return kept[2] if kept is not None and kept[:2] == (session.get("signature"), tag) else None


def show_download(
    fetched: Fetched,
    label: str,
    file_name: str,
    mime: str,
    *,
    suffix: bool = True,
    key: str | None = None,
    **button,
) -> None:
    """Show the download button of ``fetched`` (labelled anonymized when it is), or the refusal."""
    if fetched.refused:
        st.error(fetched.refused, icon=":material/block:")
        return
    st.download_button(
        label + (ANONYMISED if fetched.anonymised and suffix else ""),
        fetched.data,
        file_name,
        mime,
        icon=":material/download:",
        key=key,
        **button,
    )


def download(
    label: str,
    file_name: str,
    mime: str,
    plain: Callable[[], bytes],
    anonymised: Callable[[Anonymizer], bytes],
    *,
    key: str | None = None,
    prepare_key: str | None = None,
    sources: Iterable[str] | None = None,
    anon_file_name: str | None = None,
    **button,
) -> None:
    """Show a download under the sidebar switch.

    On, a button prepares the anonymizer of ``sources`` (file names; None = every loaded file) and the
    download shows from then on.
    """
    fetched = fetch(st.session_state, plain, anonymised, sources)
    if fetched is None and st.button(
        PREPARE_LABEL,
        icon=":material/visibility_off:",
        key=f"prepare:{prepare_key or key or file_name}",
        help="Reads the file(s) of this download again to give them new codes. The codes are the same "
        "in every download of the session.",
    ):
        fetched = fetch(st.session_state, plain, anonymised, sources, prepare=True)
    if fetched is not None:
        name = anon_file_name if fetched.anonymised and anon_file_name else file_name
        show_download(fetched, label, name, mime, key=key, **button)


def build_and_hold(
    slot: str,
    tag: object,
    plain: Callable[[], bytes] | None,
    anonymised: Callable[[Anonymizer], bytes],
    sources: Iterable[str] | None,
    *,
    spinner: str | None = None,
    anonymous: bool | None = None,
) -> None:
    """Build a download, reading ``sources`` for the anonymizer if need be, and keep it in ``slot`` for ``tag``.

    ``spinner`` is the text shown while it is built; ``anonymous`` overrides the sidebar switch.
    """
    waiting = st.spinner(spinner) if spinner else contextlib.nullcontext()
    with waiting:
        fetched = fetch(st.session_state, plain, anonymised, sources, prepare=True, anonymous=anonymous)
    hold(st.session_state, slot, tag, fetched)


def show_held(
    slot: str, tag: object, label: str, file_name: str, mime: str, *, key: str, suffix: bool = True
) -> Fetched | None:
    """Show the download kept in ``slot`` for ``tag``, if any, and return it."""
    kept = held(st.session_state, slot, tag)
    if kept is not None:
        show_download(kept, label, file_name, mime, suffix=suffix, key=key)
    return kept


def built_download(
    slot: str,
    tag: object,
    build_label: str,
    label: str,
    file_name: str,
    mime: str,
    plain: Callable[[], bytes] | None,
    anonymised: Callable[[Anonymizer], bytes],
    sources: Iterable[str] | None,
    *,
    key: str,
    build_key: str,
    icon: str,
    spinner: str | None = None,
    anonymous: bool | None = None,
    suffix: bool = True,
) -> Fetched | None:
    """Show a button that builds a download on request, then the download built for ``tag``.

    The built download is kept in ``slot`` until the loaded files or ``tag`` change. Returns it, or
    None while nothing is built.
    """
    if st.button(build_label, icon=icon, key=build_key):
        build_and_hold(slot, tag, plain, anonymised, sources, spinner=spinner, anonymous=anonymous)
    return show_held(slot, tag, label, file_name, mime, key=key, suffix=suffix)


def download_text(label: str, text: str, name: str, mime: str) -> None:
    """Show a download button for a text that holds no schedule data, as it is."""
    data = text.encode("utf-8")
    show_download(Fetched(data, "", False), label, name, mime)


def csv_download(
    frame: pd.DataFrame,
    filename: str,
    label: str = "Download CSV",
    key: str | None = None,
    sources: Iterable[str] | None = None,
    sensitive: bool = True,
) -> None:
    """Show a table as a CSV download, anonymized or not as the sidebar switch says.

    ``sources`` are the files the table comes from, the only ones read to anonymise it.
    ``sensitive=False``: a table with no schedule data, always as is.
    """
    if not sensitive:
        data = csv_bytes(frame)
        show_download(Fetched(data, "", False), label, filename, "text/csv", key=key)
        return
    download(
        label,
        filename,
        "text/csv",
        lambda: csv_bytes(frame),
        lambda anonymous: anonymous.csv(frame),
        key=key,
        sources=sources,
    )
