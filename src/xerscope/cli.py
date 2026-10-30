"""Command line: ``xerscope {app,info,check,recalc,standards,changelog,export,crosscheck,sample}``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from xerscope.xer import xer_files

APP_PATH = Path(__file__).parent / "app" / "streamlit_app.py"


def _expand(paths: list[str]) -> list[Path]:
    """Files as given; folders -> their *.xer, sorted. Nothing to read is an error (exit 2)."""
    out: list[Path] = []
    for p in (Path(x).expanduser() for x in paths):
        if p.is_dir():
            out += xer_files(p)
        elif p.is_file():
            out.append(p)
        else:
            raise SystemExit(f"xerscope: {p}: no such file or folder")
    if not out:
        raise SystemExit(f"xerscope: no .xer file in {', '.join(paths)}")
    return out


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


def _when(ts, fmt: str = "%Y-%m-%d") -> str:
    """A date for printing; files without a data date or a finish exist."""
    import pandas as pd  # the CLI imports pandas lazily, so `xerscope app` starts fast

    return "-" if ts is None or pd.isna(ts) else f"{ts:{fmt}}"


def _cmd_info(args: argparse.Namespace) -> int:
    from .store import SnapshotStore

    store = SnapshotStore.from_paths(_expand(args.paths), project_code=args.project)
    cols = [
        "data_date",
        "source",
        "forecast_finish",
        "finish_shift_wd",
        "activities",
        "complete",
        "critical",
        "relationships",
    ]
    print(store.summary[cols].to_string(index=False))
    for w in store.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


def _standard(spec: str):
    from .analysis import builtin_standards, load_standard

    found = builtin_standards()
    if spec.upper() in found:
        return found[spec.upper()]
    if Path(spec).is_file():
        return load_standard(spec)
    raise SystemExit(f"unknown standard {spec!r}: use {', '.join(found)} or a .toml file")


def _cmd_check(args: argparse.Namespace) -> int:
    import pandas as pd

    from .analysis import AnalysisContext, Baseline, results_frame, run_standard
    from .store import SnapshotStore
    from .xer import load_snapshot

    std = _standard(args.standard)
    bl = Baseline.from_snapshot(load_snapshot(args.baseline)) if args.baseline else None
    frames = []
    # one series, so checks against the previous update (DECM 06A504, 06A506c) can run
    store = SnapshotStore(load_snapshot(p, args.project) for p in _expand(args.paths))
    for snap in store:
        path = Path(snap.source)
        base = bl or (Baseline.planned(snap) if args.planned_baseline else None)
        results = run_standard(std, AnalysisContext(snap, store, baseline=base))
        df = results_frame(results)
        df.insert(0, "file", path.name)
        df.insert(1, "data_date", snap.data_date)
        frames.append(df)
        if args.flagged:  # the items behind each count, to diff against P6's own lists
            out_dir = Path(args.flagged)
            out_dir.mkdir(parents=True, exist_ok=True)
            for r in results:
                if not r.flagged.empty:
                    r.flagged.to_csv(out_dir / f"{path.stem}_{r.metric.id}.csv", index=False, encoding="utf-8-sig")
        print(
            f"\n{std.name} · {path.name} · data date {_when(snap.data_date)}"
            f" · baseline {base.label if base else 'none'}"
        )
        cols = ["id", "check", "target", "actual", "found", "total", "status"]
        print(df[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    results = pd.concat(frames)
    if args.out:
        results.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\nwritten {args.out}")
    if args.expect and _expect_differs(results, args.expect):
        return 1
    # --fail-on: let a CI job or a script stop on a schedule that misses the standard
    bad = {"fail": {"fail", "error"}, "error": {"error"}, "none": set()}[args.fail_on]
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

    exp = pd.read_csv(expect_csv, dtype={"id": str, "file": str}).rename(columns=str.strip)
    missing = {"id", "found", "total"} - set(exp.columns)
    if missing:
        sys.exit(f"{expect_csv}: columns {', '.join(sorted(missing))} missing")
    keys = ["file", "id"] if "file" in exp.columns else ["id"]
    if "file" not in exp.columns and results["file"].nunique() > 1:
        sys.exit(f"{expect_csv}: add a 'file' column, {results['file'].nunique()} files were checked")
    got = results[keys + ["check", "found", "total"]]
    m = exp.merge(got, on=keys, how="left", suffixes=("_exp", ""))
    m["match"] = (m["found_exp"] == m["found"]) & (m["total_exp"] == m["total"])
    cols = keys + ["check", "found_exp", "found", "total_exp", "total", "match"]
    print(f"\nExpected (from {expect_csv}) vs xerscope:")
    print(m[cols].to_string(index=False))
    bad = int((~m["match"].fillna(False)).sum())
    print(f"\n{bad} difference(s)" if bad else "\nall counts match", file=sys.stderr if bad else sys.stdout)
    return bad > 0


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
        for r in RULES.values():
            params = ", ".join(f"{k}={v!r}" for k, v in r.params.items())
            print(f"{r.name}  [{r.unit}{', needs baseline' if r.needs_baseline else ''}]\n  ({params})")
            print("  " + r.doc.replace("\n", "\n  ") + "\n")
        return 0
    for s in builtin_standards().values():
        print(f"{s.id:6} {s.name} ({len(s.metrics)} metrics)")
        for m in s.metrics:
            print(f"   {m.id:8} {m.name:42} {m.threshold_label:10} rule={m.rule}")
    print("\nYour own: xerscope standards --template my.toml, then --standard my.toml")
    return 0


def _cmd_recalc(args: argparse.Namespace) -> int:
    from .analysis.cpm import compare_assignments, compare_with_stored, schedule
    from .xer import load_snapshot

    for path in _expand(args.paths):
        snap = load_snapshot(path, args.project)
        sched = schedule(snap)
        cmp = compare_with_stored(snap, sched)
        stored = cmp[cmp["stored"].notna()]
        print(
            f"\n{path.name} · {len(snap.activities)} activities · data date {_when(snap.data_date, '%Y-%m-%d %H:%M')}"
            f" · recalculated finish {_when(sched.finish, '%Y-%m-%d %H:%M')}"
        )
        if stored.empty:
            print("  no stored dates to compare (never scheduled in P6?)")
        else:
            agg = stored.groupby("field")["agree"].agg(["sum", "count"])
            for field, r in agg.iterrows():
                print(f"  {field:20} {int(r['sum']):>7} / {int(r['count']):<7} identical")
            bad = stored[~stored["agree"]]
            if len(bad):
                print(bad.head(args.show).to_string(index=False))
            if args.report and len(bad):
                from .verify.shapes import difference_report

                rep = difference_report(snap, cmp)
                rep["share"] = rep["share"].map("{:.0%}".format)
                print("\n  differences by activity shape (status · type · constraint · links · option):")
                print(rep.to_string(index=False))
        a_cmp = compare_assignments(snap, sched)
        a_cmp = a_cmp[a_cmp["stored"].notna()]
        if len(a_cmp):
            print(
                f"  assignments ({a_cmp['taskrsrc_id'].nunique()}): "
                f"{int(a_cmp['agree'].sum())} / {len(a_cmp)} stored dates identical"
            )
            a_bad = a_cmp[~a_cmp["agree"]]
            if len(a_bad):
                print(a_bad.head(args.show).to_string(index=False))
        for w in sched.warnings + [w for w in snap.warnings if "leveling" in w]:
            print(f"  warning: {w}")
        if args.out:
            out = sched.frame.join(snap.activities.set_index("task_code")[["task_name"]])
            dest = (
                Path(args.out)
                if len(args.paths) == 1
                else Path(args.out).with_name(f"{path.stem}_{Path(args.out).name}")
            )
            out.to_csv(dest, encoding="utf-8-sig")
            print(f"  written {dest}")
    return 0


def _cmd_changelog(args: argparse.Namespace) -> int:
    from .analysis.changelog import changelog, summary
    from .xer import load_snapshot

    old, new = load_snapshot(args.old, args.project), load_snapshot(args.new, args.project)
    log = changelog(old, new)
    print(summary(log).to_string(index=False))
    if args.out:
        log.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\nwritten {args.out} ({len(log)} changes)")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from .export import write_tables
    from .store import SnapshotStore

    store = SnapshotStore.from_folder(args.folder, project_code=args.project)
    for p in write_tables(store, args.out, args.format):
        print(p)
    return 0


def _cmd_crosscheck(args: argparse.Namespace) -> int:
    if args.p6:
        return _cmd_crosscheck_p6(args)
    if args.cpm:
        return _cmd_crosscheck_cpm(args)
    from .crosscheck import compare_paths

    df = compare_paths(_expand(args.paths))
    if args.out:
        df.to_csv(args.out, index=False, encoding="utf-8-sig")
    summary = df.groupby("file")["agree"].agg(agree="sum", checks="count")
    print(summary.to_string())
    bad = df[~df["agree"]]
    print(f"\n{len(bad)} disagreement(s) out of {len(df)} checks")
    if len(bad):
        print(bad.groupby("field").size().to_string())
        print(bad.head(30).to_string(index=False))
    return 1 if len(bad) else 0


def _cmd_crosscheck_p6(args: argparse.Namespace) -> int:
    """The CPM against P6 23.12's own results on the held-out corpus (set folders as paths)."""
    import pandas as pd

    from .crosscheck import p6_heldout_score

    frames = [p6_heldout_score(Path(p).expanduser()) for p in args.paths]
    d = pd.concat(frames, ignore_index=True)
    err = d[d["field"] == "error"]
    d = d[d["field"] != "error"]
    for name, g in d.groupby("set"):
        by = g.groupby("field")["agree"].mean().mul(100).round(1)
        rd = g[g["resource_dependent"]]
        print(
            f"{name}: {g['agree'].mean():.1%} of {len(g)} values identical to P6"
            + (
                f" ({rd['agree'].mean():.1%} on {rd['task_code'].nunique()} resource-dependent activities)"
                if len(rd)
                else ""
            )
        )
        print("   " + "  ".join(f"{k} {v}%" for k, v in by.items()))
    for e in err.itertuples():
        print(f"  {e.set} {e.case}: cannot schedule: {e.xerscope}")
    if args.out:
        d.to_csv(args.out, index=False, encoding="utf-8-sig")
    bad = d[~d["agree"]]
    if len(bad) and args.show:
        print(
            bad[["set", "case", "task_code", "status", "field", "p6", "xerscope"]]
            .head(args.show)
            .to_string(index=False)
        )
    return 0 if bad.empty else 1


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
        snap = load_snapshot(path)
        cmp = cpm_crosscheck(path).assign(file=path.name)
        frames.append(cmp)
        ok = cmp[cmp["comparable"]]
        print(f"\n{path.name} · {ok['task_code'].nunique()} open activities")
        agg = ok.groupby("field")[["xs_mpxj_work", "xs_p6", "mpxj_p6"]].mean().mul(100).round(2)
        agg.columns = ["xerscope = MPXJ %", "xerscope = stored %", "MPXJ = stored %"]
        print(agg.to_string())
        for u in mpxj_unsupported(snap):
            print(f"  option MPXJ does not model: {u}")
        for k in sorted(settled_patterns(snap)):
            print(f"  MPXJ differs from P6 here: {P6_SETTLED[k]}")
        for k in sorted(unresolved_patterns(snap)):
            print(f"  open question present: {UNRESOLVED[k]}")
        broken = mpxj_inconsistent(snap, cmp)
        if broken:
            print(f"  MPXJ contradicts itself on: {', '.join(sorted(broken)[:8])}")
        bad = ok[~ok["xs_mpxj_work"]]
        bad = bad[[excused_row(snap, c, f) is None for c, f in zip(bad["task_code"], bad["field"], strict=True)]]
        explained = unresolved_patterns(snap) or settled_patterns(snap) or broken or mpxj_unsupported(snap)
        if len(bad) and not explained:
            unexplained += len(bad)
            print(bad[["task_code", "field", "p6", "xerscope", "mpxj"]].head(args.show).to_string(index=False))
    if args.out:
        pd.concat(frames).to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"\n{unexplained} difference(s) no listed cause explains")
    return 1 if unexplained else 0


def _cmd_sample(args: argparse.Namespace) -> int:
    from .sample import generate

    for p in generate(args.out, weeks=args.weeks):
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="xerscope", description="Weekly P6 XER analysis")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("app", help="launch the web app")
    a.add_argument("--data", help="folder of weekly .xer files to preload")
    a.add_argument("--baseline", help="baseline .xer (contract baseline)")
    a.add_argument("--standards", help="folder of your own standard .toml files")
    a.add_argument("--port", type=int, default=8501)
    a.add_argument(
        "--host",
        default="localhost",
        help="interface to listen on; default localhost. 0.0.0.0 exposes your schedules to the network",
    )
    a.set_defaults(fn=_cmd_app)

    i = sub.add_parser("info", help="summarise one or more XER files / folders")
    i.add_argument("paths", nargs="+")
    i.add_argument("--project", help="project short name, if files hold several")
    i.set_defaults(fn=_cmd_info)

    k = sub.add_parser("check", help="run a standard (P6, DCMA or a .toml) on XER files")
    k.add_argument("paths", nargs="+")
    k.add_argument("--standard", default="P6", help="P6, DCMA or path to your .toml")
    k.add_argument("--baseline", help="baseline .xer for BEI / missed / late checks")
    k.add_argument(
        "--planned-baseline", action="store_true", help="no baseline file: use each file's planned dates (target_*)"
    )
    k.add_argument("--project")
    k.add_argument("--out", help="write all results to this CSV")
    k.add_argument("--flagged", metavar="DIR", help="write the items found by each check, one CSV per file and check")
    k.add_argument(
        "--expect",
        metavar="CSV",
        help="counts typed from P6's Check Schedule summary (id,found,total[,file]); exit 1 on a difference",
    )
    k.add_argument(
        "--fail-on",
        choices=["none", "fail", "error"],
        default="none",
        help="exit 1 when a check fails (fail) or cannot run (error); default: always 0",
    )
    k.set_defaults(fn=_cmd_check)

    st = sub.add_parser("standards", help="list standards and rules, or print the template")
    st.add_argument("--rules", action="store_true", help="list rules and their parameters")
    st.add_argument(
        "--template",
        nargs="?",
        const="-",
        metavar="FILE",
        help="write a standard template to FILE (UTF-8), or print it",
    )
    st.set_defaults(fn=_cmd_standards)

    r = sub.add_parser("recalc", help="reschedule like P6 and compare with the dates stored in the file")
    r.add_argument("paths", nargs="+")
    r.add_argument("--project")
    r.add_argument("--out", help="write the recalculated dates and float to this CSV")
    r.add_argument("--report", action="store_true", help="group the differences by activity shape")
    r.add_argument("--show", type=int, default=20, help="differences to print")
    r.set_defaults(fn=_cmd_recalc)

    g = sub.add_parser("changelog", help="what changed between two XER files")
    g.add_argument("old")
    g.add_argument("new")
    g.add_argument("--project")
    g.add_argument("--out", help="write the full changelog to this CSV")
    g.set_defaults(fn=_cmd_changelog)

    e = sub.add_parser("export", help="write BI tables (Power BI star schema)")
    e.add_argument("folder")
    e.add_argument("--out", default="export")
    e.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    e.add_argument("--project")
    e.set_defaults(fn=_cmd_export)

    c = sub.add_parser("crosscheck", help="compare xerscope with MPXJ on XER files (needs Java)")
    c.add_argument("paths", nargs="+")
    c.add_argument("--out", help="write every comparison to this CSV")
    c.add_argument(
        "--cpm",
        action="store_true",
        help="compare the recalculation with MPXJ's scheduler (build it: tests/reference/mpxj_cpm.py)",
    )
    c.add_argument(
        "--p6",
        action="store_true",
        help="paths are held-out set folders (tests/reference/data/p6-heldout/validation/held-out/H1 ...): "
        "compare the recalculation with what P6 23.12 scheduled",
    )
    c.add_argument("--show", type=int, default=20, help="differences to print")
    c.set_defaults(fn=_cmd_crosscheck)

    s = sub.add_parser("sample", help="generate demo weekly XER files")
    s.add_argument("--out", default="data/sample")
    s.add_argument("--weeks", type=int, default=8)
    s.set_defaults(fn=_cmd_sample)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
