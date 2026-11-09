"""Fuzzing the file boundary: a crafted .xer must fail to load, never crash or escape.

Two properties, over arbitrary bytes and over mutations of a valid export built by
``xerkit.xer_text`` (tabs, newlines and ``%`` tags inserted, deleted or replaced, random bytes
spliced in):

- ``parse_bytes`` returns a ``RawXer`` or raises ``XerError``, never another exception;
- ``build_snapshot(parse_bytes(x))`` returns a ``Snapshot`` or raises ``XerError``.

``HYPOTHESIS_PROFILE=ci`` runs 1000 examples per property instead of 200.

A crash Hypothesis finds is recorded in ``REGRESSIONS`` with its minimal example and the audit
finding it belongs to, then fixed; ``test_former_crashes_stay_fixed`` replays each. The seven
entries are the crashes the audit's fuzzing found, all fixed.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, given, settings
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


REGRESSIONS = [  # the crashes the audit's fuzzing found, each fixed since; replayed as plain inputs
    pytest.param(b"%T\t\n%R", id="XER-03 empty table name then a row"),
    pytest.param(
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA\n%T\tTASKRSRC\n%F\t\n%R",
        id="TASKRSRC without columns",
    ),
    pytest.param(
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA\n"
        b"%T\tTASKRSRC\n%F\trsrc_id\ttask_id\trsrc_id\n%R",
        id="XER-04 duplicate TASKRSRC column",
    ),
    pytest.param(
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\n"
        b"%T\tTASKRSRC\n%F\trsrc_id\ttask_id\trsrc_id\n%R",
        id="XER-04 duplicate TASKRSRC column, no activity",
    ),
    pytest.param(
        b"%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\ttask_code\n%R\t1\tA\n"
        b"%T\tTASKPRED\n%F\ttask_id\tpred_task_id\tproj_id\tproj_id\n%R",
        id="XER-04 duplicate TASKPRED column",
    ),
    pytest.param(_calendar_file("a:b", "17:00"), id="XER-14 period start not hh:mm"),
    pytest.param(_calendar_file("8:00", ""), id="XER-14 period finish empty"),
]


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
    except Exception:
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
    except Exception:
        raise


@pytest.mark.parametrize("data", REGRESSIONS)
def test_former_crashes_stay_fixed(data: bytes):
    _load(data)
