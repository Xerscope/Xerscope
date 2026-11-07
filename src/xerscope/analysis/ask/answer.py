"""The answer in words, from the funnel's rows; the closest labels for a word nothing holds."""

from __future__ import annotations

import difflib
import re

import pandas as pd

from ..populations import Funnel
from .filters import Filter, said
from .lexer import phrase_languages
from .text import fold, plain, tokens, with_synonyms
from .vocab import Vocabulary

# words that tell the language when no phrase of the grammar does ("le", "the")
_LANGUAGE_WORDS = {
    "fr": frozenset(
        [
            "le",
            "la",
            "les",
            "des",
            "du",
            "de",
            "un",
            "une",
            "dans",
            "pour",
            "sur",
            "avec",
            "qui",
            "que",
            "quoi",
            "tout",
            "toutes",
            "montre",
            "affiche",
        ]
    ),
    "en": frozenset(["the", "of", "in", "on", "for", "with", "which", "what", "show", "list", "all", "every"]),
}


def language(text: str) -> str:
    """ "fr" or "en": the language of the grammar's phrases the sentence holds (each phrase is
    tagged), then of its common words; a tie is French when the sentence has an accent, else
    English. The answer is written in it."""
    votes = {"fr": 0, "en": 0}
    found = tokens(text)
    for lang in phrase_languages(found):
        votes[lang] = votes.get(lang, 0) + 1
    for lang, words in _LANGUAGE_WORDS.items():
        votes[lang] += sum(token in words for token in found)
    if votes["fr"] != votes["en"]:
        return "fr" if votes["fr"] > votes["en"] else "en"
    return "fr" if any(c in "àâçéèêëîïôûùüÿœ" for c in text.lower()) else "en"


WORDS = {
    "en": {
        "none": "No activity matches.",
        "one": "1 activity",
        "many": "{n} activities",
        "milestone_one": "1 milestone",
        "milestone_many": "{n} milestones",
        "in": "in {label}",
        "status": {"Not started": "not started", "In progress": "in progress", "Complete": "complete"},
        "float": {"Critical": "critical", "Near critical": "near critical", "Normal": "with float"},
        "worst": "worst float {f} wd ({code})",
        "finish": "latest finish {date}",
        "resource": "with {name}",
        "loe": "level of effort",
        "named": 'named "{text}"',
        "nothing": "Nothing understood: no activity shown.",
        "unknown_one": " The word {words} is in neither this file nor the lexicon.",
        "unknown_many": " The words {words} are in neither this file nor the lexicon.",
    },
    "fr": {
        "none": "Aucune activité ne correspond.",
        "one": "1 activité",
        "many": "{n} activités",
        "milestone_one": "1 jalon",
        "milestone_many": "{n} jalons",
        "in": "dans {label}",
        "status": {"Not started": "non démarrée(s)", "In progress": "en cours", "Complete": "terminée(s)"},
        "float": {"Critical": "critique(s)", "Near critical": "quasi critique(s)", "Normal": "avec marge"},
        "worst": "pire marge {f} j ({code})",
        "finish": "dernière fin {date}",
        "resource": "avec {name}",
        "loe": "niveau d'effort",
        "named": "nommée(s) « {text} »",
        "nothing": "Rien de compris : aucune activité affichée.",
        "unknown_one": " Le mot {words} n'est ni dans ce fichier ni dans le lexique.",
        "unknown_many": " Les mots {words} ne sont ni dans ce fichier ni dans le lexique.",
    },
}


def answer(filter: Filter, funnel: Funnel, vocab: Vocabulary, lang: str = "en") -> str:
    """One sentence from the funnel's rows, in ``lang``: the count, what was asked (node, status,
    float, resource, milestones, LOE, search, clauses), then the worst total float and the
    latest finish of the rows, and the words left out. Every number is a column of the frame
    (``total_float_d`` in working days, ``finish``); nothing is estimated."""
    words = WORDS["fr" if lang == "fr" else "en"]
    unknown = _unknown_note(filter, words)
    if filter.empty and filter.ignored:
        return words["nothing"] + unknown
    rows = funnel.rows
    if rows.empty:
        return words["none"] + unknown
    sentence = " ".join([_head(filter, len(rows), words), *_asked(filter, vocab, words)])
    sentence += "".join(", " + said(expr, vocab, lang) for _, expr in filter.clauses)
    details = _details(rows, words)
    return sentence + ("; " + ", ".join(details) if details else "") + "." + unknown


def _unknown_note(filter: Filter, words: dict) -> str:
    if not filter.ignored:
        return ""
    key = "unknown_one" if len(filter.ignored) == 1 else "unknown_many"
    return words[key].format(words=", ".join(f"« {w} »" for w in filter.ignored))


def _head(filter: Filter, n: int, words: dict) -> str:
    if filter.milestones:
        return words["milestone_one"] if n == 1 else words["milestone_many"].format(n=n)
    return words["one"] if n == 1 else words["many"].format(n=n)


def _asked(filter: Filter, vocab: Vocabulary, words: dict) -> list[str]:
    parts = [words["float"][c] for c in filter.categories if c in words["float"]]
    parts += [words["status"][st] for st in filter.status if st in words["status"]]
    parts += [words["loe"]] if filter.loe else []
    if filter.wbs_id in vocab.wbs:
        parts.append(words["in"].format(label=vocab.wbs[filter.wbs_id]))
    names = [vocab.resources[r][0] or vocab.resources[r][1] for r in sorted(filter.resources) if r in vocab.resources]
    parts += [words["resource"].format(name=", ".join(names))] if names else []
    return parts + ([words["named"].format(text=filter.search)] if filter.search else [])


def _details(rows: pd.DataFrame, words: dict) -> list[str]:
    details = []
    floats = rows["total_float_d"].dropna() if "total_float_d" in rows else pd.Series(dtype=float)
    if len(floats):
        worst = floats.idxmin()
        details.append(words["worst"].format(f=f"{floats[worst]:+.0f}", code=rows.loc[worst, "task_code"]))
    finishes = rows["finish"].dropna() if "finish" in rows else pd.Series(dtype="datetime64[ns]")
    if len(finishes):
        details.append(words["finish"].format(date=f"{finishes.max():%d/%m/%Y}"))
    return details


# --- a word the file and the lexicon do not hold -------------------------------------------

SUGGEST = 0.5  # difflib ratio from which a label is offered for an unknown word ("commiss" / "commissioning" = 0.7)


def suggestions(word: str, vocab: Vocabulary, limit: int = 3) -> list[tuple[str, str, float]]:
    """The labels of the file an unknown word may have meant: (kind, label, ratio), best first,
    over the WBS nodes (code, name, name words and their synonyms) and the resources; at most
    ``limit``, each at least SUGGEST. The page offers them as buttons; a click teaches the word."""
    word = fold(word)
    best: dict[tuple[str, str], float] = {}
    labels = [("wbs", label) for label in vocab.wbs.values()]
    labels += [("resource", short or name) for short, name in vocab.resources.values()]
    for kind, label in labels:
        ratio = max((difflib.SequenceMatcher(None, word, c).ratio() for c in _said_for(kind, label, vocab)), default=0)
        if ratio >= SUGGEST:
            best[(kind, label)] = max(best.get((kind, label), 0.0), ratio)
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0][1]))
    return [(kind, label, round(ratio, 2)) for (kind, label), ratio in ranked[:limit]]


def _said_for(kind: str, label: str, vocab: Vocabulary) -> list[str]:
    code, _, name = label.partition(" · ")
    said = [plain(code), plain(name)] if kind == "wbs" else [plain(label)]
    said += [w for w in re.split(r"[^a-z0-9]+", plain(name if kind == "wbs" else label)) if len(w) >= 4]
    return with_synonyms([w for w in said if w], vocab.lexicon)
