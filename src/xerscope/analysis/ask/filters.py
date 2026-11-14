"""The Filter a sentence becomes, and its written forms: canonical (tests), label (chips),
said (the answer, in the question's language)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from ...xer.pmxml import CONSTRAINT_TYPE
from ..p6.check_schedule import P6_HARD_CONSTRAINTS
from .grammar import CATEGORIES, STATUSES, And, Atom, Expr, Not, Or
from .vocab import Vocabulary


@dataclass(frozen=True)
class Choice:
    """One answer to a question Ask asks back: ``word`` as the file spells it (a value, a type
    name), ``value`` what ``parse_keywords(..., chosen={word: value})`` takes back (a value's
    ``code_id``, or a type's label), ``label`` the text shown ("P1 — Phase (global)")."""

    word: str
    value: str
    label: str


@dataclass(frozen=True)
class Filter:
    """What a sentence asked for; every field empty means "no filter", as the page's widgets.

    The facets (one per widget of the page) are intersected; the values of one facet are
    united. ``clauses`` hold what the facets cannot say (NOT, OR across facets...)."""

    wbs_id: str | None = None
    status: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    code_type: str | None = None
    code_ids: frozenset[str] = frozenset()
    resources: frozenset[str] = frozenset()  # rsrc_id of the file's resources named in the sentence
    milestones: bool = False  # milestones only
    loe: bool = False  # level-of-effort activities only
    search: str = ""  # words each found in the Activity ID or name, in any order
    clauses: tuple[tuple[str, Expr], ...] = ()  # (label, expression), intersected with the facets
    matched: tuple[str, ...] = ()  # the phrases understood, in reading order, for the page's chips
    ignored: tuple[str, ...] = ()  # words nothing reads (the file, the lexicon, the grammar)
    # a word naming several activity-code values or types of one P6 name: filtered on none of
    # them, the candidates offered instead (``parse_keywords(..., chosen=...)`` takes the answer back)
    clarify: tuple[Choice, ...] = ()
    # 1.0 when every phrase matched exactly; else the weakest fuzzy match, lowered under SURE when
    # two WBS nodes scored as close (MARGIN): how well the sentence separates one cluster of the
    # file's labels from the others
    confidence: float = 1.0

    @property
    def empty(self) -> bool:
        facets = (self.wbs_id, self.status, self.categories, self.code_ids, self.resources, self.search)
        return not (any(facets) or self.milestones or self.loe or self.clauses)


def resource_name(rsrc_id: str, vocab: Vocabulary) -> str:
    short, name = vocab.resources.get(rsrc_id, ("", rsrc_id))
    return short or name


@dataclass
class _Facets:
    """The conjuncts of a sentence sorted into the page's facets, the rest into clauses."""

    vocab: Vocabulary
    fields: dict = field(default_factory=dict)
    matched: list[tuple[int, str]] = field(default_factory=list)
    clauses: list[tuple[str, Expr]] = field(default_factory=list)
    words: list[str] = field(default_factory=list)

    def add(self, position: int, expr: Expr) -> None:
        atoms = expr.items if isinstance(expr, Or) else (expr,)
        kinds = {a.kind if isinstance(a, Atom) else None for a in atoms}
        kind = kinds.pop() if len(kinds) == 1 else None
        handler = getattr(self, f"_{kind}", None) if kind else None
        if handler is None or not handler(position, [a.value for a in atoms]):
            label = say_label(expr, self.vocab)
            if label not in (c[0] for c in self.clauses):
                self.clauses.append((label, expr))
                self.matched.append((position, label))

    def _status(self, position: int, values: list) -> bool:
        return self._many("status", "Status", [s for s in STATUSES if s in values], position)

    def _float(self, position: int, values: list) -> bool:
        return self._many("categories", "Float", [c for c in CATEGORIES if c in values], position)

    def _many(self, name: str, title: str, values: list, position: int) -> bool:
        if name in self.fields:
            return False
        self.fields[name] = tuple(values)
        self.matched += [(position, f"{title}: {v}") for v in values]
        return True

    def _wbs(self, position: int, values: list) -> bool:
        if len(values) > 1 or "wbs_id" in self.fields:
            return False
        self.fields["wbs_id"] = values[0]
        self.matched.append((position, f"WBS: {self.vocab.wbs.get(values[0], values[0])}"))
        return True

    def _code(self, position: int, values: list) -> bool:
        if "code_ids" in self.fields:
            return False
        self.fields["code_ids"] = frozenset(values)
        self.fields["code_type"] = self.vocab.codes[values[0]][0]
        self.matched += [(position, f"{self.vocab.codes[c][0]}: {self.vocab.codes[c][1]}") for c in values]
        return True

    def _resource(self, position: int, values: list) -> bool:
        if "resources" in self.fields:
            return False
        self.fields["resources"] = frozenset(values)
        self.matched += [(position, f"Resource: {resource_name(r, self.vocab)}") for r in values]
        return True

    def _milestone(self, position: int, values: list) -> bool:
        return self._flag("milestones", "Milestones", values, position)

    def _loe(self, position: int, values: list) -> bool:
        return self._flag("loe", "Level of effort", values, position)

    def _flag(self, name: str, label: str, values: list, position: int) -> bool:
        if len(values) > 1:
            return False
        self.fields[name] = True
        self.matched.append((position, label))
        return True

    def _word(self, position: int, values: list) -> bool:
        if len(values) > 1:
            return False
        if not self.words:
            self.matched.append((position, "Search: "))
        if values[0] not in self.words:
            self.words.append(values[0])
        return True

    def filter(self, ignored: list[str], confidence: float) -> Filter:
        search = " ".join(self.words)
        matched = [m if m != "Search: " else f"Search: {search}" for _, m in sorted(self.matched, key=lambda pm: pm[0])]
        return Filter(
            **self.fields,
            search=search,
            clauses=tuple(self.clauses),
            matched=tuple(matched),
            ignored=tuple(ignored),
            confidence=round(confidence, 2),
        )


def to_filter(conjuncts: list[tuple[int, Expr]], ignored: list[str], confidence: float, vocab: Vocabulary) -> Filter:
    """The sentence's conjuncts as a Filter: one facet's positive atoms in its field, the rest as clauses."""
    facets = _Facets(vocab)
    for position, expr in conjuncts:
        facets.add(position, expr)
    return facets.filter(ignored, confidence)


def conjuncts(ask: Filter) -> list[Expr]:
    """The filter as the expressions it intersects: each facet (one value, or an OR of its
    values), each search word, each clause."""
    facets = [
        ("wbs", [ask.wbs_id] if ask.wbs_id else []),
        ("status", ask.status),
        ("float", ask.categories),
        ("code", sorted(ask.code_ids) if ask.code_type else []),
        ("resource", sorted(ask.resources)),
        ("milestone", [None] if ask.milestones else []),
        ("loe", [None] if ask.loe else []),
    ]
    out: list[Expr] = []
    for kind, values in facets:
        atoms = [Atom(kind, v) for v in values]
        if atoms:
            out.append(atoms[0] if len(atoms) == 1 else Or(tuple(atoms)))
    out += [Atom("word", w) for w in ask.search.split()]
    return out + [expr for _, expr in ask.clauses]


# --- written forms ----------------------------------------------------------------------------


def canonical(ask: Filter, vocab: Vocabulary) -> str:
    """The filter in one written form, for the tests' expectations: atoms ``status:Not started``,
    ``float:Critical``, ``wbs:CIV``, ``code:Zone=B2``, ``resource:CREW``, ``milestone``,
    ``loe``, ``word:pump``, ``late``...; ``!x``, ``(a | b)``, ``(a & b)``; children sorted;
    the conjuncts joined by `` & ``. "" is no ask."""
    return " & ".join(sorted(written(e, vocab) for e in conjuncts(ask)))


def written(expr: Expr, vocab: Vocabulary) -> str:
    """One expression in canonical form."""
    if isinstance(expr, Not):
        return "!" + written(expr.item, vocab)
    if isinstance(expr, And | Or):
        sign = " & " if isinstance(expr, And) else " | "
        return "(" + sign.join(sorted(written(e, vocab) for e in expr.items)) + ")"
    return _atom_written(expr, vocab)


def _atom_written(atom: Atom, vocab: Vocabulary) -> str:
    kind, value = atom.kind, atom.value
    if kind == "wbs":
        return "wbs:" + vocab.wbs.get(value, value).partition(" · ")[0]
    if kind == "code":
        code_type, code_value, _ = vocab.codes.get(value, ("?", value, ""))
        return f"code:{code_type}={code_value}"
    if kind == "resource":
        return "resource:" + resource_name(value, vocab)
    if kind == "cmp":
        measure, op, number, unit = value
        return f"{measure}{op}{number:g}{unit}"
    if kind == "date":
        column, low, high = value
        return f"{column}:[{_iso(low)},{_iso(high)})"
    return kind if value is None else f"{kind}:{value}"


def _iso(day) -> str:
    return "" if day is None else f"{day:%Y-%m-%d}"


# P6 Professional's hard set (Check Schedule, 101248) in P6's constraint names: "hard" differs
# between P6, P6 EPPM and DCMA (docs/standards.md), so the filter says which one it reads
_P6_NAME = {code: name for name, code in CONSTRAINT_TYPE.items()}
_P6_HARD = ", ".join(_P6_NAME[code] for code in P6_HARD_CONSTRAINTS)

SAY = {
    "en": {
        "status": {"Not started": "not started", "In progress": "in progress", "Complete": "complete"},
        "float": {
            "Critical": "critical",
            "Near critical": "near critical",
            "Normal": "with float",
            "Complete": "complete",
        },
        "wbs": "in {}",
        "resource": "with {}",
        "word": 'named "{}"',
        "milestone": "milestones",
        "loe": "level of effort",
        "late": "late (finish after baseline finish)",
        "id": "Activity ID {}",
        "constraint": {
            "any": "with a constraint",
            "hard": f"with a hard constraint (P6: {_P6_HARD})",
            "soft": "with a soft constraint",
        },
        "pred": "with a predecessor",
        "succ": "with a successor",
        "longest": "on the longest path",
        "without": {"constraint": "without constraint", "pred": "without predecessor", "succ": "without successor"},
        "measure": {"tf": "total float", "od": "original duration", "rd": "remaining duration", "pct": "% complete"},
        "unit": {"d": " d", "h": " h", "%": " %"},
        "column": {"start": "start", "finish": "finish", "active": "active"},
        "before": "before {}",
        "from": "from {}",
        "not": "not {}",
        "or": " or ",
        "and": " and ",
    },
    "fr": {
        "status": {"Not started": "non démarrée(s)", "In progress": "en cours", "Complete": "terminée(s)"},
        "float": {
            "Critical": "critique(s)",
            "Near critical": "quasi critique(s)",
            "Normal": "avec marge",
            "Complete": "terminée(s)",
        },
        "wbs": "dans {}",
        "resource": "avec {}",
        "word": "nommée(s) « {} »",
        "milestone": "jalons",
        "loe": "niveau d'effort",
        "late": "en retard (fin après la fin de référence)",
        "id": "activité {}",
        "constraint": {
            "any": "avec contrainte",
            "hard": f"avec contrainte dure (P6 : {_P6_HARD})",
            "soft": "avec contrainte souple",
        },
        "pred": "avec prédécesseur",
        "succ": "avec successeur",
        "longest": "sur le chemin le plus long",
        "without": {"constraint": "sans contrainte", "pred": "sans prédécesseur", "succ": "sans successeur"},
        "measure": {"tf": "marge totale", "od": "durée originale", "rd": "durée restante", "pct": "avancement"},
        "unit": {"d": " j", "h": " h", "%": " %"},
        "column": {"start": "début", "finish": "fin", "active": "en cours sur"},
        "before": "avant le {}",
        "from": "à partir du {}",
        "not": "non {}",
        "or": " ou ",
        "and": " et ",
    },
}


def said(expr: Expr, vocab: Vocabulary, lang: str = "en") -> str:
    """The expression in words, in ``lang`` ("en" or "fr"): the answer's words and, in English,
    a chip's label."""
    words = SAY["fr" if lang == "fr" else "en"]
    if _without(expr, words):
        return words["without"][expr.item.kind]
    if isinstance(expr, Not):
        inner = said(expr.item, vocab, lang)
        return words["not"].format(f"({inner})" if isinstance(expr.item, And | Or) else inner)
    if isinstance(expr, And | Or):
        sign = words["and"] if isinstance(expr, And) else words["or"]
        parts = (said(e, vocab, lang) for e in expr.items)
        return sign.join(f"({p})" if isinstance(e, And | Or) else p for e, p in zip(expr.items, parts, strict=True))
    return _say_atom(expr, vocab, words)


def _without(expr: Expr, words: dict) -> bool:
    """NOT on a predecessor, a successor or any constraint reads "without ..."."""
    item = expr.item if isinstance(expr, Not) else None
    return isinstance(item, Atom) and item.kind in words["without"] and item.value in (None, "any")


def _say_atom(atom: Atom, vocab: Vocabulary, words: dict) -> str:
    kind, value = atom.kind, atom.value
    if kind in ("status", "float"):
        return words[kind].get(value, value)
    if kind == "wbs":
        return words["wbs"].format(vocab.wbs.get(value, value))
    if kind == "code":
        code_type, code_value, _ = vocab.codes.get(value, ("", value, ""))
        return f"{code_type} {code_value}".strip()
    if kind == "resource":
        return words["resource"].format(resource_name(value, vocab))
    if kind in ("word", "id"):
        return words[kind].format(value)
    if kind == "constraint":
        return words["constraint"][value]
    if kind == "cmp":
        measure, op, number, unit = value
        return f"{words['measure'][measure]} {op} {number:g}{words['unit'][unit]}"
    if kind == "date":
        return _say_dates(value, words)
    return words.get(kind, kind)


def _say_dates(value, words: dict) -> str:
    """ "start 26/10/2026–01/11/2026", "finish before 01/01/2027", "start from 16/11/2026"."""
    column, low, high = value
    if low is not None and high is not None:
        span = f"{low:%d/%m/%Y}–{high - pd.Timedelta(days=1):%d/%m/%Y}"
    else:
        span = words["before"].format(f"{high:%d/%m/%Y}") if low is None else words["from"].format(f"{low:%d/%m/%Y}")
    return f"{words['column'][column]} {span}"


def say_label(expr: Expr, vocab: Vocabulary) -> str:
    """A clause's chip label: the expression in English, capitalised ("Not critical")."""
    text = said(expr, vocab, "en")
    return text[:1].upper() + text[1:]


# --- a chip taken off -------------------------------------------------------------------------


def without(ask: Filter, label: str, vocab: Vocabulary) -> Filter:
    """``ask`` less the one item ``label`` names, as ``Filter.matched`` spells it ("WBS: CIV ·
    Civil works", "Status: Not started", "Float: Critical", "Zone: B2", "Resource: CREW",
    "Milestones", "Level of effort", "Search: piping", or a clause's label "Not critical"): the
    chip a user takes off the page."""
    kind, _, value = label.partition(": ")
    if any(c[0] == label for c in ask.clauses):
        out = replace(ask, clauses=tuple(c for c in ask.clauses if c[0] != label))
    elif kind == ask.code_type and kind:  # "Zone: B2"
        kept = frozenset(c for c in ask.code_ids if vocab.codes.get(c, ("", "", ""))[1] != value)
        out = replace(ask, code_ids=kept, code_type=ask.code_type if kept else None)
    else:
        drop = _DROP.get(kind) or _DROP.get(label)
        out = drop(ask, value, vocab) if drop else ask
    return replace(out, matched=tuple(m for m in ask.matched if m != label)) if out != ask else ask


_DROP = {
    "WBS": lambda f, value, vocab: replace(f, wbs_id=None),
    "Status": lambda f, value, vocab: replace(f, status=tuple(s for s in f.status if s != value)),
    "Float": lambda f, value, vocab: replace(f, categories=tuple(c for c in f.categories if c != value)),
    "Resource": lambda f, value, vocab: replace(
        f, resources=frozenset(r for r in f.resources if resource_name(r, vocab) != value)
    ),
    "Milestones": lambda f, value, vocab: replace(f, milestones=False),
    "Level of effort": lambda f, value, vocab: replace(f, loe=False),
    "Search": lambda f, value, vocab: replace(f, search=""),
}
