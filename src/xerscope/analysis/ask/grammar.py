"""The grammar's words and the expression a sentence becomes.

Each phrase is folded (lower case, no accent) and tagged with its language ("en", "fr", or ""
for both), which ``answer.language`` counts. A phrase that holds a negation ("not started",
"non démarré") is a phrase, matched before the NOT operator (longest first).

    query   = conj ;
    conj    = disj , { [ AND ] , disj } ;      juxtaposition is AND
    disj    = unary , { OR , unary } ;         OR binds tighter than AND: "critical or complete
    unary   = NOT , unary | primary ;          in civil works" = (critical | complete) & CIV
    primary = "(" , conj , [ ")" ] | atom ;

Every atom is a set of activities (``funnel.mask``); NOT is the complement in the page's
population, OR the union, AND the intersection (docs/architecture.md, Ask)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ...xer.model import STATUS
from .text import tokens

STATUSES = list(STATUS.values())  # "Not started", "In progress", "Complete"
CATEGORIES = ["Critical", "Near critical", "Normal", "Complete"]  # viz.gantt.CATEGORY_ORDER (checked by a test)


@dataclass(frozen=True)
class Atom:
    """One set: ``kind`` (status, float, wbs, code, resource, milestone, loe, word, ...) and its value."""

    kind: str
    value: object = None


@dataclass(frozen=True)
class Not:
    item: Expr


@dataclass(frozen=True)
class And:
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[Expr, ...]


Expr = Atom | Not | And | Or
UNKNOWN = "unknown"  # an Atom of words nothing reads: never applied, named in Filter.ignored
# facets with one value per activity: atoms of one of them joined by AND are a union ("critical
# and near critical" lists both groups); milestone and LOE are one facet, the activity type
FACETS = {"status", "float", "wbs", "code", "resource", "id", "milestone", "loe"}


def _forms(stems: tuple[str, ...], ends: tuple[str, ...] = ("", "e", "es", "s"), before: str = "") -> list[str]:
    """French agreement: "termine", "terminee", "terminees", "termines"."""
    return [f"{before}{stem}{end}" for stem in stems for end in ends]


STATUS_PHRASES = {
    "Not started": {
        "en": ["not started", "unstarted", "to start", "upcoming"],
        "fr": [
            *_forms(("demarre", "commence"), before="non "),
            *_forms(("demarre", "commence"), before="pas "),
            "a demarrer",
            "a venir",
        ],
    },
    "In progress": {
        "en": ["in progress", "ongoing", "started", "active"],
        "fr": ["en cours", *_forms(("demarre", "commence")), "actives"],
    },
    "Complete": {
        "en": ["complete", "completed", "completes", "finished", "done"],
        "fr": [*_forms(("termine", "acheve", "finalise")), "fini", "finie", "finies", "finis"],
    },
}
# remaining work: not started or in progress (an activity in progress has work remaining)
OPEN_PHRASES = {
    "en": ["remaining", "incomplete", "unfinished", "open", "outstanding"],
    "fr": [*_forms(("restant", "inacheve", "ouvert"))],
}
CATEGORY_PHRASES = {
    "Near critical": {
        "en": ["near critical", "sub critical"],
        "fr": [f"{a} critique{s}" for a in ("quasi", "presque", "sous") for s in ("", "s")],
    },
    "Critical": {"en": ["critical", "critical path"], "fr": ["critique", "critiques", "chemin critique"]},
    "Normal": {"en": ["normal", "with float"], "fr": ["normale", "normales", "normaux", "avec marge"]},
}
# late = total float below zero (Oracle P6 help, Total Float, 47223: "a negative float indicates
# that the project is already behind schedule"); not Critical, which follows the project's
# critical path definition (formulas.md §1.2)
LATE_PHRASES = {
    "en": ["late", "behind", "behind schedule", "delayed"],
    "fr": ["en retard", "retard", "retards", *_forms(("retarde",))],
}
MILESTONE_PHRASES = {
    "en": ["milestone", "milestones", "event", "events"],
    "fr": ["jalon", "jalons", "evenement", "evenements"],
}
LOE_PHRASES = {"en": ["loe", "level of effort", "hammock", "hammocks"], "fr": ["niveau d effort", "hamac", "hamacs"]}
OPERATORS = {  # NOT, OR, AND: the words that join or negate what they stand next to
    "not": {
        "en": ["not", "no", "without", "except", "excluding", "neither", "nor"],
        "fr": ["non", "pas", "sans", "hors", "ni", "aucun", "aucune", "sauf"],
    },
    "or": {"en": ["or"], "fr": ["ou"]},
    "and": {"en": ["and", "but"], "fr": ["et", "mais"], "": [","]},
    "lp": {"": ["("]},
    "rp": {"": [")"]},
}

Entry = tuple[str, object, str]  # (kind: not/or/and/lp/rp/x, the expression for x, language)


def _entries() -> list[tuple[str, object, Mapping[str, list[str]]]]:
    entries: list[tuple[str, object, Mapping[str, list[str]]]] = [
        (op, None, phrases) for op, phrases in OPERATORS.items()
    ]
    entries += [("x", Atom("status", status), phrases) for status, phrases in STATUS_PHRASES.items()]
    entries.append(("x", Or((Atom("status", "Not started"), Atom("status", "In progress"))), OPEN_PHRASES))
    entries += [("x", Atom("float", category), phrases) for category, phrases in CATEGORY_PHRASES.items()]
    entries += [("x", Atom("late"), LATE_PHRASES), ("x", Atom("milestone"), MILESTONE_PHRASES)]
    entries.append(("x", Atom("loe"), LOE_PHRASES))
    return entries


def _table() -> dict[tuple[str, ...], Entry]:
    """phrase tokens -> (kind, expression, language): the grammar's whole vocabulary, one dict."""
    table: dict[tuple[str, ...], Entry] = {}
    for kind, expr, phrases in _entries():
        for lang, said in phrases.items():
            for phrase in said:
                table[tuple(tokens(phrase))] = (kind, expr, lang)
    return table


TABLE = _table()
LONGEST = max(len(key) for key in TABLE)
# the grammar's phrases of one and two words that name a set, for the typo pass
PHRASES_OF_SIZE = {
    size: sorted(" ".join(key) for key, entry in TABLE.items() if len(key) == size and entry[0] == "x")
    for size in (1, 2)
}
GRAMMAR_WORDS = frozenset(word for key in TABLE for word in key)
