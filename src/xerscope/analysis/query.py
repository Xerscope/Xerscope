"""A sentence turned into the Gantt page's filters: "critical not started in civil works".

The page owns the filtering (WBS branch, status, float category, activity codes, resources,
milestones, level of effort, text, and the clauses no widget says: NOT, OR across facets...).
This module is the one entry point the rest of xerscope imports; the grammar lives in
``analysis/ask/`` (lexer, parser, facets, answer, scoring), and a number never comes from it:
a filter the parser picks is a set the user could have built by hand.

``parse`` tries the backend it is given (a local language model, measured only, absent by
default) and always falls back on ``parse_keywords``, a bilingual (English / French) grammar
over the file's own lexicon (``Vocabulary``). The page therefore never depends on a model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

import pandas as pd

from ..xer import Snapshot
from .ask.answer import SUGGEST, WORDS, answer, language, suggestions
from .ask.bench import (
    FIELDS,
    by_confidence,
    coverage,
    expected_filter,
    load_cases,
    ratios,
    score,
    self_cases,
    understood,
)
from .ask.filters import Filter, canonical, conjuncts, said, without, written
from .ask.funnel import apply, funnel_line, mask
from .ask.generated import counts as variant_counts
from .ask.generated import lexicons, load_refusals, load_variants, refuse, variants
from .ask.generated import to_toml as variants_toml
from .ask.grammar import CATEGORIES, STATUSES, And, Atom, Expr, Not, Or
from .ask.lexicon import CURATED, GENERATED, SUGGESTED, Lexicon, json_quote, learn, lexicon_from_groups, load_lexicon
from .ask.parser import MAX_CHARS, Backend, parse, parse_keywords, warm
from .ask.text import FUZZY, MARGIN, SURE, fold
from .ask.vocab import Vocabulary, vocabulary
from .populations import Funnel

__all__ = [
    "CATEGORIES", "CURATED", "GENERATED", "SUGGESTED",
    "FIELDS", "FUZZY", "MARGIN", "MAX_CHARS", "STATUSES", "SUGGEST", "SURE", "WORDS", "And", "Atom",
    "Backend", "Expr", "Filter", "Lexicon", "Not", "Or", "Vocabulary", "answer", "apply", "by_confidence",
    "canonical", "conjuncts", "coverage", "expected_filter", "facts", "fold", "from_answer", "funnel_line",
    "grounded", "json_quote", "language", "learn", "lexicon_from_groups", "llm_backend",
    "load_cases", "load_lexicon", "mask", "parse", "parse_keywords", "ratios", "said", "score", "self_cases",
    "suggestions", "summary", "understood", "vocabulary", "warm", "without", "written", "variants", "lexicons",
    "load_variants", "variant_counts", "variants_toml", "load_refusals", "refuse",
]  # fmt: skip


# --- a summary of what came out, by a model, from computed values only ---------------------

FACT_ROWS = 10  # activities handed to a model for a summary: the worst floats first


def facts(funnel: Funnel, snapshot: Snapshot, limit: int = FACT_ROWS) -> dict:
    """What a model may read to summarise an answer: the funnel's steps and counts, the rows
    with the worst total float (Activity ID, float in working days, finish date), and the
    successors of the worst one. Values computed by xerscope, never a name, never the file."""
    rows = funnel.rows
    ordered = rows.sort_values("total_float_d", na_position="last").head(limit) if len(rows) else rows
    listed = [
        [str(code), None if pd.isna(tf) else float(tf), None if pd.isna(finish) else f"{finish:%Y-%m-%d}"]
        for code, tf, finish in zip(ordered["task_code"], ordered["total_float_d"], ordered["finish"], strict=True)
    ]
    worst = listed[0][0] if listed else None
    successors: list[str] = []
    if worst is not None and not snapshot.relationships.empty:
        links = snapshot.relationships
        successors = sorted(set(links.loc[links["pred_code"] == worst, "succ_code"].astype(str)))[:5]
    return {
        "count": int(len(rows)),
        "steps": [[step.label, int(step.left)] for step in funnel.steps],
        "rows": listed,
        "successors_of_worst": successors,
        "data_date": None if snapshot.data_date is None else f"{snapshot.data_date:%Y-%m-%d}",
    }


_TOKEN = re.compile(r"[A-Za-z]*\d[\w./-]*")  # a number, an Activity ID, a date: anything with a digit


def grounded(text: str, given: dict) -> bool:
    """Whether every number, Activity ID and date of ``text`` is among the values given: a
    summary that fails this is dropped, the template answer standing alone."""
    allowed: set[str] = set()

    def collect(value) -> None:
        if isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, int | float):
            number = float(value)
            allowed.update({f"{number:g}", f"{abs(number):g}", f"{number:.0f}", f"{abs(number):.0f}", f"{number:+.0f}"})
        elif isinstance(value, str):
            allowed.add(value)
            allowed.update(_TOKEN.findall(value))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):  # a date, however the model writes it
                y, m, d = value.split("-")
                allowed.update({f"{d}/{m}/{y}", f"{y}/{m}/{d}", f"{m}/{d}/{y}", d, m, y, f"{int(d)}", f"{int(m)}"})

    collect(given)
    for token in _TOKEN.findall(text):
        plain = token.rstrip(".,;:")
        if plain in allowed or plain.lstrip("+-") in allowed:
            continue
        return False
    return True


_SUMMARY = (
    "You write one short English sentence (at most 40 words) for a planner, from the JSON facts given: what the "
    "question found in the schedule. Use only the numbers, Activity IDs and dates in the facts, exactly as written; "
    "never add, round or estimate a value; name the worst activity and what it drives when given. No preamble."
)


# --- a language model, for measurement only (ask-bench --url, --summary) -------------------
# Nothing deployed uses this: the app reads sentences with the grammar and the lexicon, and
# answers from a template. The client stays so a model can be measured against them
# (docs/deploy.md §10 holds the last figures) without wiring anything back.

_SCHEMA = {  # what the model may answer: ids and labels of the vocabulary, nothing else
    "type": "object",
    "properties": {
        "wbs_id": {"type": ["string", "null"]},
        "status": {"type": "array", "items": {"type": "string", "enum": STATUSES}},
        "float": {"type": "array", "items": {"type": "string", "enum": CATEGORIES}},
        "code_ids": {"type": "array", "items": {"type": "string"}},
        "resource_ids": {"type": "array", "items": {"type": "string"}},
        "milestones": {"type": "boolean"},
        "loe": {"type": "boolean"},
        "search": {"type": "string"},
    },
    "required": ["wbs_id", "status", "float", "code_ids", "resource_ids", "milestones", "loe", "search"],
    "additionalProperties": False,
}
_SYSTEM = (
    "You turn a planner's sentence (English or French) into filters over a Primavera P6 schedule. "
    'Answer with JSON matching the schema, using only ids from the vocabulary; null, [] or "" when the '
    "sentence does not ask for a filter. 'search' is a text to find in activity names, in the sentence's "
    "language, for what no other filter covers. Vocabulary: "
)


def from_answer(data: Mapping, vocab: Vocabulary) -> Filter:
    """A model's JSON answer as a ``Filter``: ids the vocabulary does not hold are dropped, so an
    invented id filters nothing; a code type is taken from the first code id kept."""
    wbs_id = data.get("wbs_id")
    wbs_id = wbs_id if isinstance(wbs_id, str) and wbs_id in vocab.wbs else None
    code_ids = frozenset(c for c in _strings(data.get("code_ids")) if c in vocab.codes)
    code_type = next((vocab.codes[c][0] for c in sorted(code_ids)), None)
    search = data.get("search").strip() if isinstance(data.get("search"), str) else ""
    asked = Filter(
        wbs_id=wbs_id,
        status=tuple(s for s in STATUSES if s in _strings(data.get("status"))),
        categories=tuple(c for c in CATEGORIES if c in _strings(data.get("float"))),
        code_type=code_type,
        code_ids=frozenset(c for c in code_ids if vocab.codes[c][0] == code_type),
        resources=frozenset(r for r in _strings(data.get("resource_ids")) if r in vocab.resources),
        milestones=bool(data.get("milestones")),
        loe=bool(data.get("loe")),
        search=search,
        source="model",
    )
    return replace(asked, matched=_model_matched(asked, vocab))


def _model_matched(asked: Filter, vocab: Vocabulary) -> tuple[str, ...]:
    """The chips of a model's answer, in the order of the page's widgets."""
    matched = [f"WBS: {vocab.wbs[asked.wbs_id]}"] if asked.wbs_id else []
    matched += [f"Status: {s}" for s in asked.status] + [f"Float: {c}" for c in asked.categories]
    matched += [f"{asked.code_type}: {vocab.codes[c][1]}" for c in sorted(asked.code_ids)]
    matched += [f"Resource: {vocab.resources[r][0] or vocab.resources[r][1]}" for r in sorted(asked.resources)]
    matched += ["Milestones"] * asked.milestones + ["Level of effort"] * asked.loe
    return tuple(matched + ([f"Search: {asked.search}"] if asked.search else []))


def _strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def llm_backend(url: str, timeout: float = 20.0, key: str = "", cafile: str = "") -> Backend:
    """A ``Backend`` on a llama.cpp server (OpenAI-compatible ``/v1/chat/completions``) at
    ``url``, answering with JSON constrained by the schema. The request carries the sentence and
    ``Vocabulary.to_prompt()`` only, with ``key`` as a bearer token (the server's ``--api-key``)
    over https verified against ``cafile`` alone (the model's own CA, pinned). Off the loopback
    all three are required: a plain http model is refused at configuration. Any failure
    (server down, slow, bad answer, refused key, bad certificate) is None, and the keyword
    grammar answers. Nothing here logs the URL, the key or the answer."""
    import json
    import ssl
    import urllib.parse
    import urllib.request

    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("XERSCOPE_QUERY_URL must be an http(s) URL")
    loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if not loopback and not (parts.scheme == "https" and cafile and key):
        # off this host the link is TLS to a pinned CA, with a key, or nothing (docs/deploy.md §10)
        raise ValueError(
            "a model off this host needs an https XERSCOPE_QUERY_URL, XERSCOPE_QUERY_CA and XERSCOPE_QUERY_KEY"
        )
    if cafile and parts.scheme != "https":
        raise ValueError("XERSCOPE_QUERY_CA needs an https URL")
    endpoint = url.rstrip("/") + "/v1/chat/completions"
    contexts: list[ssl.SSLContext] = []  # built on the first call: the CA file may be written after the app starts
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    def context() -> ssl.SSLContext | None:
        if not cafile:
            return None
        if not contexts:
            contexts.append(ssl.create_default_context(cafile=cafile))
        return contexts[0]

    def prefix(vocab: Vocabulary) -> str:
        """The static part of every prompt, byte for byte the same for one file: the rules and the
        vocabulary. The server keeps its KV state (cache_prompt), so after ``warm`` a sentence
        costs its own tokens only."""
        return _SYSTEM + json.dumps(vocab.to_prompt(), ensure_ascii=False, sort_keys=True)

    def post(payload: dict) -> dict | None:
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.urlopen(  # noqa: S310 # nosec B310 (http(s) checked above)
                request, timeout=timeout, context=context()
            ) as response:
                return json.loads(response.read().decode())
        except Exception:  # noqa: BLE001  # whatever failed, the grammar answers
            return None

    def ask(text: str, vocab: Vocabulary) -> Filter | None:
        answer = post(
            {
                "messages": [{"role": "system", "content": prefix(vocab)}, {"role": "user", "content": text}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "filter", "schema": _SCHEMA}},
                "temperature": 0,
                "cache_prompt": True,
            }
        )
        try:
            data = json.loads(answer["choices"][0]["message"]["content"])
        except (TypeError, KeyError, IndexError, ValueError):
            return None
        return from_answer(data, vocab) if isinstance(data, dict) else None

    def warm(vocab: Vocabulary) -> bool:
        """Hand the model the file's vocabulary once (at the file's load, in the background): the
        server reads the prefix now and keeps its state, so the first sentence does not pay for
        it. True when the server answered."""
        answer = post(
            {
                "messages": [{"role": "system", "content": prefix(vocab)}, {"role": "user", "content": "ready?"}],
                "max_tokens": 1,
                "temperature": 0,
                "cache_prompt": True,
            }
        )
        return answer is not None

    def summarise(question: str, given: dict, max_tokens: int = 60):
        """The model's summary of ``given`` for ``question``, streamed: a generator of text
        pieces as the server sends them (SSE), empty when the server fails. The caller joins the
        pieces and keeps the text only when ``grounded``."""
        payload = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": _SUMMARY},
                    {"role": "user", "content": question + "\n" + json.dumps(given, sort_keys=True)},
                ],
                "max_tokens": max_tokens,
                "temperature": 0,
                "cache_prompt": True,
                "stream": True,
                "stop": ["\n"],
            }
        ).encode()
        request = urllib.request.Request(endpoint, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(  # noqa: S310 # nosec B310 (http(s) checked above)
                request, timeout=timeout, context=context()
            ) as response:
                for raw in response:
                    line = raw.decode(errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        piece = json.loads(data)["choices"][0]["delta"].get("content", "")
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    if piece:
                        yield piece
        except Exception:  # noqa: BLE001  # the template answer stands alone
            return

    ask.warm = warm  # type: ignore[attr-defined]
    ask.summarise = summarise  # type: ignore[attr-defined]
    return ask


def summary(backend: Backend | None, question: str, given: dict):
    """``backend.summarise`` when the backend has one, else an empty generator."""
    summariser = getattr(backend, "summarise", None)
    if callable(summariser):
        yield from summariser(question, given)
