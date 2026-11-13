"""A sentence's tokens as items the parser reads: (token index, kind, payload).

Kinds: not, or, and, lp, rp (operators), x (an expression), u (a word nothing reads). The
grammar's phrases are matched first, longest first; then a typo on a grammar phrase; then the
file's own labels (WBS, activity codes, resources) and the words of its activity names."""

from __future__ import annotations

import bisect
import re
from collections.abc import Mapping

from .clauses import Composer, raw
from .filters import Choice
from .grammar import LONGEST, PHRASES_OF_SIZE, TABLE, And, Atom
from .text import (
    MARGIN,
    MAX_FUZZY,
    STOP,
    SURE,
    closest,
    fold,
    phrase_pattern,
    plain,
    take,
    typo_word,
    with_synonyms,
)
from .text import index as word_index
from .vocab import NAME_COLUMN, RESOURCE_COLUMNS, WBS_COLUMNS, Vocabulary

Item = tuple[int, str, object]


def items(
    tokens: list[str], vocab: Vocabulary, chosen: Mapping[str, str] | None = None
) -> tuple[list[Item], float, list[Choice]]:
    """Every token the grammar or the file reads, in sentence order, the weakest typo ratio, and
    the questions asked back on activity codes (``_code_items``)."""
    found, used = _clause_items(tokens, vocab)
    _id_items(tokens, used, vocab, found)
    confidence = _typo_items(tokens, used, found, vocab)
    rest = _Rest(tokens, used)
    confidence = min(confidence, _wbs_items(rest, vocab, found))
    clarify = _code_items(rest, vocab, found, chosen or {})
    confidence = min(confidence, _resource_items(rest, vocab, found), _word_items(rest, vocab, found))
    return sorted(found, key=lambda item: item[0]), confidence, clarify


def _grammar_items(tokens: list[str]) -> tuple[list[tuple[int, int, str, object]], set[int]]:
    """The grammar's phrases, longest first, left to right: (index, size, kind, value)."""
    found: list[tuple[int, int, str, object]] = []
    used: set[int] = set()
    i = 0
    while i < len(tokens):
        size = next((n for n in range(min(LONGEST, len(tokens) - i), 0, -1) if tuple(tokens[i : i + n]) in TABLE), 0)
        if size:
            kind, value, _ = TABLE[tuple(tokens[i : i + size])]
            found.append((i, size, kind, value))
            used.update(range(i, i + size))
        i += max(size, 1)
    return found, used


def phrase_languages(tokens: list[str]) -> list[str]:
    """The language ("en", "fr") of each grammar phrase found in the tokens, neutral ones left out."""
    found, _ = _grammar_items(tokens)
    return [TABLE[tuple(tokens[i : i + size])][2] for i, size, _, _ in found if TABLE[tuple(tokens[i : i + size])][2]]


def _clause_items(tokens: list[str], vocab: Vocabulary) -> tuple[list[Item], set[int]]:
    """The grammar's phrases, with the clause parts (measures, comparisons, dates) composed."""
    found, used = _grammar_items(tokens)
    numbers = [(i, 1, *r) for i, token in enumerate(tokens) if i not in used and (r := raw(token))]
    composed, taken, freed = Composer(tokens, sorted(found + numbers), vocab.data_date).run()
    return composed, (used | taken) - freed


def _id_items(tokens: list[str], used: set[int], vocab: Vocabulary, found: list[Item]) -> None:
    """An Activity ID said as the file spells it: that activity, exactly."""
    longest = max((len(key) for key in vocab.ids), default=0)
    i = 0
    while i < len(tokens):
        size = next(
            (
                n
                for n in range(min(longest, len(tokens) - i), 0, -1)
                if tuple(tokens[i : i + n]) in vocab.ids and not used & set(range(i, i + n))
            ),
            0,
        )
        if size:
            found.append((i, "x", Atom("id", vocab.ids[tuple(tokens[i : i + size])])))
            used.update(range(i, i + size))
        i += max(size, 1)


def _typo_items(tokens: list[str], used: set[int], found: list[Item], vocab: Vocabulary) -> float:
    """A typo on a grammar phrase ("critque", "not strated"): a word nothing else reads, alone,
    with the next one, or with the NOT before it (the phrase "not started", not NOT "started")."""
    confidence, tries = 1.0, 0
    for i, token in enumerate(tokens):
        if i in used or not _typo_candidate(token, vocab) or tries >= MAX_FUZZY:
            continue
        tries += 1
        before = next((item for item in found if item[0] == i - 1 and item[1] == "not"), None)
        attempts = [(i, f"{token} {tokens[i + 1]}")] if i + 1 < len(tokens) and i + 1 not in used else []
        attempts += [(i - 1, f"{tokens[i - 1]} {token}")] if before else []
        attempts.append((i, token))
        for start, said in attempts:
            close = closest([said], PHRASES_OF_SIZE[len(said.split())], spaced=True)
            if close:
                if start < i:  # only the attempt that starts at the NOT before it, added when ``before`` is set
                    found.remove(before)  # type: ignore[arg-type]  # mypy cannot link ``start`` to ``before``
                found.append((start, "x", TABLE[tuple(close[1].split())][1]))
                used.update(range(start, start + len(said.split())))
                confidence = min(confidence, close[2])
                break
    return confidence


def _typo_candidate(token: str, vocab: Vocabulary) -> bool:
    """A word a typo pass may read: ``typo_word``, and not a word of the file as is."""
    return typo_word(token) and not (vocab.words and token in vocab.words)


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
        """The folded ``phrase`` in the text as whole words; a substring test first, so no regex
        is compiled for a phrase the text does not hold."""
        return bool(phrase) and phrase in self.text and phrase_pattern([phrase]).search(self.text) is not None

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
    synonyms, own_synonyms = vocab.synonyms(*WBS_COLUMNS), vocab.synonyms(NAME_COLUMN)
    for wbs_id, label in vocab.wbs.items():
        code, _, name = label.partition(" · ")
        own = vocab.node_words.get(wbs_id, frozenset())
        words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 4 and w not in STOP] + sorted(own)
        for word in words:
            if word in own:
                for said in with_synonyms([word], own_synonyms):
                    stands_for.setdefault((wbs_id, plain(said)), word)
            elif vocab.words and word in vocab.words and word not in (plain(name), plain(code)):
                stands_for.setdefault((wbs_id, word), word)
        candidates = [plain(c) for c in with_synonyms([fold(code), fold(name), *words], synonyms)]
        phrases[wbs_id] = (candidates, {plain(c) for c in (fold(code), fold(name), *words)})
    return phrases, stands_for


def _wbs_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> float:
    """Every node named, longest phrase first ("MEC or COM"); none named: a typo on a node word."""
    phrases, stands_for = _node_phrases(vocab)

    def add(index: int, wbs_id: str, said: str) -> None:
        node, word = Atom("wbs", wbs_id), stands_for.get((wbs_id, said))
        found.append((index, "x", And((node, Atom("word", word))) if word else node))

    held = _held_phrases(rest, phrases)
    named = False
    while best := next(((phrase, wbs_id) for phrase, wbs_id in held if rest.has(phrase)), None):
        add(rest.take(best[0]), best[1], best[0])
        named = True
    if named:
        return 1.0
    return _typo_node(rest, vocab, add)


def _held_phrases(rest: _Rest, phrases: dict[str, tuple[list[str], set[str]]]) -> list[tuple[str, str]]:
    """(phrase, node) of the node phrases the text holds, longest first; at equal length a word
    of the file before a synonym of another node, then in the file's order. Drawn once: taking a
    phrase only blanks the text, so a phrase absent now never appears later."""
    held = [
        (len(candidate), candidate in direct, candidate, wbs_id)
        for wbs_id, (candidates, direct) in phrases.items()
        for candidate in candidates
        if candidate and candidate in rest.text
    ]
    held.sort(key=lambda h: (-h[0], not h[1]))  # stable: the file's order at equal rank
    return [(candidate, wbs_id) for _, _, candidate, wbs_id in held]


def _typo_node(rest: _Rest, vocab: Vocabulary, add) -> float:
    """The closest node word to a sentence word, per node; unsure when two nodes score as close."""
    scores: dict[str, float] = {}
    best = None
    for wbs_id, label in vocab.wbs.items():
        code, _, name = label.partition(" · ")
        # the node's code, name words and own words: a common word is no typo candidate
        # (typo_word) and no own word (vocab._reserved), so "starting" never reads "setting"
        words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 5 and w not in STOP]
        words += sorted(vocab.node_words.get(wbs_id, ()))
        close = closest(rest.unread(vocab), with_synonyms([fold(code), *words], vocab.synonyms(*WBS_COLUMNS)))
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


def _code_items(rest: _Rest, vocab: Vocabulary, found: list[Item], chosen: Mapping[str, str]) -> list[Choice]:
    """A code value or its description, whole word, longest first. One code type, as the page's
    widget: a value of another type is understood and dropped, never searched as text; the
    type's own name ("zone B2") is dropped too. P6 keeps a type name unique only within its
    scope and a value unique only within its type: a word naming values of several types of one
    name ("P1" of "Phase (global)" and of "Phase (project)"), or a name two types share
    ("Phase"), filters nothing and is asked back (the list returned) until ``chosen`` answers.
    The same holds for a value under types of different names ("A" of "Zone" and of "Room"),
    unless the sentence names one of them ("Zone A"). A one-letter word is read only as a value
    exactly."""
    answers = {fold(word): value for word, value in chosen.items()}
    clarify: list[Choice] = []
    type_name = {t: vocab.type_names.get(t, t) for t, _, _ in vocab.codes.values()}
    reached: set[str] = set()  # the P6 type names a value word named, filtered or asked
    code_type = None

    def pick(code_id: str, index: int) -> None:
        nonlocal code_type
        if code_type in (None, vocab.codes[code_id][0]):
            code_type = vocab.codes[code_id][0]
            found.append((index, "x", Atom("code", code_id)))

    for _, (_, value, name) in sorted(vocab.codes.items(), key=lambda kv: -max(len(kv[1][1]), len(kv[1][2]))):
        said = next(
            (
                c
                for c in sorted((fold(value), fold(name)), key=len, reverse=True)
                if _label(c, rest) or (len(c) == 1 and c == fold(value) and rest.has(c))
            ),
            None,
        )
        if said is None:
            continue
        letter = len(said) == 1
        index = rest.take(said)
        same = [c for c, (_, v, n) in vocab.codes.items() if said == fold(v) or (not letter and said == fold(n))]
        types = {vocab.codes[c][0] for c in same}
        named = {t: [plain(n) for n in (t, type_name[t]) if len(plain(n)) >= 2] for t in types}
        typed = {t for t, names in named.items() if any(rest.has(n) for n in names)}
        if typed:  # "Zone A": the type said keeps its values only
            same = [c for c in same if vocab.codes[c][0] in typed]
            types = typed
        reached |= {type_name[t] for t in types}
        word = value if fold(value) == said else name
        if len(types) > 1:
            if answers.get(fold(word)) in same:
                pick(answers[fold(word)], index)
            else:
                clarify += [Choice(word, c, f"{vocab.codes[c][1]} — {vocab.codes[c][0]}") for c in same]
        else:
            pick(same[0], index)
    shared: dict[str, list[str]] = {}  # P6 type name -> its labels, when several types have it
    for label, name in type_name.items():
        shared.setdefault(name, []).append(label)
    for name, labels in shared.items():
        if len(labels) < 2 or name in reached or len(fold(name)) < 2 or not rest.has(fold(name)):
            continue
        index = rest.take(fold(name))
        answer = answers.get(fold(name))
        if answer in labels:  # the type picked: its values are asked next
            clarify += [Choice(name, c, f"{v} — {t}") for c, (t, v, _) in vocab.codes.items() if t == answer]
        elif answer in vocab.codes and vocab.codes[answer][0] in labels:  # type: ignore[index]  # None is in no dict
            pick(answer, index)  # type: ignore[arg-type]  # same test: ``answer`` is a key of vocab.codes
        else:
            clarify += [Choice(name, label, label) for label in labels]
    for kind in {*type_name, *type_name.values()}:
        if len(fold(kind)) >= 2 and rest.has(fold(kind)):
            rest.take(fold(kind))
    return clarify


def _label(candidate: str, rest: _Rest) -> bool:
    return len(candidate) >= 2 and candidate not in STOP and rest.has(candidate)


def _resource_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> float:
    """Resources by short name or name (or a synonym), whole word, longest first; none: a typo."""
    ranked = sorted(vocab.resources.items(), key=lambda kv: -max(len(kv[1][0]), len(kv[1][1])))
    synonyms = vocab.synonyms(*RESOURCE_COLUMNS)
    named = False
    for rsrc_id, (short, name) in ranked:
        candidates = sorted(with_synonyms([fold(short), fold(name)], synonyms), key=len, reverse=True)
        said = next((c for c in candidates if _label(c, rest)), None)
        if said is not None:
            found.append((rest.take(said), "x", Atom("resource", rsrc_id)))
            named = True
    if named:
        return 1.0
    for rsrc_id, (short, name) in ranked:
        close = closest(rest.unread(vocab), with_synonyms([fold(short), fold(name)], synonyms))
        if close:
            found.append((rest.take(close[0]), "x", Atom("resource", rsrc_id)))
            return close[2]
    return 1.0


def _word_items(rest: _Rest, vocab: Vocabulary, found: list[Item]) -> float:
    """What is left: a word of the Activity IDs and names (or its synonym, or a typo on one) is
    a search word; a word nothing holds is a ``u`` item; stop words drop."""
    confidence, tries = 1.0, 0
    synonyms = vocab.synonyms(NAME_COLUMN)
    for match in re.finditer(r"\S+", rest.text):
        word = match.group(0)
        if word in STOP or len(word) < 2:
            continue
        index = rest.index(match.start())
        if vocab.words is None:  # the file's words unknown: every word searched
            found.append((index, "x", Atom("word", word)))
            continue
        known = next((w for w in (word, *synonyms.get(word, ())) if w in vocab.words), None)
        if known is None and tries < MAX_FUZZY and typo_word(word):  # a typo on a name word, bounded
            tries += 1
            if close := closest([word], word_index(vocab.words)):
                known, confidence = close[1], min(confidence, close[2])
        found.append((index, "x", Atom("word", known)) if known else (index, "u", word))
    return confidence
