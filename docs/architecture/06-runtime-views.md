# 6. Runtime view

Five scenarios, each drawn from the code path named in the diagram. Participant names are real
modules, classes and functions.

## 6.1 Loading a folder of `.xer` into `SnapshotStore` in the app

Path: `app/state.py` (`sidebar_loader`, `_window`, `_chosen_items`, `_build`, `_read`, `_parse`),
`xer/__init__.py` (`load_snapshot`), `xer/parser.py`, `xer/model.py`, `store.py`. Nothing is read
before the user presses Done in the Files and baseline window.

```mermaid
sequenceDiagram
    actor U as Planner
    participant W as state._window / _files_section
    participant L as state.sidebar_loader
    participant C as state._chosen_items
    participant B as state._build / _read
    participant P as state._parse (session cache)
    participant X as xer.load_snapshot
    participant M as model.build_snapshot
    participant S as SnapshotStore

    U->>W: Files line → window opens, type a folder path
    W->>W: _folder_boxes: list xer_files(folder), describe each with load_header
    U->>W: tick files, press Done
    W->>L: _apply_drafts → session_state.files_source = ("folder", path, names)
    L->>C: signature, items
    C->>C: _file_digest(path) per file (sha256, cached on inode/size/mtime/ctime)
    C-->>L: items = [(name, bytes)] only for files whose digest changed
    loop each file
        L->>B: _read(name, data)
        B->>P: _parse(name, data, project_id)
        alt key (name, sha256, project_id) cached
            P-->>B: Snapshot
        else
            P->>X: load_snapshot(bytes, name=name, project_id=)
            X->>X: parse_bytes → RawXer (strings only, XerError if no ERMHDR and no table)
            X->>M: build_snapshot(raw, project_id=)
            M->>M: pick project (_select_project), type columns, calendars, options, relationships
            M-->>X: Snapshot (warnings attached)
            X-->>P: Snapshot
        end
        B->>B: skip a file with data_date None (error listed in the sidebar)
    end
    B->>S: SnapshotStore(snapshots)
    S->>S: sort by (data_date, source), raise DuplicateDataDate if two share a date
    S-->>L: store
    L->>L: session_state.update(store, signature, errors, items)
    L->>L: _apply_file_choices (re-read a file for a project picked in the window)
    L-->>U: sidebar "Files · N files · K projects", errors, baseline picker
```

Notes: `_parse` clears its dictionary past 64 entries; the key includes `project_id`, so a file
read for another of its projects is a second entry. A `DuplicateDataDate` is shown as an error with
"Untick the others."; the store stays `None`.

## 6.2 `xerscope check FILE --standard P6`

Path: `cli.main` → `_cmd_check` → `_standard` → `SnapshotStore.from_paths` → `run_standard` →
`results_frame`; optional `--expect` through `compare_counts`.

```mermaid
sequenceDiagram
    actor U as CLI user
    participant CLI as cli.main / _cmd_check
    participant STD as analysis.standards
    participant ST as SnapshotStore.from_paths
    participant BL as analysis.baseline
    participant RS as checks.run_standard
    participant RM as checks.run_metric
    participant R as RULES[metric.rule].fn
    participant RF as checks.results_frame

    U->>CLI: xerscope check FILE.xer --standard P6 [--baseline BL.xer] [--expect p6.csv] [--fail-on fail]
    CLI->>STD: _standard("P6") → builtin_standards()["P6"] (or load_standard(path))
    STD-->>CLI: Standard(metrics)
    CLI->>ST: from_paths(_expand(paths), project)
    ST-->>CLI: store (one series, so DECM checks against the previous update can run)
    opt --baseline
        CLI->>BL: Baseline.from_snapshot(load_snapshot(BL.xer))
    end
    loop each snapshot of the store
        opt --baseline-in-file
            CLI->>BL: baseline_in_file(snapshot, file bytes)
        end
        CLI->>RS: run_standard(standard, AnalysisContext(snapshot, store, baseline))
        loop each metric
            RS->>RM: run_metric(metric, context)
            RM->>R: fn(context, **metric.params)
            R-->>RM: RuleOutput (or exception → status "error")
            RM-->>RS: CheckResult (status from metric.evaluate)
        end
        RS-->>CLI: list of CheckResult
        CLI->>RF: results_frame(results) + file, data_date columns
        CLI-->>U: print id, check, target, actual, found, total, status
        opt --flagged DIR
            CLI->>CLI: one CSV per (file, metric) of result.flagged
        end
    end
    opt --out
        CLI->>CLI: write concatenated results CSV
    end
    opt --expect CSV
        CLI->>CLI: _expect_differs → compare_counts(results, expected, keys)
        CLI-->>U: expected vs got, exit 1 on a difference
    end
    CLI-->>U: exit 1 if any status in FAIL_ON[--fail-on], else 0
```

## 6.3 One rule: populations → rule → metric → explain

Example: metric `P6-01` (`rule = "p6_01_logic"`, `target = "< 5%"`). In the app the entry point is
`state.metric_result`, which wraps `run_metric` in `memo`; in the CLI it is `run_standard`.

```mermaid
sequenceDiagram
    participant MR as state.metric_result (app) or checks.run_standard (CLI)
    participant RM as checks.run_metric
    participant RULE as p6.check_schedule.p6_01_logic
    participant F as populations.Funnel
    participant POP as populations helpers
    participant MET as standards.Metric
    participant EX as explain.explain
    participant AU as audit.split

    MR->>RM: run_metric(metric, AnalysisContext(snapshot, store, baseline))
    RM->>RM: uses_baseline? needs_baseline and no baseline → CheckResult "n/a"
    RM->>RULE: RULES["p6_01_logic"].fn(context)
    RULE->>F: activity_funnel(snapshot) → Funnel(snapshot.activities, data_date)
    RULE->>F: .exclude("complete", "101248")
    F->>F: Step("not complete", "101248", removed rows, left)
    RULE->>POP: has_predecessor_in_project, has_successor_in_project, open_end_reason
    RULE-->>RM: RuleOutput(flagged, numerator=len(flagged), denominator=len(rows), checked, funnel)
    RM->>RM: value = 100 * numerator / denominator (unit "%")
    RM->>MET: metric.evaluate(value) → "pass" | "fail" | "info" | "n/a"
    RM-->>MR: CheckResult(metric, status, value, numerator, denominator, flagged, note, checked, counted, funnel, ...)
    MR->>EX: explain(result)
    EX->>EX: Rule.params merged with metric.params → (name, value, "standard" | "default")
    EX->>EX: population = docstring lines + sentences from parameters (NOTES)
    EX-->>MR: Explanation(measured, formula, verdict, method, population, parameters, flagged_label, subject, baseline)
    MR->>AU: split(result, snapshot) → AuditSets(counted, checked, excluded)
    AU-->>MR: the three sets, nothing recomputed
```

A rule that raises gives `CheckResult(status="error", note="<ExceptionName>: <text>")`; the other
metrics still run (`checks.py` docstring). A rule whose denominator is 0 gives `"n/a"` with the
note "nothing to check" unless the rule set its own.

## 6.4 CPM recalculation and the INT-01 comparison

Path: `integrity.int_01_recalculated` → `cpm.compare_with_stored` → `cpm.schedule` → `_Run`.
The plain recalculation is cached on the snapshot object (`_xs_schedule`, `_xs_comparison`).

```mermaid
sequenceDiagram
    participant INT as integrity.int_01_recalculated
    participant CWS as cpm.compare_with_stored
    participant SCH as cpm.schedule
    participant RUN as cpm._Run
    participant AX as _Axes / TimeAxis
    participant CMP as cpm._comparison

    INT->>CWS: compare_with_stored(context.snapshot)
    CWS->>SCH: schedule(snapshot)
    alt snapshot._xs_schedule cached
        SCH-->>CWS: Schedule
    else first run
        SCH->>RUN: _Run(snapshot, {}, Options.from_snapshot(snapshot))
        RUN->>RUN: _network (topological order, CycleError on a loop, Tarjan members)
        RUN->>AX: one TimeAxis per calendar over _date_range(snapshot)
        RUN->>RUN: forward() — early dates, constraints, expected finish, rsrc_early
        RUN->>RUN: backward() — late dates from must-finish-by or latest early finish
        RUN->>RUN: floats() — total (FLOAT_TYPE) and free float in working hours
        RUN->>RUN: level_of_effort() — LOE from their links' dates
        RUN->>RUN: longest_path()
        RUN->>RUN: _report() — warnings: multiple float paths, external dates, constrained in-progress
        RUN-->>SCH: Schedule(frame of es, ef, ls, lf, tf_hr, ff_hr, rem_override_hr, finish, warnings, assignments)
        SCH->>SCH: object.__setattr__(snapshot, "_xs_schedule", result)
    end
    CWS->>CMP: _comparison(snapshot, schedule) (cached as _xs_comparison, copy returned)
    CMP-->>CWS: one row per (open activity, field): stored, computed, agree, gap_hr
    CWS-->>INT: comparison frame
    INT->>INT: keep STORED_FIELDS with a stored value, Funnel "with stored dates to compare"
    INT->>INT: differences per task_code → flagged_activities(..., differences=texts)
    INT-->>INT: RuleOutput(flagged, numerator = tasks differing, denominator = tasks compared, note, funnel)
```

A `CycleError` in `schedule` is caught by INT-01 and returned as `RuleOutput(note="cannot schedule: …")`;
INT-04 reports the loop members. `critical_path_test` (DCMA-12, DECM 06A401a) runs `schedule`
again with `extra_hours` on the first open critical task and `base` = the plain schedule.

## 6.5 Power BI export

Path (app): `views/export.py` → `state.memo` → `export.export_tables` → `export.zip_tables`, through
`Anonymizer.frame` when "Anonymous exports" is on. Path (CLI): `_cmd_export` → `export.write_tables`.

```mermaid
sequenceDiagram
    actor U as Planner
    participant V as views/export.py
    participant MEMO as state.memo
    participant EXP as export.export_tables
    participant ST as SnapshotStore
    participant AN as Anonymizer.frame
    participant Z as export.zip_tables / zip_frames

    U->>V: open "Export for Power BI"
    V->>MEMO: memo(("export",), export_tables, store, baseline=False)
    MEMO->>EXP: export_tables(store)
    EXP->>ST: store.summary, store.history, store.relationship_history, store.assignment_history
    ST->>ST: _stack(attribute, columns): snapshot_idx, data_date, then HISTORY_COLS / REL_COLS / ASSIGNMENT_COLS
    ST-->>EXP: four frames
    EXP-->>V: {dim_snapshot, fact_activity, fact_relationship, fact_assignment}
    V-->>U: table of rows and columns, preview of fact_activity
    U->>V: choose parquet or csv, press Download
    alt Anonymous exports on (default)
        V->>MEMO: memo(("export_anonymised", fmt), zip_tables, store, fmt, anonymous.frame)
        MEMO->>Z: zip_tables(store, fmt, transform=Anonymizer.frame)
        Z->>AN: frame(df) per table (codes renamed, names rebuilt, costs 0, leak check)
        Z-->>V: zip bytes, file name xerscope_<fmt>.zip (no project code)
    else switch off
        V->>Z: zip_tables(store, fmt)
        Z-->>V: zip bytes, file name <project_code>_xerscope_<fmt>.zip
    end
    V-->>U: download
```

The CLI path (`xerscope export FOLDER --out DIR --format parquet|csv`) writes one file per table with
`write_tables` and prints the paths; it does not anonymise (not determined from code whether that is
intended or an omission: the CLI has no `--anonymous` flag).
