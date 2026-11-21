"""The session's caches of what the pages compute: memoised analyses, the checks' results, the score job."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import streamlit as st

from xerscope.analysis import AnalysisContext, Baseline, Standard
from xerscope.analysis.checks import CheckResult, run_metric, run_standard
from xerscope.analysis.standards import Metric
from xerscope.app.baselines import baseline_for, data_identity, snapshot_identity
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot

MEMO_SIZE = 128  # entries per session; a standard holds at most 18 metrics, each its own entry


def memo(key: tuple, function, *arguments, keep: bool = True, baseline: bool = True, ev_basis: bool = True):
    """Return the value cached per session, keyed on the loaded files and the baseline.

    Heavy analyses run once per data set.

    The full key: ``data_identity`` (files, projects, and the baseline and EV basis unless the
    analysis reads neither: ``baseline`` / ``ev_basis`` False), then ``key``, which names the
    analysis and everything else it reads. ``function(*arguments)`` runs only on a cache miss;
    ``keep=False`` then returns the value without storing it (a series over every update that
    should not hold each update's frames). The cache lives in the session's state, never
    process-wide; past MEMO_SIZE entries the least recently used goes. Callers do not modify what
    it returns: the next reader gets the same object.
    """
    cache = st.session_state.setdefault("_memo", {})
    full_key = data_identity(baseline, ev_basis) + key
    if full_key in cache:
        cache[full_key] = cache.pop(full_key)  # most recently used last
        return cache[full_key]
    value = function(*arguments)
    if keep:
        while len(cache) >= MEMO_SIZE:
            cache.pop(next(iter(cache)))
        cache[full_key] = value
    return value


def metric_result(metric: Metric, snapshot: Snapshot, store: SnapshotStore, keep: bool = True) -> CheckResult:
    """Return ``metric`` on ``snapshot`` against the sidebar's baseline for it, once per session.

    Health, Audit and the BEI of Earned value read the same entry. Key (with ``memo``'s): the metric as
    written (rule, parameters, target, standard: its repr) and the update (file, data date). Not the EV
    basis: no rule reads what it sets (the ev_* columns, the assignment costs).
    """
    return memo(
        _metric_key(metric, snapshot),
        lambda: run_metric(metric, AnalysisContext(snapshot, store, baseline_for(snapshot))),  # built on a miss only
        keep=keep,
        ev_basis=False,
    )


def _metric_key(metric: Metric, snapshot: Snapshot) -> tuple:
    """Return the memo key of one metric on one update: the metric's definition, the file and its data date."""
    return ("metric", repr(metric), *snapshot_identity(snapshot))


def standard_results(standard: Standard, snapshot: Snapshot, store: SnapshotStore) -> list[CheckResult]:
    """Return every check of ``standard`` on ``snapshot``, each through :func:`metric_result`."""
    return [metric_result(metric, snapshot, store) for metric in standard.metrics]


def hold_standard_results(standard: Standard, snapshot: Snapshot, results: list[CheckResult]) -> None:
    """Store the results computed outside the script run (ScoreJob) where ``metric_result`` reads."""
    for metric, result in zip(standard.metrics, results, strict=True):
        memo(_metric_key(metric, snapshot), lambda result=result: result, ev_basis=False)


@dataclass
class ScoreJob:
    """Hold the standards' checks on one update, computed in a thread for the Overview's score cards.

    ``results`` fills per standard id as each finishes.
    """

    identity: tuple
    snapshot: Snapshot
    store: SnapshotStore
    baseline: Baseline | None
    standards: dict[str, Standard]
    results: dict[str, list[CheckResult] | str] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)  # standard ids already written to the memo
    done: bool = False
    cancelled: bool = False  # set when another data set or baseline replaces this one
    thread: threading.Thread | None = None

    def run(self) -> None:
        """Compute each standard in turn into ``results``, then set ``done``."""
        context = AnalysisContext(self.snapshot, self.store, self.baseline)
        for key, standard in self.standards.items():
            results: list[CheckResult] | str
            try:
                results = run_standard(standard, context, stopped=lambda: self.cancelled)
            except Exception as exc:  # noqa: BLE001 - shown as an error on the Overview, not lost
                results = str(exc)
            if self.cancelled:
                break  # computed for another data set or baseline: not kept
            self.results[key] = results
        self.done = True


def score_job(snapshot: Snapshot, store: SnapshotStore, standards_: dict[str, Standard]) -> ScoreJob:
    """Return the job computing ``standards_`` on ``snapshot`` for the current data set, started on the first call.

    A new data set or baseline starts another. The results already in are written to the memo, so Schedule
    health reads them.
    """
    identity = (*data_identity(ev_basis=False), snapshot.source, str(snapshot.data_date), tuple(standards_))
    job: ScoreJob | None = st.session_state.get("_score_job")
    if job is None or job.identity != identity:
        if job is not None:
            job.cancelled = True  # its results are for another data set or baseline
        job = ScoreJob(identity, snapshot, store, baseline_for(snapshot), dict(standards_))
        job.thread = threading.Thread(target=job.run, name="xerscope-scores", daemon=True)
        job.thread.start()
        st.session_state["_score_job"] = job
    for key, results in list(job.results.items()):
        if key not in job.held and not isinstance(results, str):
            hold_standard_results(job.standards[key], snapshot, results)
            job.held.add(key)
    return job


def standard_results_held(standard: Standard, snapshot: Snapshot) -> list[CheckResult] | None:
    """Return the results :func:`standard_results` would return, if every one is already cached, else None.

    Computes nothing.
    """
    results = [
        memo(_metric_key(metric, snapshot), lambda: None, keep=False, ev_basis=False) for metric in standard.metrics
    ]
    return None if any(result is None for result in results) else results
