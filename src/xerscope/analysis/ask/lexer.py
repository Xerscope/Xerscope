"""A sentence's tokens as items the parser reads: (token index, kind, payload).

Kinds: not, or, and, lp, rp (operators), x (an expression), u (a word nothing reads). The
grammar's phrases are matched first, longest first; then a typo on a grammar phrase; then the
file's own labels (WBS, activity codes, resources) and the words of its activity names."""

from __future__ import annotations

import bisect
import re

from .grammar import LONGEST, PHRASES_OF_SIZE, TABLE, And, Atom
from .text import MARGIN, STOP, SURE, closest, fold, phrase_pattern, plain, take, with_synonyms
from .vocab import Vocabulary

Item = tuple[int, str, object]


def items(tokens: list[str], vocab: Vocabulary) -> tuple[list[Item], float]:
    """Every token the grammar or the file reads, in sentence order, and the weakest typo ratio."""
    found, used = _grammar_items(tokens)
    confidence = _typo_items(tokens, used, found, vocab)
    rest = _Rest(tokens, used)
    confidence = min(confidence, _wbs_items(rest, vocab, found))
    _code_items(rest, vocab, found)
    confidence = min(confidence, _resource_items(rest, vocab, found), _word_items(rest, vocab, found))
    return sorted(found, key=lambda item: item[0]), confidence


def _grammar_items(tokens: list[str]) -> tuple[list[Item], set[int]]:
    """The grammar's phrases, longest first, left to right."""
    found: list[Item] = []
    used: set[int] = set()
    i = 0
    while i < len(tokens):
        size = next((n for n in range(min(LONGEST, len(tokens) - i), 0, -1) if tuple(tokens[i : i + n]) in TABLE), 0)
        if size:
            kind, expr, _ = TABLE[tuple(tokens[i : i + size])]
            found.append((i, kind, expr))
            used.update(range(i, i + size))
        i += max(size, 1)
    return found, used


def _typo_items(tokens: list[str], used: set[int], found: list[Item], vocab: Vocabulary) -> float:
    """A typo on a grammar phrase ("critque", "not strated"): a word nothing else reads, alone,
    with the next one, or with the NOT before it (the phrase "not started", not NOT "started")."""
    confidence = 1.0
    for i, token in enumerate(tokens):
        if i in used or not _typo_candidate(token, vocab):
            continue
        before = next((item for item in found if item[0] == i - 1 and item[1] == "not"), None)
        tries = [(i, f"{token} {tokens[i + 1]}")] if i + 1 < len(tokens) and i + 1 not in used else []
        tries += [(i - 1, f"{tokens[i - 1]} {token}")] if before else []
        tries.append((i, token))
        for start, said in tries:
            close = closest([said], PHRASES_OF_SIZE[len(said.split())], spaced=True)
            if close:
                if start < i:
                    found.remove(before)
                found.append((start, "x", TABLE[tuple(close[1].split())][1]))
                used.update(range(start, start + len(said.split())))
                confidence = min(confidence, close[2])
                break
    return confidence


def _typo_candidate(token: str, vocab: Vocabulary) -> bool:
    """A word a typo pass may read: not a stop word, not a word of the file, no digit."""
    return (
        len(token) >= 4
        and token not in STOP
        and not any(c.isdigit() for c in token)
        and not (vocab.words and token in vocab.words)
    )


class _Rest:
    """The tokens the grammar left, as one folded string: labels are matched on it as whole
    words and blanked once read; a position maps back to its token."""

    def __init__(self, tokens: list[str], used: set[int]):
        self.starts: list[int] = []
        shown: list[str] = []
        offset = 1
        for i, token in enumerate(tokens):
            self.starts.append(offset)
            shown.append(" " * len(token) if i in used else token)
            offset += len(token) + 1
        self.text = " " + " ".join(shown) + " "

    def index(self, position: int) -> int:
        return max(0, bisect.bisect_right(self.starts, position) - 1)

    def has(self, phrase: str) -> bool:
        return bool(phrase) and phrase_pattern([phrase]).search(self.text) is not None

    def take(self, phrase: str) -> int:
        """Blank the phrase; the token index of its first occurrence."""
        self.text, where = take(self.text, [phrase])
        return self.index(where[0])

    def unread(self, vocab: Vocabulary) -> list[str]:
        """The words a typo pass may read: never a word the file holds as is."""
        return [w for w in self.text.split() if w not in STOP and not (vocab.words and w in vocab.words)]


# --- WBS nodes ------------------------------------------------------------------------------


def _node_phrases(vocab: Vocabulary) -> tuple[dict[str, tuple[list[str], set[str]]], dict[tuple[str, str], str]]:
    """Per node, what a sentence may say for it (code, name, name words of 4+ letters, the
    node's own words, their synonyms) and what is said as the file spells it; and, for a node
    word that activities use, the file's word it stands for (the node and a search for it).
    A partial name word said by a synonym ("électricité"), the full name or the code: the node only."""
    phrases: dict[str, tuple[list[str], set[str]]] = {}
    stands_for: dict[tuple[str, str], str] = {}
    for wbs_id, label in vocab.wbs.items():
        code, _, name = label.partition(" · ")
        own = vocab.node_words.get(wbs_id, frozenset())
        words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 4 and w not in STOP] + sorted(own)
        for word in words:
            if word in own:
                for said in with_synonyms([word], vocab.lexicon):
                    stands_for.setdefault((wbs_id, plain(said)), word)
            elif vocab.words and word in vocab.words and word not in (plain(name), plain(code)):
                stands_for.setdefault((wbs_id, word), word)
        candidates = [plain(c) for c in with_synonyms([fold(code), fold(name), *words], vocab.lexicon)]
        phrases[wbs_id] = (candidates, {plain(c) for c in (fold(code), fold(name), *words)})
    return phrases, stands_for


def _wbs_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> float:
    """Every node named, longest phrase first ("MEC or COM"); none named: a typo on a node word."""
    phrases, stands_for = _node_phrases(vocab)

    def add(index: int, wbs_id: str, said: str) -> None:
        node, word = Atom("wbs", wbs_id), stands_for.get((wbs_id, said))
        found.append((index, "x", And((node, Atom("word", word))) if word else node))

    named = False
    while best := _longest_node(rest, phrases):
        add(rest.take(best[0]), best[1], best[0])
        named = True
    if named:
        return 1.0
    return _typo_node(rest, vocab, add)


def _longest_node(rest: _Rest, phrases: dict[str, tuple[list[str], set[str]]]) -> tuple[str, str] | None:
    """(phrase, node) of the longest node phrase in the text; at equal length a word of the
    file beats a synonym of another node."""
    best, best_rank = None, None
    for wbs_id, (candidates, direct) in phrases.items():
        for candidate in candidates:
            rank = (len(candidate), candidate in direct)
            if (best_rank is None or rank > best_rank) and rest.has(candidate):
                best, best_rank = (candidate, wbs_id), rank
    return best


def _typo_node(rest: _Rest, vocab: Vocabulary, add) -> float:
    """The closest node word to a sentence word, per node; unsure when two nodes score as close."""
    scores: dict[str, float] = {}
    best = None
    for wbs_id, label in vocab.wbs.items():
        code, _, name = label.partition(" · ")
        words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 5 and w not in STOP]
        words += sorted(vocab.node_words.get(wbs_id, ()))
        close = closest(rest.unread(vocab), with_synonyms([fold(code), *words], vocab.lexicon))
        if close:
            scores[wbs_id] = close[2]
            if best is None or close[2] > best[2]:
                best = (close[0], wbs_id, close[2], close[1])
    if best is None:
        return 1.0
    add(rest.take(best[0]), best[1], best[3])
    others = sorted((v for k, v in scores.items() if k != best[1]), reverse=True)
    return SURE - 0.01 if others and best[2] - others[0] < MARGIN else best[2]


# --- activity codes, resources, words -------------------------------------------------------


def _code_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> None:
    """A code value or its description, whole word, longest first. One code type, as the page's
    widget: a value of another type is understood and dropped, never searched as text; the
    type's own name ("zone B2") is dropped too."""
    code_type = None
    for code_id, (kind, value, name) in sorted(vocab.codes.items(), key=lambda kv: -max(len(kv[1][1]), len(kv[1][2]))):
        said = next((c for c in sorted((fold(value), fold(name)), key=len, reverse=True) if _label(c, rest)), None)
        if said is None:
            continue
        index = rest.take(said)
        if code_type in (None, kind):
            code_type = kind
            found.append((index, "x", Atom("code", code_id)))
    for kind in {t for t, _, _ in vocab.codes.values()}:
        if len(fold(kind)) >= 2 and rest.has(fold(kind)):
            rest.take(fold(kind))


def _label(candidate: str, rest: _Rest) -> bool:
    return len(candidate) >= 2 and candidate not in STOP and rest.has(candidate)


def _resource_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> float:
    """Resources by short name or name (or a synonym), whole word, longest first; none: a typo."""
    ranked = sorted(vocab.resources.items(), key=lambda kv: -max(len(kv[1][0]), len(kv[1][1])))
    named = False
    for rsrc_id, (short, name) in ranked:
        candidates = sorted(with_synonyms([fold(short), fold(name)], vocab.lexicon), key=len, reverse=True)
        said = next((c for c in candidates if _label(c, rest)), None)
        if said is not None:
            found.append((rest.take(said), "x", Atom("resource", rsrc_id)))
            named = True
    if named:
        return 1.0
    for rsrc_id, (short, name) in ranked:
        close = closest(rest.unread(vocab), with_synonyms([fold(short), fold(name)], vocab.lexicon))
        if close:
            found.append((rest.take(close[0]), "x", Atom("resource", rsrc_id)))
            return close[2]
    return 1.0


def _word_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> float:
    """What is left: a word of the Activity IDs and names (or its synonym, or a typo on one) is
    a search word; a word nothing holds is a ``u`` item; stop words drop."""
    confidence = 1.0
    for match in re.finditer(r"\S+", rest.text):
        word = match.group(0)
        if word in STOP or len(word) < 2:
            continue
        index = rest.index(match.start())
        if vocab.words is None:  # the file's words unknown: every word searched
            found.append((index, "x", Atom("word", word)))
            continue
        known = next((w for w in (word, *vocab.lexicon.get(word, ())) if w in vocab.words), None)
        if known is None and (close := closest([word], sorted(vocab.words))):
            known, confidence = close[1], min(confidence, close[2])
        found.append((index, "x", Atom("word", known)) if known else (index, "u", word))
    return confidence
