"""Command line: ``xerscope {app,info,check,recalc,standards,changelog,export,crosscheck,sample}``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

APP_PATH = Path(__file__).parent / "app" / "streamlit_app.py"


def _expand(paths: list[str]) -> list[Path]:
    """Files as given; folders -> their *.xer, sorted."""
    out: list[Path] = []
    for p in (Path(x).expanduser() for x in paths):
        out += sorted(p.glob("*.xer")) if p.is_dir() else [p]
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
        "finish_shift_d",
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
        df = results_frame(run_standard(std, AnalysisContext(snap, store, baseline=base)))
        df.insert(0, "file", path.name)
        df.insert(1, "data_date", snap.data_date)
        frames.append(df)
        print(
            f"\n{std.name} · {path.name} · data date {_when(snap.data_date)}"
            f" · baseline {base.label if base else 'none'}"
        )
        cols = ["id", "check", "target", "actual", "found", "total", "status"]
        print(df[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    if args.out:
        pd.concat(frames).to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\nwritten {args.out}")
    return 0


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
    c.set_defaults(fn=_cmd_crosscheck)

    s = sub.add_parser("sample", help="generate demo weekly XER files")
    s.add_argument("--out", default="data/sample")
    s.add_argument("--weeks", type=int, default=8)
    s.set_defaults(fn=_cmd_sample)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
