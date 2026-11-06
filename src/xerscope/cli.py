"""Command line: ``xerscope {app,info,check,recalc,standards,changelog,export,crosscheck,sample}``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from xerscope.config import DATE_FMT, DATETIME_FMT
from xerscope.store import DuplicateDataDate
from xerscope.xer import XerError, xer_files

APP_PATH = Path(__file__).parent / "app" / "streamlit_app.py"
# --fail-on: the statuses that make `check` exit 1 (a CI job or script stops on a schedule that misses the standard)
FAIL_ON = {"none": set(), "fail": {"fail", "error"}, "error": {"error"}}

# Exit codes: 0 done, 1 a finding (--fail-on, --expect), 2 the input could not be used. A script
# can then tell a schedule that misses the standard from a file that could not be read.
INPUT_ERROR = 2


def fail(message: str) -> NoReturn:
    """Stop on input that cannot be used: one line on stderr, exit code 2, no traceback."""
    print(f"xerscope: {message}", file=sys.stderr)
    raise SystemExit(INPUT_ERROR)


def _expand(paths: list[str]) -> list[Path]:
    """Files as given; folders -> their *.xer, sorted. Nothing to read is an error (exit 2)."""
    found: list[Path] = []
    for path in (Path(raw_path).expanduser() for raw_path in paths):
        if path.is_dir():
            found += xer_files(path)
        elif path.is_file():
            found.append(path)
        else:
            fail(f"{path}: no such file or folder")
    if not found:
        fail(f"no .xer file in {', '.join(paths)}")
    return found


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="+")


def _add_project(parser: argparse.ArgumentParser, help_text: str | None = None) -> None:
    parser.add_argument("--project", help=help_text)


def _add_out(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--out", help=help_text)


def _write_csv(frame, path, *, index: bool = False) -> None:
    frame.to_csv(path, index=index, encoding="utf-8-sig")  # the BOM makes Excel read UTF-8


def _cmd_app(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    for flag, var in (
        ("data", "XERSCOPE_DATA"),
        ("baseline", "XERSCOPE_BASELINE"),
        ("standards", "XERSCOPE_STANDARDS"),
    ):
        if getattr(args, flag):
            env[var] = str(Path(getattr(args, flag)).expanduser().resolve())
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
        "--browser.gatherUsageStats",
        "false",
    ]
    # Streamlit reads .streamlit/config.toml from the working directory: run from the app
    # folder so the packaged theme and server settings apply wherever xerscope is started.
    return subprocess.call(cmd, env=env, cwd=APP_PATH.parent)


def _args_app(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", help="folder of weekly .xer files to preload")
    parser.add_argument("--baseline", help="baseline .xer, or a P6 XML export holding the baseline")
    parser.add_argument("--standards", help="folder of your own standard .toml files")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument(
        "--host",
        default="localhost",
        help="interface to listen on; default localhost. 0.0.0.0 exposes your schedules to the network",
    )


def _when(timestamp, fmt: str = DATE_FMT) -> str:
    """A date for printing; files without a data date or a finish exist."""
    import pandas as pd  # the CLI imports pandas lazily, so `xerscope app` starts fast

    return "-" if timestamp is None or pd.isna(timestamp) else f"{timestamp:{fmt}}"


def _args_info(parser: argparse.ArgumentParser) -> None:
    _add_paths(parser)
    _add_project(parser, "project short name, if files hold several")


def _cmd_info(args: argparse.Namespace) -> int:
    from .store import SnapshotStore

    store = SnapshotStore.from_paths(_expand(args.paths), project_code=args.project)
    columns = [
        "data_date",
        "source",
        "forecast_finish",
        "finish_shift_wd",
        "activities",
        "complete",
        "critical",
        "relationships",
    ]
    print(store.summary[columns].round({"finish_shift_wd": 1}).to_string(index=False))
    for warning in store.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _standard(spec: str):
    from .analysis import builtin_standards, load_standard

    found = builtin_standards()
    if spec.upper() in found:
        return found[spec.upper()]
    if Path(spec).is_file():
        return load_standard(spec)
    fail(f"unknown standard {spec!r}: use {', '.join(found)} or a .toml file")


def _args_check(parser: argparse.ArgumentParser) -> None:
    _add_paths(parser)
    parser.add_argument("--standard", default="P6", help="P6, DCMA or path to your .toml")
    parser.add_argument("--baseline", help="baseline .xer (or P6 XML) for BEI / missed / late checks")
    parser.add_argument(
        "--planned-baseline", action="store_true", help="no baseline file: use each file's planned dates (target_*)"
    )
    parser.add_argument(
        "--baseline-in-file",
        action="store_true",
        help="use the P6 Project Baseline each file holds (sum_base_proj_id), as Check Schedule does; "
        "a file without a usable one falls back on --baseline / --planned-baseline, else none",
    )
    _add_project(parser)
    _add_out(parser, "write all results to this CSV")
    parser.add_argument(
        "--flagged", metavar="DIR", help="write the items found by each check, one CSV per file and check"
    )
    parser.add_argument(
        "--expect",
        metavar="CSV",
        help="counts typed from P6's Check Schedule summary (id,found,total[,file]); exit 1 on a difference",
    )
    parser.add_argument(
        "--fail-on",
        choices=list(FAIL_ON),
        default="none",
        help="exit 1 when a check fails (fail) or cannot run (error); default: always 0",
    )


def _cmd_check(args: argparse.Namespace) -> int:
    import pandas as pd

    from .analysis import AnalysisContext, Baseline, results_frame, run_standard
    from .analysis.baseline import baseline_in_file
    from .store import SnapshotStore
    from .xer import load_snapshot

    standard = _standard(args.standard)
    baseline = Baseline.from_snapshot(load_snapshot(args.baseline)) if args.baseline else None
    frames = []
    files = _expand(args.paths)
    by_name = {path.name: path for path in files}  # Snapshot.source is the file name
    if args.baseline_in_file and len(by_name) < len(files):
        fail("--baseline-in-file needs distinct file names")
    # one series, so checks against the previous update (DECM 06A504, 06A506c) can run
    store = SnapshotStore.from_paths(files, args.project)
    for snapshot in store:
        path = Path(snapshot.source)
        in_file = baseline_in_file(snapshot, by_name[snapshot.source].read_bytes()) if args.baseline_in_file else None
        applied_baseline = in_file or baseline or (Baseline.planned(snapshot) if args.planned_baseline else None)
        results = run_standard(standard, AnalysisContext(snapshot, store, baseline=applied_baseline))
        frame = results_frame(results)
        frame.insert(0, "file", path.name)
        frame.insert(1, "data_date", snapshot.data_date)
        frames.append(frame)
        if args.flagged:  # the items behind each count, to diff against P6's own lists
            out_dir = Path(args.flagged)
            out_dir.mkdir(parents=True, exist_ok=True)
            for result in results:
                if not result.flagged.empty:
                    _write_csv(result.flagged, out_dir / f"{path.stem}_{result.metric.id}.csv")
        print(
            f"\n{standard.name} · {path.name} · data date {_when(snapshot.data_date)}"
            f" · baseline {applied_baseline.label if applied_baseline else 'none'}"
        )
        columns = ["id", "check", "target", "actual", "found", "total", "status"]
        print(frame[columns].to_string(index=False, float_format="{:.2f}".format))
    results = pd.concat(frames)
    if args.out:
        _write_csv(results, args.out)
        print(f"\nwritten {args.out}")
    if args.expect and _expect_differs(results, args.expect):
        return 1
    bad = FAIL_ON[args.fail_on]
    hits = results[results["status"].isin(bad)]
    if len(hits):
        print(f"\n{len(hits)} result(s) with status {'/'.join(sorted(bad))}", file=sys.stderr)
        return 1
    return 0


def _expect_differs(results, expect_csv: str) -> bool:
    """Compare found / total with the counts typed from a P6 Check Schedule summary.

    The CSV has columns id, found, total, and file when several files were checked (the
    file name without its folder). Prints every expected line as expected / got."""
    import pandas as pd

    from .analysis import compare_counts

    expected = pd.read_csv(expect_csv, dtype={"id": str, "file": str}).rename(columns=str.strip)
    missing = {"id", "found", "total"} - set(expected.columns)
    if missing:
        fail(f"{expect_csv}: columns {', '.join(sorted(missing))} missing")
    keys = ["file", "id"] if "file" in expected.columns else ["id"]
    if "file" not in expected.columns and results["file"].nunique() > 1:
        fail(f"{expect_csv}: add a 'file' column, {results['file'].nunique()} files were checked")
    merged = compare_counts(results, expected, keys)
    print(f"\nExpected (from {expect_csv}) vs xerscope:")
    print(merged.to_string(index=False))
    bad = int((~merged["match"]).sum())
    print(f"\n{bad} difference(s)" if bad else "\nall counts match", file=sys.stderr if bad else sys.stdout)
    return bad > 0


def _args_standards(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rules", action="store_true", help="list rules and their parameters")
    parser.add_argument(
        "--template",
        nargs="?",
        const="-",
        metavar="FILE",
        help="write a standard template to FILE (UTF-8), or print it",
    )


def _cmd_standards(args: argparse.Namespace) -> int:
    from .analysis import RULES, builtin_standards, template_text

    if args.template:
        if args.template == "-":
            print(template_text(), end="")
        else:
            Path(args.template).write_text(template_text(), encoding="utf-8")
            print(f"written {args.template}")
        return 0
    if args.rules:
        for rule in RULES.values():
            params = ", ".join(f"{name}={value!r}" for name, value in rule.params.items())
            print(f"{rule.name}  [{rule.unit}{', needs baseline' if rule.needs_baseline else ''}]\n  ({params})")
            print("  " + rule.doc.replace("\n", "\n  ") + "\n")
        return 0
    for standard in builtin_standards().values():
        print(f"{standard.id:6} {standard.name} ({len(standard.metrics)} metrics)")
        for metric in standard.metrics:
            print(f"   {metric.id:8} {metric.name:42} {metric.threshold_label:10} rule={metric.rule}")
    print("\nYour own: xerscope standards --template my.toml, then --standard my.toml")
    return 0


def _args_recalc(parser: argparse.ArgumentParser) -> None:
    _add_paths(parser)
    _add_project(parser)
    _add_out(parser, "write the recalculated dates and float to this CSV")
    parser.add_argument("--report", action="store_true", help="group the differences by activity shape")
    parser.add_argument("--show", type=int, default=20, help="differences to print")


def _cmd_recalc(args: argparse.Namespace) -> int:
    from .analysis.cpm import compare_assignments, compare_with_stored, schedule
    from .xer import load_snapshot

    for path in _expand(args.paths):
        snapshot = load_snapshot(path, args.project)
        recalculated = schedule(snapshot)
        comparison = compare_with_stored(snapshot, recalculated)
        stored = comparison[comparison["stored"].notna()]
        print(
            f"\n{path.name} · {len(snapshot.activities)} activities"
            f" · data date {_when(snapshot.data_date, DATETIME_FMT)}"
            f" · recalculated finish {_when(recalculated.finish, DATETIME_FMT)}"
        )
        if stored.empty:
            print("  no stored dates to compare (never scheduled in P6?)")
        else:
            agg = stored.groupby("field")["agree"].agg(["sum", "count"])
            for field, row in agg.iterrows():
                print(f"  {field:20} {int(row['sum']):>7} / {int(row['count']):<7} identical")
            wrong = stored[~stored["agree"]]
            if len(wrong):
                print(wrong.head(args.show).to_string(index=False))
            if args.report and len(wrong):
                from .verify.shapes import difference_report

                report = difference_report(snapshot, comparison)
                report["share"] = report["share"].map("{:.0%}".format)
                print("\n  differences by activity shape (status · type · constraint · links · option):")
                print(report.to_string(index=False))
        assignment_comparison = compare_assignments(snapshot, recalculated)
        assignment_comparison = assignment_comparison[assignment_comparison["stored"].notna()]
        if len(assignment_comparison):
            print(
                f"  assignments ({assignment_comparison['taskrsrc_id'].nunique()}): "
                f"{int(assignment_comparison['agree'].sum())} / {len(assignment_comparison)} stored dates identical"
            )
            assignment_wrong = assignment_comparison[~assignment_comparison["agree"]]
            if len(assignment_wrong):
                print(assignment_wrong.head(args.show).to_string(index=False))
        for warning in recalculated.warnings + [warning for warning in snapshot.warnings if "leveling" in warning]:
            print(f"  warning: {warning}")
        if args.out:
            out = recalculated.frame.join(snapshot.activities.set_index("task_code")[["task_name"]])
            dest = (
                Path(args.out)
                if len(args.paths) == 1
                else Path(args.out).with_name(f"{path.stem}_{Path(args.out).name}")
            )
            _write_csv(out, dest, index=True)
            print(f"  written {dest}")
    return 0


def _args_changelog(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("old")
    parser.add_argument("new")
    _add_project(parser)
    _add_out(parser, "write the full changelog to this CSV")


def _cmd_changelog(args: argparse.Namespace) -> int:
    from .analysis.changelog import changelog, summary
    from .xer import load_snapshot

    old, new = load_snapshot(args.old, args.project), load_snapshot(args.new, args.project)
    log = changelog(old, new)
    print(summary(log).to_string(index=False))
    if args.out:
        _write_csv(log, args.out)
        print(f"\nwritten {args.out} ({len(log)} changes)")
    return 0


def _args_export(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("folder")
    parser.add_argument("--out", default="export")
    parser.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    _add_project(parser)


def _cmd_export(args: argparse.Namespace) -> int:
    from .export import write_tables
    from .store import SnapshotStore

    store = SnapshotStore.from_folder(args.folder, project_code=args.project)
    for written_path in write_tables(store, args.out, args.format):
        print(written_path)
    return 0


def _args_pv_compare(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", help="the update .xer")
    parser.add_argument("--baseline", help="baseline .xer or P6 XML (else --planned-baseline)")
    parser.add_argument("--planned-baseline", action="store_true", help="use the update's planned dates (target_*)")
    parser.add_argument("--p6", required=True, metavar="CSV", help="P6 Activities view saved as CSV")
    parser.add_argument(
        "--column",
        action="append",
        default=[],
        metavar="FIELD=HEADER",
        help="a column the export names otherwise, e.g. pv_hr='PV Labor Units' (fields: "
        "task_code pv_hr ev_hr schedule_pct bl_hr status bl_start bl_finish start finish)",
    )
    parser.add_argument("--tolerance", type=float, default=None, metavar="H", help="gap under which an activity agrees")
    parser.add_argument("--p6-total", type=float, default=None, metavar="H", help="PV labor units total shown by P6")
    _add_project(parser)
    _add_out(parser, "write the five tables to this folder (default pv_compare)")


def _cmd_pv_compare(args: argparse.Namespace) -> int:
    """Block 10 of the diagnostic from the disk: PV and EV labour units of the update against a P6
    Activities export, nothing kept. Four tables without code or name, and the activities in gap."""
    from .analysis import Baseline
    from .app import diagnostic
    from .xer import load_snapshot

    snapshot = load_snapshot(args.path, args.project)
    if args.baseline:
        baseline = Baseline.from_snapshot(load_snapshot(args.baseline))
    elif args.planned_baseline:
        baseline = Baseline.planned(snapshot)
    else:
        fail("pv-compare: give --baseline BL.xer or --planned-baseline")
    if snapshot.data_date is None:
        fail(f"{args.path}: no data date")
    try:
        raw = diagnostic.read_p6_export(args.p6, Path(args.p6).read_bytes())
    except ValueError as exc:
        fail(f"{args.p6}: {exc}")
    chosen = {}
    for item in args.column:
        field, _, header = item.partition("=")
        if field not in diagnostic.P6_EXPORT_FIELDS or not header:
            fail(f"--column {item!r}: expected FIELD=HEADER with FIELD among {' '.join(diagnostic.P6_EXPORT_FIELDS)}")
        chosen[field] = header
    columns = diagnostic.p6_export_columns(raw, chosen)
    missing = [
        field for field, (_, required) in diagnostic.P6_EXPORT_FIELDS.items() if required and columns[field] is None
    ]
    if missing:
        fail(
            f"{args.p6}: column(s) not found for {', '.join(missing)}; headers read: {', '.join(raw.columns)}. "
            "Name them with --column FIELD=HEADER."
        )
    tolerance = diagnostic.PV_P6_TOLERANCE_HR if args.tolerance is None else args.tolerance
    comparison, notes = diagnostic.compare_p6_export(snapshot, baseline, raw, columns, tolerance, args.p6_total)
    out = Path(args.out or "pv_compare")
    out.mkdir(parents=True, exist_ok=True)
    frames = {**diagnostic.pv_p6_frames(comparison), "10_pv_p6_activities_in_gap": comparison.activities}
    for name, frame in frames.items():
        _write_csv(frame, out / f"{name}.csv")
    set_aside = ", ".join(f"{count} {what.replace('_', ' ')}" for what, count in notes.items() if count)
    print(f"{args.path} at {_when(snapshot.data_date)} against {args.p6} (tolerance {tolerance:g} h)")
    if set_aside:
        print(f"set aside: {set_aside}")
    print(comparison.totals.to_string(index=False))
    print(f"\n{len(comparison.activities)} activities in gap; tables written to {out}/")
    return 0


def _args_crosscheck(parser: argparse.ArgumentParser) -> None:
    _add_paths(parser)
    _add_out(parser, "write every comparison to this CSV")
    parser.add_argument(
        "--cpm",
        action="store_true",
        help="compare the recalculation with MPXJ's scheduler (build it: tests/reference/mpxj_cpm.py)",
    )
    parser.add_argument(
        "--p6",
        action="store_true",
        help="paths are held-out set folders (tests/reference/data/p6-heldout/validation/held-out/H1 ...): "
        "compare the recalculation with what P6 23.12 scheduled",
    )
    parser.add_argument("--show", type=int, default=20, help="differences to print")


def _cmd_crosscheck(args: argparse.Namespace) -> int:
    if args.p6:
        return _cmd_crosscheck_p6(args)
    if args.cpm:
        return _cmd_crosscheck_cpm(args)
    from .crosscheck import compare_paths

    checks = compare_paths(_expand(args.paths))
    if args.out:
        _write_csv(checks, args.out)
    summary = checks.groupby("file")["agree"].agg(agree="sum", checks="count")
    print(summary.to_string())
    wrong = checks[~checks["agree"]]
    print(f"\n{len(wrong)} disagreement(s) out of {len(checks)} checks")
    if len(wrong):
        print(wrong.groupby("field").size().to_string())
        print(wrong.head(30).to_string(index=False))
    return 1 if len(wrong) else 0


def _cmd_crosscheck_p6(args: argparse.Namespace) -> int:
    """The CPM against P6 23.12's own results on the held-out corpus (set folders as paths)."""
    import pandas as pd

    from .crosscheck import p6_heldout_score

    frames = [p6_heldout_score(Path(folder).expanduser()) for folder in args.paths]
    scores = pd.concat(frames, ignore_index=True)
    errors = scores[scores["field"] == "error"]
    scores = scores[scores["field"] != "error"]
    for name, group in scores.groupby("set"):
        by_field = group.groupby("field")["agree"].mean().mul(100).round(1)
        dependent = group[group["resource_dependent"]]
        print(
            f"{name}: {group['agree'].mean():.1%} of {len(group)} values identical to P6"
            + (
                f" ({dependent['agree'].mean():.1%} on {dependent['task_code'].nunique()} resource-dependent"
                " activities)"
                if len(dependent)
                else ""
            )
        )
        print("   " + "  ".join(f"{field} {agreement}%" for field, agreement in by_field.items()))
    for error in errors.itertuples():
        print(f"  {error.set} {error.case}: cannot schedule: {error.xerscope}")
    if args.out:
        _write_csv(scores, args.out)
    wrong = scores[~scores["agree"]]
    if len(wrong) and args.show:
        print(
            wrong[["set", "case", "task_code", "status", "field", "p6", "xerscope"]]
            .head(args.show)
            .to_string(index=False)
        )
    return 0 if wrong.empty else 1


def _cmd_crosscheck_cpm(args: argparse.Namespace) -> int:
    """xerscope's CPM against MPXJ's PrimaveraScheduler, and both against what P6 stored."""
    import pandas as pd

    from .crosscheck import (
        P6_SETTLED,
        UNRESOLVED,
        cpm_crosscheck,
        excused_row,
        mpxj_inconsistent,
        mpxj_scheduler_source,
        mpxj_unsupported,
        settled_patterns,
        unresolved_patterns,
    )
    from .xer import load_snapshot

    source = mpxj_scheduler_source()
    print(f"MPXJ scheduler: {source}")
    if "mpxj-cpm-" not in source:
        print(
            "warning: MPXJ's released scheduler predates its out-of-sequence fix (#972); build the pinned one "
            "(tests/reference/mpxj_cpm.py) and set XERSCOPE_MPXJ_CPM_JAR to its path",
            file=sys.stderr,
        )
    frames, unexplained = [], 0
    for path in _expand(args.paths):
        snapshot = load_snapshot(path)
        comparison = cpm_crosscheck(path).assign(file=path.name)
        frames.append(comparison)
        ok = comparison[comparison["comparable"]]
        print(f"\n{path.name} · {ok['task_code'].nunique()} open activities")
        agreement = ok.groupby("field")[["xs_mpxj_work", "xs_p6", "mpxj_p6"]].mean().mul(100).round(2)
        agreement.columns = ["xerscope = MPXJ %", "xerscope = stored %", "MPXJ = stored %"]
        print(agreement.to_string())
        for option in mpxj_unsupported(snapshot):
            print(f"  option MPXJ does not model: {option}")
        for pattern in sorted(settled_patterns(snapshot)):
            print(f"  MPXJ differs from P6 here: {P6_SETTLED[pattern]}")
        for pattern in sorted(unresolved_patterns(snapshot)):
            print(f"  open question present: {UNRESOLVED[pattern]}")
        broken = mpxj_inconsistent(snapshot, comparison)
        if broken:
            print(f"  MPXJ contradicts itself on: {', '.join(sorted(broken)[:8])}")
        wrong = ok[~ok["xs_mpxj_work"]]
        wrong = wrong[
            [
                excused_row(snapshot, task_code, field) is None
                for task_code, field in zip(wrong["task_code"], wrong["field"], strict=True)
            ]
        ]
        explained = unresolved_patterns(snapshot) or settled_patterns(snapshot) or broken or mpxj_unsupported(snapshot)
        if len(wrong) and not explained:
            unexplained += len(wrong)
            print(wrong[["task_code", "field", "p6", "xerscope", "mpxj"]].head(args.show).to_string(index=False))
    if args.out:
        _write_csv(pd.concat(frames), args.out)
    print(f"\n{unexplained} difference(s) no listed cause explains")
    return 1 if unexplained else 0


def _args_sample(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", default="data/sample")
    parser.add_argument("--weeks", type=int, default=8)


def _cmd_sample(args: argparse.Namespace) -> int:
    from .sample import generate

    for sample_path in generate(args.out, weeks=args.weeks):
        print(sample_path)
    return 0


# name: (help, adds its arguments, runs); the order is the order of `xerscope --help`
COMMANDS = {
    "app": ("launch the web app", _args_app, _cmd_app),
    "info": ("summarise one or more XER files / folders", _args_info, _cmd_info),
    "check": ("run a standard (P6, DCMA or a .toml) on XER files", _args_check, _cmd_check),
    "standards": ("list standards and rules, or print the template", _args_standards, _cmd_standards),
    "recalc": ("reschedule like P6 and compare with the dates stored in the file", _args_recalc, _cmd_recalc),
    "changelog": ("what changed between two XER files", _args_changelog, _cmd_changelog),
    "export": ("write BI tables (Power BI star schema)", _args_export, _cmd_export),
    "crosscheck": ("compare xerscope with MPXJ on XER files (needs Java)", _args_crosscheck, _cmd_crosscheck),
    "pv-compare": ("PV and EV labour units against a P6 Activities export (CSV)", _args_pv_compare, _cmd_pv_compare),
    "sample": ("generate demo weekly XER files", _args_sample, _cmd_sample),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xerscope", description="Weekly P6 XER analysis")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    for name, (help_text, add_arguments, run) in COMMANDS.items():
        command_parser = subparsers.add_parser(name, help=help_text)
        add_arguments(command_parser)
        command_parser.set_defaults(fn=run)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (XerError, DuplicateDataDate, OSError) as exc:
        fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
