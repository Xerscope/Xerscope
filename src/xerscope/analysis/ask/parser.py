"""Items to the sentence's conjuncts: a recursive-descent parser (grammar.py), then the unknown
words taken out and the exclusive facets united; ``parse_keywords`` returns the Filter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .filters import Choice, Filter, to_filter
from .grammar import FACETS, UNKNOWN, And, Atom, Expr, Not, Or
from .lexer import Item, items
from .text import fold, tokens
from .vocab import Vocabulary

MAX_CHARS = 300  # a sentence is read up to here; the rest is named as left out ("…")


def parse_keywords(text: str, vocab: Vocabulary, chosen: Mapping[str, str] | None = None) -> Filter:
    """The grammar over the file's lexicon: the sentence's conjuncts become the page's facets
    where one facet says them (status, float, WBS, codes, resources, milestones, LOE, search
    words) and ``clauses`` otherwise (NOT, OR across facets...). ``chosen``: the user's answers
    to a previous ``Filter.clarify``, {word: value}."""
    if not fold(text).strip():
        return Filter()
    conjuncts, ignored, confidence, clarify = sentence(text, vocab, chosen)
    return replace(to_filter(conjuncts, ignored, confidence, vocab), clarify=tuple(clarify))


def sentence(
    text: str, vocab: Vocabulary, chosen: Mapping[str, str] | None = None
) -> tuple[list[tuple[int, Expr]], list[str], float, list[Choice]]:
    """The sentence's conjuncts (position, expression) once simplified, the words nothing read
    (unknown, dangling operators, "…" for the part past MAX_CHARS), the reading's confidence and
    the questions asked back (``Filter.clarify``)."""
    found, confidence, clarify = items(tokens(text[:MAX_CHARS]), vocab, chosen)
    parsed = _Parser(found)
    conjuncts, ignored = parsed.top(), list(parsed.dangling)
    kept: list[tuple[int, Expr]] = []
    for position, expr in conjuncts:
        simple = simplify(expr, ignored, vocab)
        if _unknown(simple):
            ignored += list(simple.value)
        elif simple is not None:
            kept += [(position, part) for part in (simple.items if isinstance(simple, And) else (simple,))]
    if len(text) > MAX_CHARS:
        ignored.append("…")
    return unite(kept, vocab), list(dict.fromkeys(ignored)), confidence, clarify


class _Parser:
    """conj = disj {[AND] disj}; disj = unary {OR unary}; unary = NOT unary | primary;
    primary = "(" conj [")"] | atom. Each method returns (position, expression) or None."""

    def __init__(self, found: list[Item]):
        self.items = found
        self.at = 0
        self.dangling: list[str] = []  # operators with nothing to apply to

    def peek(self) -> str | None:
        return self.items[self.at][1] if self.at < len(self.items) else None

    def top(self) -> list[tuple[int, Expr]]:
        found: list[tuple[int, Expr]] = []
        while self.at < len(self.items):
            found += self.conj()
            if self.peek() == "rp":  # a stray ")" at the top
                self.at += 1
        return found

    def conj(self) -> list[tuple[int, Expr]]:
        found = []
        while self.peek() not in (None, "rp"):
            if self.peek() in ("and", "or"):  # "and" joins; an "or" with nothing before it dangles
                if self.peek() == "or":
                    self.dangling.append("or")
                self.at += 1
                continue
            part = self.disj()
            if part is not None:
                found.append(part)
        return found

    def disj(self) -> tuple[int, Expr] | None:
        first = self.unary()
        parts = [first] if first else []
        while self.peek() == "or":
            self.at += 1
            nxt = self.unary()
            parts += [nxt] if nxt else []
            if nxt is None:
                self.dangling.append("or")
        if not parts:
            return None
        return parts[0][0], parts[0][1] if len(parts) == 1 else Or(tuple(e for _, e in parts))

    def unary(self) -> tuple[int, Expr] | None:
        if self.peek() != "not":
            return self.primary()
        position = self.items[self.at][0]
        self.at += 1
        inner = self.unary()
        if inner is None:
            self.dangling.append("not")
            return None
        return position, Not(inner[1])

    def primary(self) -> tuple[int, Expr] | None:
        if self.peek() not in ("lp", "x", "u"):
            self.at += self.peek() == "rp"  # a stray ")" inside: skipped
            return None
        position, kind, payload = self.items[self.at]
        self.at += 1
        if kind == "x":
            return position, payload
        if kind == "u":
            return position, Atom(UNKNOWN, (payload,))
        inside = self.conj()
        self.at += self.peek() == "rp"
        return (inside[0][0], And(tuple(e for _, e in inside))) if inside else None


def simplify(expr: Expr | None, ignored: list[str], vocab: Vocabulary) -> Expr | None:
    """``expr`` with the unknown words taken out: an AND drops them (named in ``ignored``); NOT
    or an OR holding one is unknown as a whole, never applied (a superset, never the inverse);
    NOT NOT x is x; nested ANDs and ORs flatten; exclusive facets under one AND are united."""
    if isinstance(expr, Not):
        return _simplify_not(expr, ignored, vocab)
    if isinstance(expr, Or):
        return _simplify_or(expr, ignored, vocab)
    if isinstance(expr, And):
        return _simplify_and(expr, ignored, vocab)
    return expr


def _simplify_not(expr: Not, ignored: list[str], vocab: Vocabulary) -> Expr | None:
    inner = simplify(expr.item, ignored, vocab)
    if inner is None or _unknown(inner):
        return inner
    return inner.item if isinstance(inner, Not) else Not(inner)


def _simplify_or(expr: Or, ignored: list[str], vocab: Vocabulary) -> Expr | None:
    parts = [p for p in (simplify(item, ignored, vocab) for item in expr.items) if p is not None]
    unknown = [w for p in parts if _unknown(p) for w in p.value]
    if unknown:
        return Atom(UNKNOWN, tuple(unknown))
    flat = list(dict.fromkeys(q for p in parts for q in (p.items if isinstance(p, Or) else (p,))))
    return _one(flat, Or)


def _simplify_and(expr: And, ignored: list[str], vocab: Vocabulary) -> Expr | None:
    parts = [p for p in (simplify(item, ignored, vocab) for item in expr.items) if p is not None]
    ignored += [w for p in parts if _unknown(p) for w in p.value]
    flat = [q for p in parts if not _unknown(p) for q in (p.items if isinstance(p, And) else (p,))]
    return _one([e for _, e in unite([(0, e) for e in dict.fromkeys(flat)], vocab)], And)


def _one(parts: list[Expr], join) -> Expr | None:
    return None if not parts else parts[0] if len(parts) == 1 else join(tuple(parts))


def _unknown(expr: Expr | None) -> bool:
    return isinstance(expr, Atom) and expr.kind == UNKNOWN


def _facet(expr: Expr, vocab: Vocabulary) -> object:
    """The exclusive facet an atom, or an OR of atoms, belongs to; None otherwise."""
    atoms = expr.items if isinstance(expr, Or) else (expr,)
    if not all(isinstance(a, Atom) and a.kind in FACETS for a in atoms):
        return None
    keys = {_facet_key(a, vocab) for a in atoms}
    return keys.pop() if len(keys) == 1 else None


def _facet_key(atom: Atom, vocab: Vocabulary) -> object:
    if atom.kind == "code":  # one value per code type and activity
        return ("code", vocab.codes.get(atom.value, ("",))[0])
    return "type" if atom.kind in ("milestone", "loe") else atom.kind


def unite(parts: list[tuple[int, Expr]], vocab: Vocabulary) -> list[tuple[int, Expr]]:
    """Atoms (or ORs of atoms) of one exclusive facet joined by AND become one OR, at the
    position of the first: an activity has one status, one float category, one WBS node..."""
    out: list[tuple[int, Expr]] = []
    where: dict[object, int] = {}
    for position, part in parts:
        key = _facet(part, vocab)
        if key is None or key not in where:
            where.update({key: len(out)} if key is not None else {})
            out.append((position, part))
            continue
        first, held = out[where[key]]
        merged = [
            *(held.items if isinstance(held, Or) else (held,)),
            *(part.items if isinstance(part, Or) else (part,)),
        ]
        out[where[key]] = (first, Or(tuple(dict.fromkeys(merged))))
    return out
