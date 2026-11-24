# ADR-0017: Files read in background worker processes; per-session memo cache keyed on data identity and baseline

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-06 (`25a0ba9`, #137: files read on worker processes, pages drawn once); the session memo keyed on `data_identity` dates from 2026-11-05 (`d12e576`, #102); the cap of two workers from 2026-11-08 (`ba98b86`, #145) |
| Scope | `src/xerscope/app/reading.py`, `app/loading.py` (`LoadJob`, `_poll_load`, `background_jobs`), `app/cache.py` (`memo`, `metric_result`, `ScoreJob`, `score_job`, `MEMO_SIZE`), `app/baselines.py` (`data_identity`, `_baseline_identity`, `snapshot_identity`), `app/session.py` (`_parse`, `_cache_for`), `app/streamlit_app.py` (the `__main__` guard), `deploy/compose.yaml` (`XERSCOPE_LOAD_WORKERS`) |
| Sources | `5a2db20` "App: parsed files are cached per session, not in a process-wide st.cache_data (#17)"; `d12e576` "Performance: one cached result per metric, Health trend on request, narrower cache keys (#102)"; `af57a08` "App: pages linked to each other, one update per session, background reading of the series, UI fixes (#125)"; `25a0ba9` (#137); `ba98b86` "Loading: at most two worker processes; an unusable XERSCOPE_LOAD_WORKERS falls back to the default (#145)"; `52b5fb9` "Performance: fragments and workers, measured (#164)"; `017cb42` "refactor(front): no baseline rebuilt by a rerun with nothing changed"; [docs/architecture.md §7](../architecture.md) (`loading.py`, `reading.py`, `cache.py`, `state.py`); [docs/deploy.md §7](../deploy.md); Python documentation, multiprocessing, "Safe importing of main module" |

## Context

A series is ten to twenty weekly XER exports, several megabytes each. Reading one is parsing plus
building a `Snapshot`: pure Python and pandas work. Streamlit reruns the whole page script on most
interactions, and every page reads the same heavy results (the checks of four built-in standards,
the earned value series, the WBS rollup). Three forces follow:

- Reading the files one after the other in the page run blocks every page for seconds; reading
  them in threads gains nothing, since threads share one core under the GIL.
- A cached result must change exactly when what it was computed from changes: the files, the
  project read from each, the baseline in use and, for earned value, the EV basis. A key too
  wide recomputes for nothing (a change of EV basis rerunning every check); a key too narrow
  shows a stale result.
- The deployment target is a NAS with a memory cap (docs/deploy.md §7): each process reading a
  40 MB export holds about 1 GB while it reads.

A process-wide cache (`st.cache_data`) was used for parsed files at first and dropped: every
session of the process shared it, it had no lifetime, and a parsed upload stayed in memory after
its session ended (`5a2db20`).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Read every file in the page run, one after the other (before `af57a08`) | simplest | the first page waits for the whole series: "18 files, several seconds each on real exports" (`af57a08`) |
| Read in a background thread only | no process start | parsing is pure Python: threads share one core (GIL), the series still reads at sequential speed |
| **A background thread that hands the files to a `spawn` process pool, capped at two processes, with a sequential fallback (chosen)** | process start and pickling of each `Snapshot` back | memory: one export held per worker; the NAS default is one worker (`XERSCOPE_LOAD_WORKERS` 1 in compose) |
| Cache results process-wide with `st.cache_data` | one line per function | shared by every session, no lifetime: dropped in `5a2db20` for the parse cache |
| **A per-session memo keyed on the data identity, then on what each analysis reads, least recently used out past `MEMO_SIZE` (chosen)** | every call site names its key and what it does not read | a key that forgets an input is a stale-result bug: pinned by `tests/test_cache_invariant.py` |

## Decision

**Reading on worker processes.** On Done in the Files window, `loading._start_load` starts a
`LoadJob` in a daemon thread (`xerscope-load`), seeded with the files the session parsed already
(`_parsed_snapshots`) and ordered most recent first (`files_window.most_recent_first`).
`LoadJob.run` hands the others to `reading.read_updates`:

- `reading.worker_count` takes `XERSCOPE_LOAD_WORKERS` (`WORKERS_VARIABLE`), else one per core,
  never above `MAX_WORKERS = 2` nor above the number of files. A value that is not a whole ASCII
  number of at least 1 (`""`, `"0"`, `"-1"`, `"two"`, `"²"`, `"1.5"`) is ignored and the default
  applies.
- With more than one file and more than one worker, `_read_on_workers` reads on a
  `ProcessPoolExecutor` with `multiprocessing.get_context("spawn")`: a fresh interpreter, never a
  fork of the server and its threads. `reading.py` imports no Streamlit; `streamlit_app.py` keeps
  the app behind `if __name__ == "__main__"`, since a spawned worker runs the parent's main file
  again as `__mp_main__`.
- A pool that cannot start or breaks (`OSError`, `BrokenProcessPool`, `RuntimeError`: no process
  allowed, a worker killed for memory) ends the pool; `read_updates` then reads the files not yet
  yielded in the thread. `XERSCOPE_LOAD_WORKERS=1` reads every file in the thread.
- Measured (`reading.py` docstring, `25a0ba9`): ten 3.8 MB updates in 3.3 s one after the other,
  1.6 s on four processes, process start included. Two is the most the NAS deployment stays stable
  with, each process holding the file it reads (`ba98b86`); `deploy/compose.yaml` sets
  `XERSCOPE_LOAD_WORKERS: ${XERSCOPE_LOAD_WORKERS:-1}`, to be raised with `XERSCOPE_MEM_LIMIT`.

**The pages wait, then draw once.** `_poll_load`, a fragment run every second, redraws only the
progress bar ("Reading the updates · n/N") and calls `st.rerun(scope="app")` once when the job is
done; the pages then draw on the complete series, never on a partial one.

**Scores in a second thread.** Once the series is read and its baseline set, the Overview's
`score_section` calls `cache.score_job`, which runs the built-in standards on the latest update
in a `ScoreJob` thread (`xerscope-scores`) and writes each standard's results where
`metric_result` reads them (`hold_standard_results`), so Schedule health reuses them. A new data
set, baseline or standard (`_score_identity`, the standards entering by their repr) cancels the
running job and starts another.

**Neither thread touches the session state.** `LoadJob` and `ScoreJob` fill their own fields
(`results`, `cache`, `done`, `cancelled`); the script run collects them (`loading._collect`,
`score_job`). A new choice of files (`_forget_previous_series`) cancels both jobs (files not
started are not read, checks not started are not computed), drops the memo and the baselines read
from the files. The parse cache is pruned once the new series is read (`loading._keep_parsed`
keeps only the files of that series), so an unchanged file is not parsed twice.

**Synchronous for the tests.** `loading.background_jobs()` is false when `XERSCOPE_SYNC_LOAD` is
`1`, `true` or `yes` (set by `tests/conftest.py`): everything then runs in the page run, and the
Overview offers a "Compute scores" button instead of the score thread.

**The session memo.** `cache.memo(key, function, *arguments, keep=True, baseline=True,
ev_basis=True)` stores its value in `st.session_state["_memo"]`, never process-wide. The full key
is `baselines.data_identity(baseline, ev_basis) + key`:

- `data_identity` = the files (`signature`: names and content digests), the project read from each
  file, and, unless `baseline=False`, the baseline in use (`_baseline_identity`: the choice, the
  EV basis unless `ev_basis=False`, the "Link renumbered tasks by GUID" option, an uploaded file's
  digest and project; in "Baseline in each file" mode the pointer of each file, the fallback, the
  choices of undecided updates and the export in use).
- `key` names the analysis and everything else it reads.
- An analysis that reads no baseline (change log, PPC, milestones, exports, forecast) passes
  `baseline=False`; one that reads no EV basis (the checks, the WBS rollup) passes
  `ev_basis=False`. A change it does not read then recomputes nothing.
- Past `MEMO_SIZE = 128` entries the least recently used goes. `keep=False` returns the value
  without storing it (a series over every update that should not hold each update's frames).

**One result per check.** `cache.metric_result(metric, snapshot, store)` holds one `CheckResult`
per (metric as written, update, baseline): its key is `("metric", repr(metric), source,
data_date)` under `data_identity(ev_basis=False)`, and it runs
`run_metric(metric, AnalysisContext(snapshot, store, baseline_for_checks(snapshot)))` on a miss
only. Schedule health, Audit and the BEI of Earned value read the same entry; the health trend
(computed on request) and the BEI series reuse the entries and keep only their numbers. No check
reads the columns the EV basis sets, so a change of EV basis reruns no check.

**No rebuild on a rerun with nothing changed** (`017cb42`): `baselines.baseline_for` is cached in
the session on `data_identity()` plus (file, link) through `session._cache_for`, which empties its
slot when the identity moves; the background load does not parse again a file the session holds.

## Consequences

Positive:

- The first page draws once, on the whole series; on a workstation the series reads about twice as
  fast as one file after the other.
- A rerun with nothing changed recomputes nothing; a change recomputes only what reads it.
- Each session's data and results stay in that session and go with it.
- A worker killed for memory degrades to sequential reading instead of failing the load.

Negative:

- Memory: each worker holds the export it reads; on the NAS the default is one worker
  ([docs/backlog.md](../backlog.md), "App": memory per loaded file).
- Every memo call site must declare what it does not read; a forgotten input is a stale result.
- Two load paths (background and `XERSCOPE_SYNC_LOAD`) must give the same results and errors.

## Verification

- `tests/test_reading.py::test_worker_count_follows_the_variable_and_never_exceeds_the_files`,
  `::test_worker_count_never_exceeds_two`, `::test_an_unusable_variable_falls_back_to_the_default`,
  `::test_every_file_is_read_as_one_after_the_other`, `::test_a_stop_drops_the_files_not_started`,
  `::test_a_worker_does_not_run_the_app_script`, `::test_an_unreadable_file_is_named_and_the_others_load`.
- `tests/test_app_background.py::test_the_pages_wait_for_the_whole_series_then_draw_once`,
  `::test_a_new_choice_of_files_stops_the_reading_and_forgets_the_previous_series`,
  `::test_a_standard_finished_while_the_overview_is_shown_fills_its_card_without_an_app_rerun`,
  `::test_both_load_paths_give_the_same_errors_for_the_same_bad_files`,
  `::test_a_score_job_cancelled_during_a_standard_runs_none_of_its_other_checks`.
- `tests/test_app_cache.py::test_metric_result_runs_once_then_again_for_any_other_input`,
  `::test_metric_result_is_not_run_again_for_another_ev_basis`,
  `::test_memo_drops_the_least_recently_used_entry_past_its_size`,
  `::test_health_audit_and_earned_value_compute_each_result_once`,
  `::test_cached_results_are_left_as_a_fresh_calculation_gives_them`,
  `::test_pages_that_read_no_baseline_are_not_recomputed_for_another`,
  `::test_a_rerun_with_nothing_changed_builds_no_baseline_and_lists_the_folder_once`,
  `::test_a_series_change_reads_only_the_files_the_session_has_not_parsed`.
- `tests/test_cache_invariant.py::test_a_toggled_option_shows_what_a_fresh_session_shows`.
- `tests/test_loading.py` (`load_series` reads the upload, tells the count then each file, does
  not read the same source again).
- `tests/test_docker.py::test_remote_load_workers_follow_the_env_file_and_default_to_one`
  (`XERSCOPE_LOAD_WORKERS: ${XERSCOPE_LOAD_WORKERS:-1}` in the app service of
  `deploy/compose.yaml`, commented in `deploy/.env.example`).

## References

- `src/xerscope/app/reading.py`: `MAX_WORKERS`, `WORKERS_VARIABLE`, `worker_count`, `read_update`,
  `read_updates`, `_read_on_workers`, `store_of`.
- `src/xerscope/app/loading.py`: `LoadJob`, `_start_load`, `_parsed_snapshots`, `_collect`,
  `_poll_load`, `background_jobs`, `_forget_previous_series`, `_keep_parsed`, `load_series`.
- `src/xerscope/app/cache.py`: `memo`, `MEMO_SIZE`, `metric_result`, `_metric_key`,
  `hold_standard_results`, `ScoreJob`, `score_job`, `_score_identity`.
- `src/xerscope/app/baselines.py`: `data_identity`, `_baseline_identity`, `snapshot_identity`,
  `baseline_for`; `src/xerscope/app/session.py`: `_parse`, `_cache_for`.
- `src/xerscope/app/views/overview.py:score_section`.
- `deploy/compose.yaml` (`XERSCOPE_LOAD_WORKERS`, `XERSCOPE_MEM_LIMIT`).
- [docs/architecture.md](../architecture.md) §7 (`loading.py`, `reading.py`, `cache.py`, `state.py`);
  [docs/deploy.md](../deploy.md) §7.
- Related: ADR-0006 (the series store), ADR-0016 (the app), ADR-0018 (which baseline each page
  reads, part of the cache key).
