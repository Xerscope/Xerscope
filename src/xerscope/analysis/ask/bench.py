"""Scoring a parser on sentences with known filters (tests/ask/, ``xerscope ask-bench``)."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

from .filters import Filter, canonical, written
from .grammar import CATEGORIES, STATUSES
from .parser import parse_keywords
from .text import STOP, SURE, fold, words_of
from .vocab import Vocabulary

FIELDS = ("wbs_id", "status", "categories", "code_ids", "resources", "milestones", "loe", "search", "clauses")

_SAID = {  # one phrase per status and float category, in each language: what a planner says
    "Not started": ["not started", "non démarré"],
    "In progress": ["in progress", "en cours"],
    "Complete": ["complete", "terminé"],
    "Critical": ["critical", "critique"],
    "Near critical": ["near critical", "quasi critique"],
    "Normal": ["normal", "normales"],
}


def self_cases(vocab: Vocabulary) -> list[dict]:
    """Cases drawn from the file's own lexicon: each WBS node by its code, its full name and
    every synonym of its name (the lexicon, both languages); each resource by short name and
    name; each status and float category in both languages; milestones and LOE when the file
    has them. `ask-bench --self` scores them: the share of the file's labels the grammar can
    name, and the labels it cannot (what a company's lexicon file should add)."""
    cases = [case for wbs_id, label in vocab.wbs.items() for case in _node_cases(wbs_id, label, vocab)]
    for short, name in vocab.resources.values():
        for text in dict.fromkeys(t for t in (short, name, *vocab.lexicon.get(fold(name), ())) if t):
            cases.append({"text": text, "resources": [short or name], "label": f"resource {short or name}"})
    return cases + _grammar_cases(vocab)


def _grammar_cases(vocab: Vocabulary) -> list[dict]:
    """Each status and float category in both languages; milestones and LOE when the file has them."""
    cases: list[dict] = [{"text": t, "status": [s], "label": f"status {s}"} for s in STATUSES for t in _SAID[s]]
    cases += [{"text": t, "float": [c], "label": f"float {c}"} for c in CATEGORIES[:3] for t in _SAID[c]]
    if vocab.has_milestones:
        cases += [{"text": t, "milestones": True, "label": "milestones"} for t in ("milestones", "jalons")]
    if vocab.has_loe:
        cases += [{"text": t, "loe": True, "label": "level of effort"} for t in ("LOE", "hamacs")]
    return cases


def _node_cases(wbs_id: str, label: str, vocab: Vocabulary) -> list[dict]:
    """A node by its code, its name, the synonyms of its name words, and its own words (node and search)."""
    code, _, name = label.partition(" · ")
    said = [code, name] if name else [code]
    for word in words_of(name):
        if len(word) >= 4 and word not in STOP:
            said += [w for w in vocab.lexicon.get(word, ()) if " " in w or len(w) >= 4]
    said += vocab.lexicon.get(fold(name), ())
    cases = [{"text": text, "wbs": code, "label": f"WBS {label}"} for text in dict.fromkeys(t for t in said if t)]
    for word in sorted(vocab.node_words.get(wbs_id, ()))[:5]:
        cases.append({"text": word, "wbs": code, "search": word, "label": f"WBS {label} (own word {word})"})
    return cases


def coverage(vocab: Vocabulary) -> tuple[pd.DataFrame, list[str]]:
    """``score`` on ``self_cases``: the scored frame with each case's label, and the labels of
    the file no phrase reached (every one of a label's phrases right = covered)."""
    cases = self_cases(vocab)
    scored = score(cases, vocab)
    scored["label"] = [case["label"] for case in cases]
    missed = sorted(set(scored.loc[~scored["exact"], "label"]))
    return scored, missed


def load_cases(path) -> list[dict]:
    """Sentences with their expected filters, from a TOML file of ``[[case]]`` tables. Expected
    values name things as a planner would (a WBS code, a resource short name, ``"Zone:B2"`` for a
    code value) so a file of cases reads without ids; ``expected_filter`` resolves them."""
    return list(tomllib.loads(Path(path).read_text(encoding="utf-8")).get("case", []))


def expected_filter(case: Mapping, vocab: Vocabulary) -> Filter:
    """The ``Filter`` a case expects, its names resolved against the vocabulary; a name the
    vocabulary does not hold raises, so a case cannot silently expect nothing. (``clauses`` are
    compared in canonical form by ``score``.)"""
    code_type, code_ids = _expected_codes(case, vocab)
    return Filter(
        wbs_id=_expected_wbs(case, vocab),
        status=tuple(s for s in STATUSES if s in case.get("status", [])),
        categories=tuple(c for c in CATEGORIES if c in case.get("float", [])),
        code_type=code_type,
        code_ids=code_ids,
        resources=_expected_resources(case, vocab),
        milestones=bool(case.get("milestones", False)),
        loe=bool(case.get("loe", False)),
        search=fold(case.get("search", "")),
    )


def _expected_wbs(case: Mapping, vocab: Vocabulary) -> str | None:
    by_code = {label.split(" · ")[0]: wbs_id for wbs_id, label in vocab.wbs.items()}
    wbs = case.get("wbs")
    if wbs is not None and wbs not in by_code:
        raise KeyError(f"WBS {wbs!r} is not in the file")
    return by_code.get(wbs) if wbs else None


def _expected_codes(case: Mapping, vocab: Vocabulary) -> tuple[str | None, frozenset[str]]:
    code_ids, code_type = set(), None
    for item in case.get("codes", []):
        kind, _, value = item.partition(":")
        matches = [c for c, (t, v, _) in vocab.codes.items() if t == kind and v == value]
        if not matches:
            raise KeyError(f"code value {item!r} is not in the file")
        code_ids.add(matches[0])
        code_type = kind
    return code_type, frozenset(code_ids)


def _expected_resources(case: Mapping, vocab: Vocabulary) -> frozenset[str]:
    by_short = {short or name: rsrc_id for rsrc_id, (short, name) in vocab.resources.items()}
    missing = [n for n in case.get("resources", []) if n not in by_short]
    if missing:
        raise KeyError(f"resource {missing[0]!r} is not in the file")
    return frozenset(by_short[n] for n in case.get("resources", []))


def score(cases: Sequence[Mapping], vocab: Vocabulary) -> pd.DataFrame:
    """One row per case: the sentence, whether every field matched (``exact``), one column per
    field (True when it matched) and the reading's confidence. A ratio of a column is the share
    of cases it got right; ``exact`` is the share of sentences whose every filter was right."""
    rows = []
    for case in cases:
        expected = expected_filter(case, vocab)
        got = parse_keywords(case["text"], vocab)
        fields = {name: getattr(got, name) == getattr(expected, name) for name in FIELDS[:-1]}
        fields["clauses"] = sorted(written(e, vocab) for _, e in got.clauses) == sorted(case.get("clauses", []))
        rows.append(
            {
                "text": case["text"],
                "exact": all(fields.values()),
                **fields,
                "confidence": got.confidence,
            }
        )
    return pd.DataFrame(rows, columns=["text", "exact", *FIELDS, "confidence"])


def understood(cases: list[Mapping], vocab: Vocabulary) -> pd.DataFrame:
    """One row per case of a ``[[case]] text, expect[, ignored]`` file: the filter read
    (``canonical``), the one expected, and whether they match (and the words left out, when the
    case names them). The share of ``exact`` is the share of sentences understood."""
    rows = []
    for case in cases:
        got = parse_keywords(case["text"], vocab)
        read = canonical(got, vocab)
        exact = read == case.get("expect", "") and sorted(got.ignored) == sorted(case.get("ignored", got.ignored))
        rows.append(
            {
                "text": case["text"],
                "expect": case.get("expect", ""),
                "got": read,
                "ignored": got.ignored,
                "exact": exact,
            }
        )
    return pd.DataFrame(rows, columns=["text", "expect", "got", "ignored", "exact"])


def ratios(scored: pd.DataFrame) -> dict[str, float]:
    """Share of cases right, overall (``exact``) and per field."""
    return {name: float(scored[name].mean()) if len(scored) else 0.0 for name in ("exact", *FIELDS)}


def by_confidence(scored: pd.DataFrame) -> pd.DataFrame:
    """Sentences and share right, for the confident answers (>= SURE) and the unsure ones: the
    confidence index is only worth showing if the unsure answers are indeed wrong more often."""
    sure = scored["confidence"] >= SURE
    shares = [float(scored.loc[part, "exact"].mean()) if part.any() else float("nan") for part in (sure, ~sure)]
    return pd.DataFrame({"sentences": [int(sure.sum()), int((~sure).sum())], "exact": shares}, index=["sure", "unsure"])
