"""A sentence turned into the Gantt page's filters: "critical not started in civil works".

The page owns the filtering (WBS branch, status, float category, activity codes, resources,
milestones, level of effort, text, and the clauses no widget says: NOT, OR across facets...).
This module is the one entry point the rest of xerscope imports; the grammar lives in
``analysis/ask/`` (lexer, parser, facets, answer, scoring), and a number never comes from it:
a filter the parser picks is a set the user could have built by hand.

``parse_keywords`` is a bilingual (English / French) grammar over the file's own lexicon
(``Vocabulary``).
"""

from __future__ import annotations

import pandas as pd

from ..xer import Snapshot
from .ask.answer import SUGGEST, WORDS, answer, language, suggestions, worst_float_first
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
from .ask.filters import Choice, Filter, canonical, conjuncts, said, without, written
from .ask.funnel import apply, funnel_line, mask
from .ask.generated import counts as variant_counts
from .ask.generated import lexicons, load_refusals, load_variants, near_spellings, refuse, variants
from .ask.generated import to_toml as variants_toml
from .ask.grammar import CATEGORIES, STATUSES, And, Atom, Expr, Not, Or
from .ask.lexicon import CURATED, GENERATED, SUGGESTED, Lexicon, json_quote, learn, lexicon_from_groups, load_lexicon
from .ask.parser import MAX_CHARS, parse_keywords
from .ask.text import FUZZY, MARGIN, MAX_FUZZY, SURE, fold
from .ask.vocab import Vocabulary, vocabulary
from .populations import Funnel

__all__ = [
    "CATEGORIES", "CURATED", "GENERATED", "SUGGESTED",
    "FIELDS", "FUZZY", "MARGIN", "MAX_CHARS", "MAX_FUZZY", "STATUSES", "SUGGEST", "SURE", "WORDS", "And", "Atom",
    "Choice", "Expr", "Filter", "Lexicon", "Not", "Or", "Vocabulary", "answer", "apply", "by_confidence",
    "canonical", "conjuncts", "coverage", "expected_filter", "facts", "fold", "funnel_line",
    "json_quote", "language", "learn", "lexicon_from_groups", "load_cases", "load_lexicon", "mask", "parse_keywords",
    "ratios", "said", "score", "self_cases",
    "suggestions", "understood", "vocabulary", "without", "written", "variants", "lexicons",
    "load_variants", "variant_counts", "variants_toml", "load_refusals", "refuse", "near_spellings",
    "worst_float_first",
]  # fmt: skip


# --- what an answer computed: the funnel and the worst floats ------------------------------

FACT_ROWS = 10  # activities listed: the worst floats first


def facts(funnel: Funnel, snapshot: Snapshot, limit: int = FACT_ROWS) -> dict:
    """What an answer computed: the funnel's steps and counts, the rows with the worst total
    float (Activity ID, float in working days, finish date), and the
    successors of the worst one. Values computed by xerscope, never a name, never the file."""
    rows = funnel.rows
    ordered = worst_float_first(rows).head(limit)
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
