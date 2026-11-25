"""Feasibility study: can a local model answer questions about a weekly schedule series?

    docker compose -f compose.yaml -f compose.silo.yaml -f compose.gpu.yaml run --rm study [--data /data]

Run on the maintainer's own machine, inside the silo network of ``compose.gpu.yaml``, against a
llama.cpp ``llama-server`` that only the silo reaches (docs/deploy.md §12). Nothing here is part
of the app: ``src/`` has no network import, and this script talks to ``llm`` on the silo or to a
loopback address only (``is_model_url``; a loopback URL serves the tests' fake server).

Each question is asked twice, from the same series:

- grounded: the model gets the facts xerscope computed (``store.history``,
  ``activity_half_step_series``, ``half_step_series``, ``path_churn``) as compact JSON and must
  read the answer out of them;
- raw: the model gets the series itself as CSV (the history columns the question needs, at most
  ``--max-rows`` rows) and must compute the answer.

The truth is the same value, computed by xerscope. A reply is correct when it holds that value
(a date exactly, a number within the question's tolerance). It has an invented value when it
quotes an Activity ID, a date or, in grounded mode, a number that is nowhere in what the model
was given. In raw mode a number is not checked: the model is asked to compute it.

The report names no activity, project or file: activities are numbered in the order the study
picked them, so a report on real files (``--data``) can be read without leaking them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

import pandas as pd

from xerscope.analysis.activity_forensics import activity_half_step_series
from xerscope.analysis.forensics import half_step_series
from xerscope.analysis.longest_path import path_churn
from xerscope.sample import generate
from xerscope.store import SnapshotStore

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "tests" / "llm_study" / "questions.toml"
GROUNDED, RAW = "grounded", "raw"
MODES = (GROUNDED, RAW)
# Exactly these names: 127.0.0.2 and the rest of 127.0.0.0/8 are loopback too, but a list of names
# is easier to audit than a range.
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
SILO_HOST = "llm"  # compose.gpu.yaml: the model's name on the internal network, unknown outside it
MODEL_HOSTS = (*LOOPBACK_HOSTS, SILO_HOST)
TIMEOUT_S = 600  # a raw prompt of 15,000 tokens can take a minute to read on a 12 GB card
SYSTEM_PROMPT = "Answer from the data given only, in one sentence. Write every date as YYYY-MM-DD."
DAY_FORMAT = "%Y-%m-%d"

# an Activity ID: a capital, then letters, digits, "-" or "_", with a digit somewhere (A1020, CIV-1010)
ID_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\b")
DATE_PATTERN = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")  # also inside 2026-12-18T16:00
NUMBER_PATTERN = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?")


# --- the checker: pure functions ------------------------------------------------------------


@dataclass(frozen=True)
class Values:
    """The Activity IDs, ISO dates and numbers a text holds; a number inside a date or an ID is not one."""

    ids: frozenset[str]
    dates: frozenset[str]
    numbers: tuple[float, ...]


def extract_values(text: str) -> Values:
    """Read every Activity ID, date (YYYY-MM-DD) and number of ``text``, a Unicode minus read as "-"."""
    text = text.replace("−", "-")
    ids = frozenset(ID_PATTERN.findall(text))
    dates = frozenset(DATE_PATTERN.findall(text))
    rest = DATE_PATTERN.sub(" ", ID_PATTERN.sub(" ", text))
    return Values(ids, dates, tuple(float(number) for number in NUMBER_PATTERN.findall(rest)))


def invented_values(reply: str, given: str, is_number_checked: bool) -> list[str]:
    """The IDs, dates and (when ``is_number_checked``) numbers of ``reply`` that ``given`` does not hold.

    A number is compared without its sign: a sign error is a wrong answer (``is_correct``), not an
    invented value.
    """
    found, allowed = extract_values(reply), extract_values(given)
    invented = sorted(found.ids - allowed.ids) + sorted(found.dates - allowed.dates)
    if is_number_checked:
        allowed_sizes = {abs(number) for number in allowed.numbers}
        invented += [f"{number:g}" for number in found.numbers if abs(number) not in allowed_sizes]
    return invented


def is_correct(reply: str, truth: str | float, tolerance: float) -> bool:
    """The reply holds the truth: the date written exactly, or a number within ``tolerance`` (inclusive).

    Any number of the reply may match, so a reply that lists several numbers is read generously.
    """
    found = extract_values(reply)
    if isinstance(truth, str):
        return truth in found.dates
    return any(abs(number - truth) <= tolerance for number in found.numbers)


# --- the host guard and the model call ---------------------------------------------------


def is_model_url(url: str) -> bool:
    """The URL is http(s) and its host (not a userinfo, not a prefix of a longer name) is a loopback
    name, or ``llm``, the model's name on the silo network, which nothing outside it resolves."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.hostname in MODEL_HOSTS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is an error: the model server cannot send the study elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ProxyHandler({}): an HTTP(S)_PROXY in the environment must not carry the request to a proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


@dataclass(frozen=True)
class Reply:
    """One answer of the model and what the server said it cost (``tokens_per_s`` is None without timings)."""

    text: str
    latency_s: float
    prompt_tokens: int
    tokens_per_s: float | None


Ask = Callable[[str], Reply]  # a prompt in, a reply out: the study never knows which server is behind


def _fetch_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _OPENER.open(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def model_name(url: str) -> str:
    """The id llama-server gives its model at ``/v1/models``."""
    return _fetch_json(f"{url.rstrip('/')}/v1/models")["data"][0]["id"]


def model_caller(url: str, max_tokens: int) -> Ask:
    """An ``Ask`` over the OpenAI-compatible ``/v1/chat/completions`` of a llama-server."""

    def ask(prompt: str) -> Reply:
        payload = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        started = time.perf_counter()
        answer = _fetch_json(f"{url.rstrip('/')}/v1/chat/completions", payload)
        latency_s = time.perf_counter() - started
        return Reply(
            text=answer["choices"][0]["message"]["content"] or "",
            latency_s=latency_s,
            prompt_tokens=answer["usage"]["prompt_tokens"],
            tokens_per_s=answer.get("timings", {}).get("predicted_per_second"),
        )

    return ask


# --- the questions and their truths, computed by xerscope ------------------------------------


def _iso_days(table: pd.DataFrame) -> pd.DataFrame:
    """The table with every date column written YYYY-MM-DD, as the model reads and answers it."""
    table = table.copy()
    for column in table.columns:
        if pd.api.types.is_datetime64_any_dtype(table[column]):
            table[column] = table[column].dt.strftime(DAY_FORMAT)
    return table


def history_table(store: SnapshotStore, task_code: str) -> pd.DataFrame:
    """The activity's finish in each update."""
    history = store.history
    return _iso_days(history.loc[history["task_code"] == task_code, ["data_date", "finish"]])


def activity_table(store: SnapshotStore, task_code: str) -> pd.DataFrame:
    """The activity's finish and the working days it moved by progress and by replanning, per update."""
    series = activity_half_step_series(store, task_code)
    return _iso_days(series[["data_date", "finish", "slip_wd", "replanning_wd"]])


def project_table(store: SnapshotStore) -> pd.DataFrame:
    """The project finish and the working days it moved by progress and by replanning, per update."""
    series = half_step_series(store)
    return _iso_days(series[["data_date", "finish", "slip_wd", "replanning_wd"]])


def path_table(store: SnapshotStore) -> pd.DataFrame:
    """The open activities on the longest path, and those that entered it, per update."""
    return _iso_days(path_churn(store)[["data_date", "on_path", "entered"]])


SOURCES = {"history": history_table, "activity": activity_table, "project": project_table, "path": path_table}


@dataclass(frozen=True)
class Question:
    """One template of ``tests/llm_study/questions.toml``."""

    id: str
    text: str
    source: str
    column: str
    date: str
    tolerance: float
    unit: str
    raw_columns: list[str]

    @property
    def is_about_an_activity(self) -> bool:
        """The text names an Activity ID: it is asked once per activity studied."""
        return "{task_code}" in self.text


@dataclass(frozen=True)
class Case:
    """A question filled for one activity (or none), with its truth and what each mode sends."""

    question: Question
    activity: int | None  # rank of the activity in the study, never its Activity ID
    text: str
    truth: str | float
    facts: str
    csv: str
    csv_rows: int
    csv_total_rows: int


def load_questions(path: Path = QUESTIONS) -> list[Question]:
    """The questions of the TOML, in file order."""
    return [Question(**entry) for entry in tomllib.loads(path.read_text(encoding="utf-8"))["question"]]


def studied_activities(store: SnapshotStore, count: int) -> list[str]:
    """Activity IDs present in every update, open in the latest, the least total float first (then by ID)."""
    history = store.history
    latest = history[history["snapshot_idx"] == len(store) - 1]
    updates_per_code = history.groupby("task_code")["snapshot_idx"].nunique()
    open_in_all = latest[~latest["is_complete"] & latest["task_code"].map(updates_per_code).eq(len(store))]
    ordered = open_in_all.sort_values(["total_float_d", "task_code"])
    return ordered["task_code"].head(count).tolist()


def raw_series(store: SnapshotStore, columns: list[str], max_rows: int) -> tuple[str, int, int]:
    """The history columns as CSV in series order (update, then Activity ID), cut at ``max_rows``.

    Returns the CSV, the rows sent and the rows the series has.
    """
    series = store.history.sort_values(["data_date", "task_code"])[columns]
    sent = _iso_days(series.head(max_rows))
    return sent.to_csv(index=False), len(sent), len(series)


def _truth(table: pd.DataFrame, date: str, column: str) -> str | float | None:
    """The value of ``column`` in the row dated ``date``, None when the row or the value is missing."""
    values = table.loc[table["data_date"] == date, column].dropna()
    if values.empty:
        return None
    value = values.iloc[0]
    return value if isinstance(value, str) else float(value)


def _facts_json(table: pd.DataFrame) -> str:
    """The table as compact JSON records, a missing value as null."""
    return table.astype(object).where(table.notna(), None).to_json(orient="records")


def build_cases(store: SnapshotStore, questions: list[Question], activity_count: int, max_rows: int) -> list[Case]:
    """Every question filled and its truth read from xerscope's table; one whose truth is missing is skipped."""
    days = [f"{snapshot.data_date:{DAY_FORMAT}}" for snapshot in store]
    dates = {"first": days[0], "latest": days[-1]}
    codes = studied_activities(store, activity_count)
    cases = []
    for question in questions:
        for rank, code in enumerate(codes if question.is_about_an_activity else [None]):
            source = SOURCES[question.source]
            table = source(store, code) if code else source(store)
            date = dates[question.date]
            truth = _truth(table, date, question.column)
            if truth is None:
                print(f"skipped {question.id}: no value on {date}", file=sys.stderr)
                continue
            text = question.text.format(task_code=code, date=date, previous_date=days[-2])
            csv, rows, total = raw_series(store, question.raw_columns, max_rows)
            cases.append(Case(question, rank + 1 if code else None, text, truth, _facts_json(table), csv, rows, total))
    return cases


# --- one run and its report ----------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """One question asked in one mode."""

    case: Case
    mode: str
    reply: Reply
    is_correct: bool
    invented: list[str]


def prompt(case: Case, mode: str) -> str:
    """What the model reads: the facts or the series, then the question."""
    if mode == GROUNDED:
        return f"Facts computed by xerscope (JSON, one record per update):\n{case.facts}\n\nQuestion: {case.text}"
    return f"Schedule series (CSV, one row per activity per update):\n{case.csv}\n\nQuestion: {case.text}"


def run_study(cases: list[Case], ask: Ask) -> list[Result]:
    """Ask every case in both modes and check each reply against its truth and what the model was given."""
    results = []
    for case in cases:
        for mode in MODES:
            reply = ask(prompt(case, mode))
            given = f"{case.facts if mode == GROUNDED else case.csv} {case.text}"
            results.append(
                Result(
                    case,
                    mode,
                    reply,
                    is_correct(reply.text, case.truth, case.question.tolerance),
                    invented_values(reply.text, given, is_number_checked=mode == GROUNDED),
                )
            )
    return results


def _mode_row(mode: str, results: list[Result]) -> str:
    """One line of the summary table: the shares, the means of latency, prompt tokens and speed of a mode."""
    correct = sum(result.is_correct for result in results) / len(results)
    invented = sum(bool(result.invented) for result in results) / len(results)
    speeds = [result.reply.tokens_per_s for result in results if result.reply.tokens_per_s is not None]
    speed = f"{fmean(speeds):.1f}" if speeds else "n/a"
    latency_s = fmean(result.reply.latency_s for result in results)
    prompt_tokens = fmean(result.reply.prompt_tokens for result in results)
    shares = f"{correct:.0%} | {invented:.0%}"
    return f"| {mode} | {len(results)} | {shares} | {latency_s:.1f} | {prompt_tokens:.0f} | {speed} |"


def _result_row(result: Result) -> str:
    """One line of the per-question table; the activity is its rank, never its Activity ID."""
    case = result.case
    sent = f"{case.csv_rows} of {case.csv_total_rows}" if result.mode == RAW else ""
    verdict = "yes" if result.is_correct else "no"
    return (
        f"| {case.question.id} | {case.activity or ''} | {result.mode} | {verdict} | {len(result.invented)}"
        f" | {result.reply.latency_s:.1f} | {result.reply.prompt_tokens} | {sent} |"
    )


def render_report(model: str, store: SnapshotStore, results: list[Result]) -> str:
    """The Markdown report: a table per mode, then one line per question; no name of the series."""
    lines = [
        "# Local model study",
        "",
        f"Model: `{model}`. Series: {len(store)} updates, {len(store.latest.activities)} activities in the latest.",
        "Truths computed by xerscope; activities are numbered in the order the study picked them.",
        "",
        "| mode | questions | correct | invented value | mean latency (s) | mean prompt tokens | mean tokens/s |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines += [_mode_row(mode, [result for result in results if result.mode == mode]) for mode in MODES]
    lines += [
        "",
        "| question | activity | mode | correct | invented | latency (s) | prompt tokens | raw rows sent |",
        "|---|---:|---|---|---:|---:|---:|---:|",
    ]
    lines += [_result_row(result) for result in results]
    return "\n".join(lines) + "\n"


# --- command line ----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Study a local llama-server on a weekly schedule series.")
    parser.add_argument(
        "--url", required=True, help="llama-server base URL: http://llm:8080 in the silo, or a loopback URL"
    )
    parser.add_argument("--out", type=Path, default=Path("report.md"), help="Markdown report to write")
    parser.add_argument("--data", type=Path, help="folder of weekly .xer files; default: the demo series")
    parser.add_argument("--questions", type=Path, default=QUESTIONS, help="question templates (TOML)")
    parser.add_argument("--activities", type=int, default=2, help="activities asked about (least total float first)")
    parser.add_argument("--max-rows", type=int, default=400, help="rows of the raw CSV, about 25 tokens each")
    parser.add_argument("--max-tokens", type=int, default=1024, help="tokens the model may generate per reply")
    return parser


def _study(args: argparse.Namespace, store: SnapshotStore) -> str:
    cases = build_cases(store, load_questions(args.questions), args.activities, args.max_rows)
    results = run_study(cases, model_caller(args.url, args.max_tokens))
    return render_report(model_name(args.url), store, results)


def main(argv: list[str] | None = None) -> int:
    """Run the study; returns the exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not is_model_url(args.url):
        parser.error(f"--url must be http(s) on {', '.join(LOOPBACK_HOSTS)}: the study makes no external call")
    try:
        if args.data:
            report = _study(args, SnapshotStore.from_folder(args.data))
        else:
            with tempfile.TemporaryDirectory() as folder:
                generate(folder)
                report = _study(args, SnapshotStore.from_folder(folder))
    except (urllib.error.URLError, TimeoutError) as error:
        parser.exit(1, f"error: no answer from {args.url} ({error!r})\n")
    args.out.write_text(report, encoding="utf-8")
    print(f"report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
