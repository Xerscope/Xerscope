# ADR-0003: Activities are identified by task_code (Activity ID), never task_id

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: "Key decisions" of `xer/model.py`) |
| Scope | `src/xerscope/xer/model.py`, `src/xerscope/store.py`, `src/xerscope/export.py`, `src/xerscope/analysis/` (changelog, progress, evm, baseline), `src/xerscope/anonymize.py` |
| Sources | `49ad764` initial commit (`xer/model.py` docstring); `6fb4836` "Model: a predecessor in another project of the file keeps its [ext] code" (2026-10-30); `f7cbe0f` "Renumbered tasks found by GUID; option to link them to the baseline (#118)" (2026-11-05); `5ca0f45` (#165, placeholder clash warning, AUDIT-XER-10); P6 Professional 24/25 help, Renumber Activity IDs; `docs/architecture.md` §2 |

## Context

Every weekly analysis compares an activity with itself in another file: the changelog
(W-1 against W), the history over the series, milestone trend, PPC, earned value against the
baseline, the Gantt comparison and the Power BI fact tables. Two keys exist in an XER `TASK` row:

- `task_id`: the database key of the P6 instance that wrote the export. It is what `TASKPRED`,
  `TASKRSRC` and `PROJCOST` point at inside one file, and it changes when a project is
  re-imported (the demo series renumbers every `task_id` from week to week:
  `tests/test_store.py::test_task_ids_change_but_codes_join`);
- `task_code`: the Activity ID the planner sees and P6 matches a baseline on.

A file can also hold several projects. A predecessor in another project of the same file may
carry an Activity ID that also exists in the analysed project. Before `6fb4836` such a link kept
the other project's Activity ID as `pred_code`, so the CPM and the project-end lookups read it as
a link from the local activity: the successor waited for the wrong predecessor.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Key on `task_id` | none: it is the XER's own key | changes on re-import; no two weeks of a series would join |
| Key on `TASK.guid` | needs the column | not in every file (`tests/test_renumbered.py::test_a_file_without_guid_column_finds_nothing`), may be blank or shared by several tasks of a file; P6 itself matches a baseline by Activity ID |
| Key on `task_code`; `task_id` only to resolve links inside one file; GUID only as an explicit option for renumbered tasks (chosen) | a repeated Activity ID in one project must be resolved | a task renumbered since the baseline reads as deleted plus new unless the option is on, as P6 does when the renumbering was not carried to the baseline |

## Decision

- **Identity.** An activity is keyed by `task_code` (Activity ID) in every frame and every
  comparison across files. `task_id` is used only inside one file, to resolve `TASKPRED`,
  `TASKRSRC` and `PROJCOST` rows to their task.
- **One row per Activity ID.** P6 does not write two activities of one project with one Activity
  ID; a merged or hand-made file can. `build_snapshot` keeps the first `TASK` row of each and
  leaves the others out, with their relationships, assignments and expenses, and one warning
  ("Activity ID repeated in the project ...").
- **Predecessors in another project of the file.** A predecessor that is a `TASK` row of another
  project of the same file is named `[ext]<task_id>` in `relationships.pred_code`
  (`is_external` True), as in `external_links` and `external_tasks`, never by its own Activity ID.
  A local activity literally named like a placeholder is kept and reported
  (`validate.placeholder_clashes`: "activity ID(s) [...] are also the placeholder names").
  Links whose other end has no `TASK` row in the file are dropped from `relationships`: those
  from another project (`is_external`) are counted in `external_links_dropped`; any other is
  treated as corrupt and reported in one warning ("relationship(s) to a task not in the file").
- **Series and exports.** `SnapshotStore.history` is one row per (`snapshot_idx`, `task_code`).
  The Power BI star schema (`export.export_tables`) relates on `snapshot_idx` and uses
  `task_code` to follow one activity across weeks and to join `fact_assignment` to
  `fact_activity`.
- **Renumbered tasks, by explicit choice.** `analysis/baseline.py::renumbered(old, new)` finds the
  tasks of an update that carry the GUID (`TASK.guid`) of a baseline task under another Activity
  ID, the old ID gone from the update and the new one absent from the baseline; blank GUIDs and
  GUIDs held by several tasks of a file are left out. The Files and baseline window's option
  "Link renumbered tasks by GUID" (session key `guid_link`, off by default) measures those tasks
  against the baseline task under their new ID (`baseline.relinked`), as P6 does when
  "Renumber Selected Activities in Baselines" was ticked. Off, they count as deleted and new, as
  P6 does otherwise.

## Consequences

- A series of exports from different P6 instances, or re-imported between weeks, joins on what
  the planner reads in P6.
- An external predecessor can never be mistaken for a local activity sharing its Activity ID;
  the CPM does not wait on the wrong task.
- The anonymiser keeps one code per activity across every download of the session
  (`docs/architecture.md`, `anonymize.py`), so the key survives anonymisation.
- A renumbered task loses its baseline unless the user turns the GUID option on; the sidebar
  names the updates that hold such tasks, and the Debug page lists the pairs.
- A file that repeats an Activity ID in one project loses the later rows, with a warning.

## Verification

- `tests/test_store.py::test_task_ids_change_but_codes_join`: every internal id changes across
  the demo series, the history still joins on `task_code`.
- `tests/test_cpm.py::test_predecessor_in_another_project_of_the_file_is_not_the_local_namesake`:
  `pred_code` is `[ext]1`, and the successor starts at the data date, not after the local
  namesake.
- `tests/test_audit_edges_xer.py::test_same_activity_id_in_two_projects_with_an_external_link_is_named_by_task_id`
  and `::test_local_activity_named_like_an_external_placeholder_is_warned_about`.
- `tests/test_audit_edges_cpm.py::test_duplicate_activity_id_first_row_wins` and
  `tests/test_audit_edges_xer.py::test_repeated_activity_id_keeps_the_first_row_with_a_warning`.
- `tests/test_renumbered.py`: `test_a_task_with_the_same_guid_under_a_new_activity_id_is_renumbered`,
  `test_blank_and_shared_guids_and_codes_still_present_are_left_out`,
  `test_linking_by_guid_counts_the_renumbered_task_as_p6_does_when_the_baseline_was_renumbered`,
  `test_linking_changes_nothing_without_renumbered_tasks`,
  `test_linking_renames_the_tasks_of_the_baseline_file_too_so_the_checks_counting_them_agree`.

## References

- `src/xerscope/xer/model.py`: module docstring ("Key decisions"), `_task_frame` (repeated
  Activity ID), `_relationships` (`[ext]` naming), `_external_links`
- `src/xerscope/xer/validate.py`: `placeholder_clashes`
- `src/xerscope/store.py`: `SnapshotStore.history`
- `src/xerscope/export.py`: module docstring (star schema keys), `export_tables`
- `src/xerscope/analysis/baseline.py`: `renumbered`, `relinked`
- `src/xerscope/app/baseline_window.py` (option "Link renumbered tasks by GUID")
- `docs/architecture.md` §2 table ("Identity", "Links" rows)
- `docs/user-guide.md` "Concepts" (How activities are matched between files)
- `CONTRIBUTING.md` "Units" paragraph
- Related: [ADR-0002](0002-format-parser-then-p6-model-with-load-contract.md),
  [ADR-0006](0006-weekly-series-store-one-snapshot-per-data-date.md),
  [ADR-0015](0015-anonymised-downloads-by-default.md),
  [ADR-0018](0018-baseline-read-per-page-with-kind-and-source.md),
  [ADR-0022](0022-power-bi-star-schema-export.md)
