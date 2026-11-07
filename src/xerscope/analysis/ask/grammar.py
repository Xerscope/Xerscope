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

# --- what a clause is made of (clauses.py composes them): measures, comparisons, units, dates ---
# total float (TF), original (OD) and remaining (RD) duration, % complete: compared in hours, a
# number of days being days of the activity's own calendar (hours_per_day)
MEASURES = {
    "tf": {"en": ["float", "total float", "tf"], "fr": ["marge", "marges", "marge totale"]},
    "od": {
        "en": ["duration", "durations", "original duration", "od"],
        "fr": [*_forms(("duree",), ("", "s")), "duree originale"],
    },
    "rd": {"en": ["remaining duration", "rd"], "fr": ["duree restante", "durees restantes"]},
    "pct": {
        "en": ["% complete", "percent complete", "pct"],
        "fr": ["avancement", "pourcentage", "pourcentage d avancement"],
    },
}
COMPARISONS = {
    "<": {
        "en": ["<", "less than", "lower than", "fewer than", "shorter than", "under", "below"],
        "fr": [
            *_forms(("inferieur",), before=""),
            *(f"{w} a" for w in _forms(("inferieur",))),
            "moins de",
            "moins que",
            "sous",
            "en dessous de",
        ],
    },
    ">": {
        "en": [">", "more than", "greater than", "higher than", "longer than", "over", "above", "exceeding"],
        "fr": [
            *_forms(("superieur",)),
            *(f"{w} a" for w in _forms(("superieur",))),
            "plus de",
            "plus que",
            "au dessus de",
        ],
    },
    "<=": {"en": ["<=", "at most", "maximum"], "fr": ["au plus", "au maximum"]},
    ">=": {"en": [">=", "at least", "minimum"], "fr": ["au moins"]},
    "=": {"en": ["=", "equal to", "equals"], "fr": ["egal a", "egale a", "egal", "egale"]},
}
SIGNS = {  # "marge nulle", "negative float": a comparison with zero
    "=": {"en": ["zero"], "fr": _forms(("nul",), ("", "le", "s", "les"))},
    "<": {"en": ["negative"], "fr": ["negatif", "negatifs", "negative", "negatives"]},
    ">": {"en": ["positive"], "fr": ["positif", "positifs", "positive", "positives"]},
}
UNITS = {
    "d": {
        "en": ["d", "day", "days", "wd", "working days", "work days"],
        "fr": ["j", "jour", "jours", "jo", "jours ouvres"],
    },
    "h": {"en": ["h", "hr", "hrs", "hour", "hours"], "fr": ["heure", "heures"]},
    "%": {"": ["%"], "en": ["percent"], "fr": ["pourcent", "pour cent"]},
    "week": {"en": ["week", "weeks", "month", "months"], "fr": ["semaine", "semaines", "mois"]},  # refused
}
ANCHORS = {  # which date a date expression reads: start, finish (none: the activity overlaps it)
    "start": {
        "en": ["start", "starts", "starting", "begin", "begins", "start date", "started"],
        "fr": [
            "commence",
            "commencent",
            "commencant",
            "debute",
            "debutent",
            "debutant",
            "demarre",
            "demarrent",
            "demarrant",
            "date de debut",
        ],
    },
    "finish": {
        "en": ["finish", "finishes", "finishing", "ends", "ending", "due", "finish date", "finished", "completed"],
        "fr": [
            "finit",
            "finissent",
            "finissant",
            "termine",
            "terminent",
            "terminant",
            "echeance",
            "date de fin",
            "fini",
        ],
    },
}
PREPOSITIONS = {
    "before": {"en": ["before"], "fr": ["avant", "avant le", "avant la"]},
    "after": {"en": ["after"], "fr": ["apres", "apres le", "apres la"]},
    "by": {
        "en": ["by", "until", "no later than"],
        "fr": ["d ici", "d ici le", "d ici la", "au plus tard", "au plus tard le", "jusqu au", "jusqu a"],
    },
    "since": {"en": ["since", "from"], "fr": ["depuis", "a partir du", "a partir de", "a compter du"]},
    "in": {"en": ["in", "on", "during"], "fr": ["en", "le", "pendant", "au cours de"]},
}
PERIODS = {  # (week or month, offset from the one holding the data date)
    ("week", 0): {"en": ["this week", "current week"], "fr": ["cette semaine", "semaine en cours"]},
    ("week", 1): {"en": ["next week"], "fr": ["semaine prochaine", "la semaine prochaine", "prochaine semaine"]},
    ("week", -1): {"en": ["last week", "previous week"], "fr": ["semaine derniere", "la semaine derniere"]},
    ("month", 0): {"en": ["this month", "current month"], "fr": ["ce mois", "ce mois ci", "mois en cours"]},
    ("month", 1): {"en": ["next month"], "fr": ["mois prochain", "le mois prochain"]},
    ("month", -1): {"en": ["last month", "previous month"], "fr": ["mois dernier", "le mois dernier"]},
}
MONTHS = {
    1: {"en": ["january", "jan"], "fr": ["janvier", "janv"]},
    2: {"en": ["february", "feb"], "fr": ["fevrier", "fevr", "fev"]},
    3: {"en": ["march"], "fr": ["mars"]},
    4: {"en": ["april", "apr"], "fr": ["avril", "avr"]},
    5: {"en": ["may"], "fr": ["mai"]},
    6: {"en": ["june", "jun"], "fr": ["juin"]},
    7: {"en": ["july", "jul"], "fr": ["juillet", "juil"]},
    8: {"en": ["august", "aug"], "fr": ["aout"]},
    9: {"en": ["september", "sep", "sept"], "fr": ["septembre"]},
    10: {"en": ["october", "oct"], "fr": ["octobre"]},
    11: {"en": ["november", "nov"], "fr": ["novembre"]},
    12: {"en": ["december", "dec"], "fr": ["decembre"]},
}
EDGES = {
    "end": {"en": ["end of", "the end of", "end"], "fr": ["fin", "fin de", "fin du", "la fin de", "la fin du"]},
    "begin": {"en": ["beginning of", "start of"], "fr": ["debut", "debut de", "debut du", "le debut de"]},
}
BETWEEN = {"en": ["between"], "fr": ["entre"]}
CONSTRAINTS = {  # P6 Professional sets (101248): see analysis/p6/check_schedule.py
    "any": {
        "en": ["constraint", "constraints", "constrained"],
        "fr": _forms(("contrainte", "contraint"), ("", "s", "e", "es")),
    },
    "hard": {
        "en": ["hard constraint", "hard constraints", "mandatory constraint", "mandatory constraints"],
        "fr": [
            f"{c} {a}"
            for c in ("contrainte", "contraintes")
            for a in ("dure", "dures", "forte", "fortes", "imperative", "imperatives")
        ],
    },
    "soft": {
        "en": ["soft constraint", "soft constraints"],
        "fr": [f"{c} {a}" for c in ("contrainte", "contraintes") for a in ("souple", "souples")],
    },
}
LOGIC = {
    "pred": {"en": ["predecessor", "predecessors"], "fr": ["predecesseur", "predecesseurs"]},
    "succ": {"en": ["successor", "successors"], "fr": ["successeur", "successeurs"]},
}
OPEN_ENDS = {
    "en": ["open end", "open ends", "open ended", "dangling"],
    "fr": ["extremite ouverte", "extremites ouvertes", "logique ouverte"],
}
LONGEST_PATH = {
    "en": ["longest path", "longest"],
    "fr": ["chemin le plus long", "plus long chemin", "le plus long chemin"],
}
# P6 Check Schedule "Long Durations" (101248): remaining duration over 352 h (LARGE_HOURS)
LONG_DURATIONS = {
    "en": ["long durations", "long duration", "large durations"],
    "fr": ["longues durees", "longue duree", "durees longues", "duree longue"],
}
LARGE_HOURS = 352.0

Entry = tuple[str, object, str]  # (kind: not/or/and/lp/rp/x or a clause part, its value, language)


def _entries() -> list[tuple[str, object, Mapping[str, list[str]]]]:
    entries: list[tuple[str, object, Mapping[str, list[str]]]] = [
        (op, None, phrases) for op, phrases in OPERATORS.items()
    ]
    entries += [("x", Atom("status", status), phrases) for status, phrases in STATUS_PHRASES.items()]
    entries.append(("x", Or((Atom("status", "Not started"), Atom("status", "In progress"))), OPEN_PHRASES))
    entries += [("x", Atom("float", category), phrases) for category, phrases in CATEGORY_PHRASES.items()]
    entries += [("x", Atom("late"), LATE_PHRASES), ("x", Atom("milestone"), MILESTONE_PHRASES)]
    entries.append(("x", Atom("loe"), LOE_PHRASES))
    entries += [("x", Atom("constraint", kind), phrases) for kind, phrases in CONSTRAINTS.items()]
    entries += [("x", Atom(kind), phrases) for kind, phrases in LOGIC.items()]
    entries.append(("x", Or((Not(Atom("pred")), Not(Atom("succ")))), OPEN_ENDS))
    entries.append(("x", Atom("longest"), LONGEST_PATH))
    entries.append(("x", Atom("cmp", ("rd", ">", LARGE_HOURS, "h")), LONG_DURATIONS))
    for kind, table in (("measure", MEASURES), ("cmp", COMPARISONS), ("sign", SIGNS), ("unit", UNITS)):
        entries += [(kind, value, phrases) for value, phrases in table.items()]
    for kind, table in (("prep", PREPOSITIONS), ("period", PERIODS), ("month", MONTHS), ("edge", EDGES)):
        entries += [(kind, value, phrases) for value, phrases in table.items()]
    entries.append(("between", None, BETWEEN))
    return entries + _anchors(entries)


def _anchors(entries) -> list:
    """A date anchor that is also a status word ("commence", "terminé", "started") falls back on
    the status when no date follows it."""
    status = {
        phrase: expr
        for kind, expr, phrases in entries
        if kind == "x"
        for said in phrases.values()
        for phrase in said
        if isinstance(expr, Atom) and expr.kind == "status"
    }
    return [
        ("anchor", (field, status.get(phrase)), {lang: [phrase]})
        for field, phrases in ANCHORS.items()
        for lang, said in phrases.items()
        for phrase in said
    ]


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
