"""Fuzzing the file boundary: a crafted .xer must fail to load, never crash or escape.

Two properties, over arbitrary bytes and over mutations of a valid export built by
``xerkit.xer_text`` (tabs, newlines and ``%`` tags inserted, deleted or replaced, random bytes
spliced in):

- ``parse_bytes`` returns a ``RawXer`` or raises ``XerError``, never another exception;
- ``build_snapshot(parse_bytes(x))`` returns a ``Snapshot`` or raises ``XerError``.

``HYPOTHESIS_PROFILE=ci`` runs 1000 examples per property instead of 200.

A crash Hypothesis finds is recorded in ``KNOWN_CRASHES`` with its minimal example and the audit
finding it belongs to (``AUDIT-XER-nn``, or "new"). ``test_known_crash_examples`` replays each as
``xfail(strict=False)``: it fails while the defect exists and passes once it is fixed, without
breaking the suite either way (Hypothesis's own ``@example(...).xfail`` is strict, so pytest's
marker is used instead). The property tests discard an example that hits a known crash site,
so they stay green and keep looking for crashes nobody has recorded. Fixing a defect: remove its
entry here, the audit report's test loses its xfail marker at the same time.
"""

from __future__ import annotations

import os
import traceback

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from xerkit import clndr_data, xer_text

from xerscope.xer import Snapshot, build_snapshot
from xerscope.xer.parser import RawXer, XerError, parse_bytes

_HEALTH = [HealthCheck.too_slow, HealthCheck.filter_too_much]
settings.register_profile("default", max_examples=200, deadline=None, suppress_health_check=_HEALTH)
settings.register_profile("ci", max_examples=1000, deadline=None, suppress_health_check=_HEALTH)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

BASE = xer_text(
    [{"task_code": "A"}, {"task_code": "B", "target_drtn_hr_cnt": "16"}, {"task_code": "C"}],
    [("A", "B", "FS", 0), ("B", "C", "SS", 8)],
    rsrc=["A"],
).encode("cp1252")

TOKENS = [b"\t", b"\n", b"\r\n", b"%T\t", b"%F\t", b"%R\t", b"%E", b"%", b"ERMHDR\t", b"\x00", b"\xff", b'"', b"\\"]

# (finding, exception, "module.py:function", minimal failing input). The crash site, not the bytes,
# identifies a known crash: random inputs reach the same line in many ways.


def _calendar_file(start: str, finish: str) -> bytes:
    """A one-task export whose calendar holds one work period ``start``-``finish`` on Monday."""
    blob = clndr_data(range(2, 3), [(start, finish)])
    return (
        f"%T\tCALENDAR\n%F\tclndr_id\tclndr_data\n%R\t1\t{blob}\n"
        "%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA"
    ).encode()


KNOWN_CRASHES = [
    ("AUDIT-XER-03", KeyError, "parser.py:parse_text", b"%T\t\n%R"),  # empty table name, then a row
    (
        "new: TASKRSRC with an empty %F line reaches _assignments without task_id",
        KeyError,
        "model.py:_assignments",
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA\n%T\tTASKRSRC\n%F\t\n%R",
    ),
    (  # duplicate %F column: a DataFrame with two rsrc_id columns reaches the model
        "AUDIT-XER-04",
        NotImplementedError,
        "model.py:_assignments",
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA\n"
        b"%T\tTASKRSRC\n%F\trsrc_id\ttask_id\trsrc_id\n%R",
    ),
    (  # the same, with no activity row
        "AUDIT-XER-04",
        TypeError,
        "model.py:_assignments",
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\n"
        b"%T\tTASKRSRC\n%F\trsrc_id\ttask_id\trsrc_id\n%R",
    ),
    (  # duplicate %F column in TASKPRED
        "AUDIT-XER-04",
        ValueError,
        "model.py:_relationships",
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA\n"
        b"%T\tTASKPRED\n%F\ttask_id\tpred_task_id\tproj_id\tproj_id\n%R",
    ),
    ("AUDIT-XER-14", ValueError, "calendar.py:_interval", _calendar_file("a:b", "17:00")),  # start not hh:mm
    ("AUDIT-XER-14", ValueError, "calendar.py:_interval", _calendar_file("8:00", "")),  # finish empty
]


def _site(exc: BaseException) -> str:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "xerscope" in f.filename]
    return f"{os.path.basename(frames[-1].filename)}:{frames[-1].name}" if frames else "?"


def _known(exc: BaseException, raw: RawXer | None = None) -> bool:
    if raw is not None and any(t.columns.duplicated().any() for t in raw.tables.values()):
        return True  # AUDIT-XER-04: a duplicate %F column trips the model wherever that table is read
    return any(isinstance(exc, kind) and _site(exc) == site for _, kind, site, _ in KNOWN_CRASHES)


@st.composite
def mutated_export(draw) -> bytes:
    """``BASE`` with a few edits: a token or random bytes inserted, a span deleted or replaced."""
    data = bytearray(BASE)
    for _ in range(draw(st.integers(min_value=1, max_value=6))):
        pos = draw(st.integers(min_value=0, max_value=len(data)))
        payload = draw(st.one_of(st.sampled_from(TOKENS), st.binary(min_size=1, max_size=8)))
        op = draw(st.sampled_from(["insert", "delete", "replace"]))
        end = min(len(data), pos + draw(st.integers(min_value=1, max_value=40)))
        if op == "insert":
            data[pos:pos] = payload
        elif op == "delete":
            del data[pos:end]
        else:
            data[pos:end] = payload
    return bytes(data)


INPUTS = st.one_of(st.binary(max_size=4096), mutated_export())


def _parse(data: bytes) -> RawXer | None:
    """A RawXer, None for a clean refusal; any other exception is the failure."""
    try:
        raw = parse_bytes(data, source="fuzz.xer")
    except XerError:
        return None
    assert isinstance(raw, RawXer)
    return raw


def _snapshot(raw: RawXer) -> Snapshot | None:
    try:
        snapshot = build_snapshot(raw)
    except XerError:
        return None
    assert isinstance(snapshot, Snapshot)
    return snapshot


def _load(data: bytes) -> None:
    raw = _parse(data)
    if raw is not None:
        _snapshot(raw)


@given(INPUTS)
def test_parse_bytes_returns_rawxer_or_xererror(data: bytes):
    try:
        _parse(data)
    except XerError:
        raise
    except Exception as exc:
        assume(not _known(exc))  # recorded in KNOWN_CRASHES: the example is discarded, not passed
        raise


@given(INPUTS)
def test_build_snapshot_returns_snapshot_or_xererror(data: bytes):
    raw = None
    try:
        raw = _parse(data)
        if raw is not None:
            _snapshot(raw)
    except XerError:
        raise
    except Exception as exc:
        assume(not _known(exc, raw))
        raise


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(data, id=site, marks=pytest.mark.xfail(strict=False, reason=reason))
        for reason, _, site, data in KNOWN_CRASHES
    ],
)
def test_known_crash_examples(data: bytes):
    _load(data)
