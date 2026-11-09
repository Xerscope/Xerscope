"""A sentence turned into the Gantt page's filters: "critical not started in civil works".

The page owns the filtering (WBS branch, status, float category, activity codes, resources,
milestones, level of effort, text).
This module only decides *which* filters a sentence asks for, so a number never comes from
here: a filter the parser picks is the one the user could have ticked by hand.

``parse`` tries the backend it is given (a local language model, step two of the feature,
absent by default) and always falls back on ``parse_keywords``, a bilingual (English /
French) phrase grammar over the file's own lexicon (``Vocabulary``: its WBS, activity-code
values, resources, and the words of its activity names). The page therefore never depends
on a model being up.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path

import pandas as pd

from ..xer import Snapshot
from ..xer.model import STATUS
from .populations import Funnel
from .wbs import ROOT

STATUSES = list(STATUS.values())  # "Not started", "In progress", "Complete"
CATEGORIES = ["Critical", "Near critical", "Normal", "Complete"]  # viz.gantt.CATEGORY_ORDER (checked by a test)


def fold(text) -> str:
    """Lower-case without accents, for matching: fold("Béton") == "beton"."""
    text = "" if text is None or (not isinstance(text, str) and pd.isna(text)) else str(text)
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


@dataclass(frozen=True)
class Filter:
    """What a sentence asked for; every field empty means "no filter", as the page's widgets."""

    wbs_id: str | None = None
    status: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    code_type: str | None = None
    code_ids: frozenset[str] = frozenset()
    resources: frozenset[str] = frozenset()  # rsrc_id of the file's resources named in the sentence
    milestones: bool = False  # milestones only
    loe: bool = False  # level-of-effort activities only
    search: str = ""
    matched: tuple[str, ...] = ()  # the phrases understood, in reading order, for the page's caption
    ignored: tuple[str, ...] = ()  # words the file's own lexicon does not hold, left out of the search
    source: str = "keywords"  # "keywords" (the grammar) or "model" (a Backend), for the page's caption
    # 1.0 when every phrase matched exactly; else the weakest fuzzy match, lowered under SURE when
    # two WBS nodes scored as close (MARGIN): how well the sentence separates one cluster of the
    # file's labels from the others
    confidence: float = 1.0

    @property
    def empty(self) -> bool:
        return not (
            self.wbs_id
            or self.status
            or self.categories
            or self.code_ids
            or self.resources
            or self.milestones
            or self.loe
            or self.search
        )


@dataclass(frozen=True)
class Vocabulary:
    """The names a sentence can refer to in one update: WBS nodes and activity-code values.

    Built once per update by ``vocabulary``; it is also the whole of what a model backend
    receives (no activity, no date, no number)."""

    wbs: Mapping[str, str]  # wbs_id -> "CIV · Civil works" (code and name)
    codes: Mapping[str, tuple[str, str, str]] = field(default_factory=dict)  # code_id -> (type, value, name)
    resources: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # rsrc_id -> (short name, name)
    # every folded word of the Activity IDs and names: a search word the file does not hold is
    # dropped (``Filter.ignored``) instead of emptying the chart; None = unknown, keep every word
    words: frozenset[str] | None = None
    has_milestones: bool = False
    has_loe: bool = False
    lexicon: Lexicon = field(default_factory=lambda: BUILTIN_LEXICON)  # trade words read as one (load_lexicon)
    # the file's own aliases, drawn at the file's load: the words of the activity names that appear
    # under ONE WBS node only ("foundations", "earthworks" -> Civil works; "piping" -> Mechanical &
    # electrical), wbs_id -> words. A word under several nodes names none of them (a search).
    node_words: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def to_prompt(self) -> dict:
        """The vocabulary as plain data, for a model prompt: the file's labels, not its activities."""
        return {
            "status": STATUSES,
            "float": CATEGORIES,
            "wbs": [{"id": k, "label": v} for k, v in self.wbs.items()],
            "codes": [{"id": k, "type": t, "value": v, "name": n} for k, (t, v, n) in self.codes.items()],
            "resources": [{"id": k, "short": short, "name": name} for k, (short, name) in self.resources.items()],
            "milestones": self.has_milestones,
            "loe": self.has_loe,
        }


Backend = Callable[[str, Vocabulary], Filter | None]
"""A parser that may decline (None): a model, step two; the keyword grammar is the fallback. A
model backend also carries ``warm(vocab)``: the vocabulary handed over once, at the file's load."""


def warm(backend: Backend | None, vocab: Vocabulary) -> bool:
    """``backend.warm(vocab)`` when the backend has one (a model), else False."""
    warmer = getattr(backend, "warm", None)
    return bool(warmer(vocab)) if callable(warmer) else False


def vocabulary(snapshot: Snapshot, nodes: pd.DataFrame | None = None, lexicon: Lexicon | None = None) -> Vocabulary:
    """``nodes`` is ``analysis.wbs.tree``/``rollup`` output (``wbs_id``, ``wbs_code``, ``wbs_name``);
    ``snapshot.wbs`` when not given. The project node and the synthetic root are left out.
    ``lexicon``: the packaged trade words by default (``load_lexicon`` adds a company's own)."""
    frame = snapshot.wbs if nodes is None else nodes
    codes_column = "wbs_code" if "wbs_code" in frame else "wbs_short_name"
    flags = frame["proj_node_flag"] if "proj_node_flag" in frame else pd.Series("N", index=frame.index)
    wbs = {}
    for wbs_id, code, name, flag in zip(frame["wbs_id"], frame[codes_column], frame["wbs_name"], flags, strict=True):
        if isinstance(wbs_id, str) and wbs_id and wbs_id != ROOT and flag != "Y":
            wbs[wbs_id] = " · ".join(s for s in (code, name) if isinstance(s, str) and s)
    codes = {}
    values = snapshot.code_values
    if not values.empty:
        for code_id, code_type, value, name in zip(
            values["code_id"], values["code_type"], values["value"], values["name"], strict=True
        ):
            codes[code_id] = (str(code_type), str(value), "" if pd.isna(name) else str(name))
    resources = {}
    assigned = snapshot.assignments
    if not assigned.empty and "rsrc_id" in assigned:
        named = assigned.dropna(subset=["rsrc_id"]).drop_duplicates("rsrc_id")
        for rsrc_id, short, name in zip(named["rsrc_id"], named["rsrc_short_name"], named["rsrc_name"], strict=True):
            if isinstance(rsrc_id, str) and rsrc_id:
                resources[rsrc_id] = tuple("" if pd.isna(s) else str(s) for s in (short, name))
    activities = snapshot.activities
    text = " ".join(activities["task_code"].astype(str)) + " " + " ".join(activities["task_name"].astype(str))
    words = frozenset(w for w in re.split(r"[^a-z0-9]+", fold(text)) if len(w) > 1)
    return Vocabulary(
        wbs=wbs,
        codes=codes,
        resources=resources,
        words=words,
        has_milestones=bool(activities["is_milestone"].any()),
        has_loe=bool(activities["is_loe"].any()),
        lexicon=BUILTIN_LEXICON if lexicon is None else lexicon,
        node_words=_node_words(activities, wbs, nodes, resources),
    )


def _node_words(
    activities: pd.DataFrame,
    wbs: Mapping[str, str],
    nodes: pd.DataFrame | None,
    resources: Mapping[str, tuple[str, str]],
) -> dict[str, frozenset[str]]:
    """The automatic lexicon: for each node, the words (4+ letters, no stop word, no node's own
    name word) of its activities' names that no other node's activities use. With ``nodes``
    (the tree, with ``ancestors``) an activity counts for every node above it, so a word
    specific to a branch names the branch; without it, for its own node only."""
    above: dict[str, list[str]] = {}
    if nodes is not None and "ancestors" in nodes:
        above = {
            wbs_id: [a for a in ancestors if a in wbs]
            for wbs_id, ancestors in zip(nodes["wbs_id"], nodes["ancestors"], strict=True)
        }
    name_words = {w for label in wbs.values() for w in re.split(r"[^a-z0-9]+", fold(label))}
    name_words |= {
        w for phrases in (*_STATUS_PHRASES.values(), *_CATEGORY_PHRASES.values()) for ph in phrases for w in ph.split()
    }
    name_words |= {w for short, name in resources.values() for w in re.split(r"[^a-z0-9]+", fold(f"{short} {name}"))}
    holders: dict[str, set[str]] = {}
    for wbs_id, name in zip(activities["wbs_id"], activities["task_name"], strict=True):
        if not isinstance(wbs_id, str):
            continue
        for word in set(re.split(r"[^a-z0-9]+", fold(name))):
            if len(word) >= 4 and word not in _STOP and word not in name_words and not word.isdigit():
                for node in above.get(wbs_id, [wbs_id] if wbs_id in wbs else []):
                    holders.setdefault(word, set()).add(node)
    result: dict[str, set[str]] = {}
    for word, owners in holders.items():
        # the deepest node holding the word alone: with the tree, a word under one leaf is held by
        # the leaf and every node above it; the leaf is the one with no other holder below it
        if len(owners) == 1:
            result.setdefault(next(iter(owners)), set()).add(word)
        elif above:
            leaves = [o for o in owners if not any(o in above.get(other, []) and other != o for other in owners)]
            if len(leaves) == 1:
                result.setdefault(leaves[0], set()).add(word)
    return {wbs_id: frozenset(words) for wbs_id, words in result.items()}


# phrases are matched longest first on the folded sentence, as whole words
_STATUS_PHRASES = {
    "Not started": [
        "not started",
        "non demarre",
        "non demarree",
        "non demarrees",
        "non demarres",
        "a demarrer",
        "pas commence",
        "pas commencee",
        "pas commencees",
        "pas commences",
        "non commence",
        "non commencee",
        "non commencees",
        "non commences",
        "unstarted",
        "to start",
        "a venir",
        "upcoming",
        "restant",
        "restantes",
        "restants",
        "remaining",
    ],
    "In progress": [
        "in progress",
        "en cours",
        "ongoing",
        "started",
        "demarre",
        "demarree",
        "demarrees",
        "demarres",
        "commence",
        "commencee",
        "commencees",
        "commences",
        "active",
        "actives",
    ],
    "Complete": [
        "complete",
        "completed",
        "completes",
        "terminee",
        "terminees",
        "termines",
        "termine",
        "achevee",
        "achevees",
        "acheves",
        "acheve",
        "finished",
        "fini",
        "finie",
        "finies",
        "finis",
        "done",
        "finalise",
        "finalisee",
        "finalisees",
        "finalises",
    ],
}
_CATEGORY_PHRASES = {
    "Near critical": [
        "near critical",
        "near-critical",
        "quasi critique",
        "quasi critiques",
        "quasi-critique",
        "quasi-critiques",
        "presque critique",
        "presque critiques",
        "sub critical",
        "sous critique",
        "sous critiques",
    ],
    "Critical": [
        "critical",
        "critique",
        "critiques",
        "chemin critique",
        "critical path",
        "float negatif",
        "negative float",
        "marge negative",
        "en retard",
        "late",
        "behind",
        "bloque",
        "bloquent",
        "bloquant",
        "bloquante",
        "bloquantes",
        "bloquants",
        "blocking",
        "blocks",
        "retard",
        "retards",
        "delayed",
    ],
    "Normal": [
        "normal",
        "normales",
        "normaux",
        "non critique",
        "non critiques",
        "not critical",
        "with float",
        "avec marge",
    ],
}
_MILESTONE_PHRASES = ["milestone", "milestones", "jalon", "jalons", "evenement", "evenements", "event", "events"]
_LOE_PHRASES = ["loe", "level of effort", "niveau d effort", "hamac", "hamacs", "hammock", "hammocks"]
# --- the lexicon: trade words read as one -----------------------------------------------

LEXICON_DIR = resources.files("xerscope") / "lexicon"  # the packaged groups (fr-en.toml)
Lexicon = dict[str, tuple[str, ...]]  # folded word -> the other words of its group


def load_lexicon(*dirs: str | Path) -> tuple[Lexicon, list[str]]:
    """The packaged groups plus every ``*.toml`` of ``dirs`` (a company's own words, the folder
    XERSCOPE_LEXICON names): ``[[group]] words = [...]`` tables, every word folded. Returns the
    lexicon and the load errors (a bad file is skipped and named, never fatal)."""
    groups: list[list[str]] = []
    errors: list[str] = []
    files = [entry for entry in sorted(LEXICON_DIR.iterdir(), key=lambda e: e.name) if entry.name.endswith(".toml")]
    for directory in dirs:
        root = Path(directory).expanduser()
        if root.is_dir():
            files += sorted(root.glob("*.toml"))
    for file in files:
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
            for table in data.get("group", []):
                words = [fold(w) for w in table.get("words", []) if isinstance(w, str) and fold(w)]
                if len(words) >= 2:
                    groups.append(words)
        except (OSError, tomllib.TOMLDecodeError, AttributeError, TypeError) as exc:
            errors.append(f"{file.name}: {exc}")
    lexicon: dict[str, list[str]] = {}
    for group in groups:
        for word in group:
            lexicon.setdefault(word, []).extend(w for w in group if w != word)
    return {word: tuple(dict.fromkeys(others)) for word, others in lexicon.items()}, errors


BUILTIN_LEXICON, _ = load_lexicon()


def _with_synonyms(words: list[str], lexicon: Lexicon) -> list[str]:
    """``words`` and, for each, the words of its group: what a sentence may say for it."""
    seen = dict.fromkeys(words)
    for word in words:
        seen.update(dict.fromkeys(lexicon.get(word, ())))
    return list(seen)


# words that carry no filter, dropped before the leftover becomes a text search
_STOP_WORDS = """
    a au aux avec ce ces cette d de des du en et l la le les ou pour qui que quoi sur un une tout toute
    tous toutes dans lot phase partie est sont ont c qu celles ceux montre montrer affiche afficher voir
    filtre filtrer activite activites tache taches noeud branche moi
    the an and or of in on for with all every any at to from by is are that which ones show list display
    filter task tasks activity activities wbs node branch me
    """
_STOP = frozenset(_STOP_WORDS.split())


FUZZY = 0.8  # difflib ratio under which two words are not the same word ("mecanque" / "mecanique" = 0.94)
MARGIN = 0.05  # a fuzzy WBS pick whose runner-up node scores within this is unsure (two clusters as close)
SURE = 0.9  # confidence at or above which the page shows no "unsure" mark


def _closest(words: list[str], phrases: list[str]) -> tuple[str, str, float] | None:
    """The sentence word closest to one of the phrases (single words of 5+ letters), with the
    ratio, when at least FUZZY; the fuzzy pass runs only where no phrase matched exactly, so a
    typo ("critque", "fondation" for "fondations") still finds its filter at a lower confidence."""
    import difflib

    best = None
    for word in words:
        if len(word) < 4:
            continue
        for phrase in phrases:
            if " " in phrase or len(phrase) < 5:
                continue
            ratio = difflib.SequenceMatcher(None, word, phrase).ratio()
            if ratio >= FUZZY and (best is None or ratio > best[2]):
                best = (word, phrase, ratio)
    return best


def _plain(text: str) -> str:
    """A label as the folded sentence spells it: letters and digits, single spaces ("Mechanical &
    electrical" -> "mechanical electrical")."""
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()


def _phrase_pattern(phrases: list[str]) -> re.Pattern:
    alternatives = sorted({fold(p) for p in phrases}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, alternatives)) + r")(?![a-z0-9])")


def _take(text: str, phrases: list[str]) -> tuple[str, list[int]]:
    """Blank every occurrence of the phrases in ``text``; where each was found, in order."""
    found: list[int] = []
    pattern = _phrase_pattern(phrases)

    def blank(match: re.Match) -> str:
        found.append(match.start())
        return " " * len(match.group(0))

    return pattern.sub(blank, text), found


def parse_keywords(text: str, vocab: Vocabulary) -> Filter:
    """Phrase grammar: status and float words, then a WBS node (code or name), then activity-code
    values, then what is left (minus stop words) as a text search. Negation is carried by the
    phrases themselves ("non démarré", "not critical"), longest match first."""
    folded = " " + re.sub(r"[^a-z0-9]+", " ", fold(text)) + " "
    if not folded.strip():
        return Filter()
    matched: list[tuple[int, str]] = []
    result = Filter()
    confidence = 1.0

    def record(position: int, label: str) -> None:
        matched.append((position, label))

    def sentence_words() -> list[str]:  # what a fuzzy pass may read: never a word the file holds as is
        return [w for w in folded.split() if w not in _STOP and not (vocab.words and w in vocab.words)]

    def negated(word: str) -> bool:
        return re.search(rf"(?<![a-z0-9])(not|non|pas|un)\s*{re.escape(word)}(?![a-z0-9])", folded) is not None

    # near-critical before critical: "quasi critique" must not leave "critique" to the next pass
    for category in ("Near critical", "Critical", "Normal"):
        folded, found = _take(folded, _CATEGORY_PHRASES[category])
        if found:
            result = replace(result, categories=(*result.categories, category))
            record(found[0], f"Float: {category}")
    if not result.categories:  # a typo on a float word
        for category in ("Near critical", "Critical", "Normal"):
            if close := _closest(sentence_words(), _CATEGORY_PHRASES[category]):
                folded, found = _take(folded, [close[0]])
                result = replace(result, categories=(category,))
                confidence = min(confidence, close[2])
                record(found[0], f"Float: {category}")
                break
    for status, phrases in _STATUS_PHRASES.items():
        folded, found = _take(folded, phrases)
        if found:
            result = replace(result, status=(*result.status, status))
            record(found[0], f"Status: {status}")
    if not result.status:  # a typo on a status word
        for status, phrases in _STATUS_PHRASES.items():
            if close := _closest(sentence_words(), phrases):
                # "not strated": the negation stays
                found_status = "Not started" if status == "In progress" and negated(close[0]) else status
                folded, found = _take(folded, [close[0]])
                result = replace(result, status=(found_status,))
                confidence = min(confidence, close[2])
                record(found[0], f"Status: {found_status}")
                break

    folded, found = _take(folded, _MILESTONE_PHRASES)
    if found:
        result = replace(result, milestones=True)
        record(found[0], "Milestones")
    folded, found = _take(folded, _LOE_PHRASES)
    if found:
        result = replace(result, loe=True)
        record(found[0], "Level of effort")

    # WBS: the longest node label (code, then name, then any word of the name of 4+ letters) found in the text
    best: tuple | None = None  # (phrase, wbs_id, label[, ratio])
    stands_for: dict[tuple[str, str], str] = {}  # (node, a node word or its synonym as said) -> the file's word
    searched: list[tuple[int, str]] = []  # (where it was said, the file's word a node phrase stood for)
    best_direct: set[str] = set()
    for wbs_id, label in vocab.wbs.items():
        code, _, name = label.partition(" · ")
        words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 4 and w not in _STOP]
        words += sorted(vocab.node_words.get(wbs_id, ()))  # the file's own aliases of the node
        candidates = [_plain(c) for c in _with_synonyms([fold(code), fold(name), *words], vocab.lexicon)]
        # an own word of the node (an activity word), said as is or by a synonym, and a partial
        # name word that activities use, said as is: the node and a search for the file's word.
        # A partial name word said by a synonym ("électricité"), the full name or the code: the
        # node only, the planner did not say the activity's word.
        own = vocab.node_words.get(wbs_id, frozenset())
        for word in words:
            if word in own:
                for said in _with_synonyms([word], vocab.lexicon):
                    stands_for.setdefault((wbs_id, _plain(said)), word)
            elif vocab.words and word in vocab.words and word not in (_plain(name), _plain(code)):
                stands_for.setdefault((wbs_id, word), word)
        direct = {_plain(c) for c in (fold(code), fold(name), *words)}  # said as the file spells it
        for candidate in candidates:
            if not candidate or not _phrase_pattern([candidate]).search(folded):
                continue
            # the longest phrase wins; at equal length a word of the file beats a synonym of another
            rank = (len(candidate), candidate in direct)
            if best is None or rank > (len(best[0]), best[0] in best_direct):
                best, best_direct = (candidate, wbs_id, label), direct
    scores: dict[str, float] = {}
    if best is None:  # no node named exactly: the closest node word to a sentence word, per node
        for wbs_id, label in vocab.wbs.items():
            code, _, name = label.partition(" · ")
            words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 5 and w not in _STOP]
            words += sorted(vocab.node_words.get(wbs_id, ()))
            close = _closest(sentence_words(), _with_synonyms([fold(code), *words], vocab.lexicon))
            if close:
                scores[wbs_id] = close[2]
                if best is None or close[2] > best[3]:
                    best = (close[0], wbs_id, label, close[2], close[1])
    if best:
        # a word of a node's name that also names activities of the file ("electrical", in
        # "Mechanical & electrical" and in "Electrical installation") is the node and a search
        # in it: the word stays in the sentence for the search step below
        folded, found = _take(folded, [best[0]])
        if len(best) > 3:  # a fuzzy pick: the sentence word it matched, not the candidate, was in the text
            candidate = best[4]  # the sentence word it matched, best[0], was in the text, not the candidate
            if (best[1], candidate) in stands_for:
                searched.append((found[0], stands_for[(best[1], candidate)]))
        elif (best[1], best[0]) in stands_for:
            searched.append((found[0], stands_for[(best[1], best[0])]))
        result = replace(result, wbs_id=best[1])
        if len(best) > 3:
            confidence = min(confidence, best[3])
            others = sorted((v for k, v in scores.items() if k != best[1]), reverse=True)
            if others and best[3] - others[0] < MARGIN:  # two nodes as close: the pick is a guess
                confidence = min(confidence, SURE - 0.01)
        record(found[0], f"WBS: {best[2]}")

    # activity codes: a value or a value name, whole word, longest first. One code type, as the
    # page's widget: a value of another type is understood and dropped, never searched as text.
    # The type's own name ("zone B2") is dropped too.
    by_length = sorted(vocab.codes.items(), key=lambda kv: -max(len(kv[1][1]), len(kv[1][2])))
    for code_id, (code_type, value, name) in by_length:
        for candidate in sorted((fold(value), fold(name)), key=len, reverse=True):
            if len(candidate) >= 2 and candidate not in _STOP and _phrase_pattern([candidate]).search(folded):
                folded, found = _take(folded, [candidate])
                if result.code_type in (None, code_type):
                    result = replace(result, code_type=code_type, code_ids=result.code_ids | {code_id})
                    record(found[0], f"{code_type}: {value}")
                break
    for code_type in {t for t, _, _ in vocab.codes.values()}:
        if len(fold(code_type)) >= 2:
            folded, _ = _take(folded, [fold(code_type)])

    # resources: short name or name, whole word, longest first
    by_length = sorted(vocab.resources.items(), key=lambda kv: -max(len(kv[1][0]), len(kv[1][1])))
    for rsrc_id, (short, name) in by_length:
        for candidate in sorted(_with_synonyms([fold(short), fold(name)], vocab.lexicon), key=len, reverse=True):
            if len(candidate) >= 2 and candidate not in _STOP and _phrase_pattern([candidate]).search(folded):
                folded, found = _take(folded, [candidate])
                result = replace(result, resources=result.resources | {rsrc_id})
                record(found[0], f"Resource: {short or name}")
                break

    if not result.resources:  # a typo on a resource name
        for rsrc_id, (short, name) in by_length:
            close = _closest(sentence_words(), _with_synonyms([fold(short), fold(name)], vocab.lexicon))
            if close:
                folded, found = _take(folded, [close[0]])
                result = replace(result, resources=frozenset({rsrc_id}))
                confidence = min(confidence, close[2])
                record(found[0], f"Resource: {short or name}")
                break

    # what is left is a text search, kept to the words the file holds (Activity IDs and names)
    rest = [w for w in folded.split() if w not in _STOP and len(w) > 1]
    if vocab.words is None:
        known, ignored = rest, ()
    else:  # a word the file does not hold, whose synonym it does, searches that synonym
        known, ignored = [], []
        for word in rest:
            match = next((w for w in (word, *vocab.lexicon.get(word, ())) if w in vocab.words), None)
            if match is None and (close := _closest([word], sorted(vocab.words))):  # a typo on a name word
                match, confidence = close[1], min(confidence, close[2])
            (known.append(match) if match else ignored.append(word))
        ignored = tuple(ignored)
    # a node's own word said (or its synonym) is searched too, every word in the sentence's order
    placed = [*searched, *((folded.find(w) if w in folded else fold(text).find(w), w) for w in known)]
    known = list(dict.fromkeys(w for _, w in sorted(placed)))
    if known:
        search = " ".join(known)
        result = replace(result, search=search)
        record(folded.find(known[0]), f"Search: {search}")
    return replace(
        result, matched=tuple(label for _, label in sorted(matched)), ignored=ignored, confidence=round(confidence, 2)
    )


def parse(text: str, vocab: Vocabulary, backend: Backend | None = None) -> Filter:
    """The backend's answer when it gives one, the keyword grammar otherwise (or when it fails)."""
    if backend is not None and text.strip():
        try:
            answer = backend(text, vocab)
        except Exception:  # a model down or slow must never break the page
            answer = None
        if answer is not None:
            return answer
    return parse_keywords(text, vocab)


# --- coverage of a file's own lexicon ------------------------------------------------------

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
    cases: list[dict] = []
    for label in vocab.wbs.values():
        code, _, name = label.partition(" · ")
        said = [code, name] if name else [code]
        for word in re.split(r"[^a-z0-9]+", fold(name)):
            if len(word) >= 4 and word not in _STOP:
                said += [w for w in vocab.lexicon.get(word, ()) if " " in w or len(w) >= 4]
        said += vocab.lexicon.get(fold(name), ())
        for text in dict.fromkeys(t for t in said if t):
            cases.append({"text": text, "wbs": code, "label": f"WBS {label}"})
        wbs_id = next(k for k, v in vocab.wbs.items() if v == label)
        for word in sorted(vocab.node_words.get(wbs_id, ()))[:5]:  # the file's own aliases: node and search
            cases.append({"text": word, "wbs": code, "search": word, "label": f"WBS {label} (own word {word})"})
    for short, name in vocab.resources.values():
        for text in dict.fromkeys(t for t in (short, name, *vocab.lexicon.get(fold(name), ())) if t):
            cases.append({"text": text, "resources": [short or name], "label": f"resource {short or name}"})
    for status in STATUSES:
        cases += [{"text": t, "status": [status], "label": f"status {status}"} for t in _SAID[status]]
    for category in CATEGORIES:
        if category != "Complete":
            cases += [{"text": t, "float": [category], "label": f"float {category}"} for t in _SAID[category]]
    if vocab.has_milestones:
        cases += [{"text": t, "milestones": True, "label": "milestones"} for t in ("milestones", "jalons")]
    if vocab.has_loe:
        cases += [{"text": t, "loe": True, "label": "level of effort"} for t in ("LOE", "hamacs")]
    return cases


def coverage(vocab: Vocabulary, backend: Backend | None = None) -> tuple[pd.DataFrame, list[str]]:
    """``score`` on ``self_cases``: the scored frame with each case's label, and the labels of
    the file no phrase reached (every one of a label's phrases right = covered)."""
    cases = self_cases(vocab)
    scored = score(cases, vocab, backend)
    scored["label"] = [case["label"] for case in cases]
    missed = sorted(set(scored.loc[~scored["exact"], "label"]))
    return scored, missed


# --- the filter as a population funnel ----------------------------------------------------


def apply(filter: Filter, tasks: pd.DataFrame, snapshot: Snapshot, nodes: pd.DataFrame | None = None) -> Funnel:
    """The sentence's filters as the steps of a ``Funnel`` over ``tasks`` (the page's frame, with
    its ``category`` column), one named step per filter understood, source ``ask``: a reader
    sees what each removed and how many are left, as under every check. ``nodes`` is the WBS
    tree (``analysis.wbs.tree``) for the branch step; without it a WBS filter is skipped."""
    from .wbs import subtree_ids

    funnel = Funnel(tasks, snapshot.data_date)
    if filter.wbs_id and nodes is not None and filter.wbs_id in set(nodes["wbs_id"]):
        label = nodes.loc[nodes["wbs_id"] == filter.wbs_id].iloc[0]
        branch = subtree_ids(nodes, filter.wbs_id)
        funnel.keep(f"WBS {label['wbs_code']} · {label['wbs_name']}", "ask", lambda rows: rows["wbs_id"].isin(branch))
    if filter.status:
        funnel.keep(f"status {' / '.join(filter.status)}", "ask", lambda rows: rows["status"].isin(filter.status))
    if filter.categories and "category" in tasks:
        funnel.keep(
            f"float {' / '.join(filter.categories)}", "ask", lambda rows: rows["category"].isin(filter.categories)
        )
    if filter.code_type and filter.code_ids:
        with_codes = snapshot.tasks_with_codes(filter.code_type, filter.code_ids)
        values = sorted(snapshot.code_values.loc[snapshot.code_values["code_id"].isin(filter.code_ids), "value"])
        funnel.keep(f"{filter.code_type} {' / '.join(values)}", "ask", lambda rows: rows["task_code"].isin(with_codes))
    if filter.resources:
        assigned = snapshot.assignments
        codes = set(assigned.loc[assigned["rsrc_id"].isin(filter.resources), "task_code"])
        names = sorted(assigned.loc[assigned["rsrc_id"].isin(filter.resources), "rsrc_short_name"].dropna().unique())
        funnel.keep(f"resource {' / '.join(map(str, names))}", "ask", lambda rows: rows["task_code"].isin(codes))
    if filter.milestones:
        funnel.keep("milestones", "ask", lambda rows: rows["is_milestone"])
    if filter.loe:
        funnel.keep("level of effort", "ask", lambda rows: rows["is_loe"])
    if filter.search:
        needle = fold(filter.search)
        funnel.keep(
            f'name contains "{filter.search}"',
            "ask",
            lambda rows: (
                rows["task_code"].map(fold).str.contains(needle, regex=False)
                | rows["task_name"].map(fold).str.contains(needle, regex=False)
            ),
        )
    return funnel


def funnel_line(funnel: Funnel) -> str:
    """ "212 → WBS CIV · Civil works 48 → status Not started 30 → float Critical 3": the population
    step by step, in one line, for the page's caption."""
    return " → ".join([str(funnel.start), *(f"{step.label} {step.left}" for step in funnel.steps)])


def without(filter: Filter, label: str, vocab: Vocabulary) -> Filter:
    """``filter`` less the one item ``label`` names, as ``Filter.matched`` spells it ("WBS: CIV ·
    Civil works", "Status: Not started", "Float: Critical", "Zone: B2", "Resource: CREW",
    "Milestones", "Level of effort", "Search: piping"): the chip a user takes off the page."""
    kind, _, value = label.partition(": ")
    if kind == "WBS":
        return replace(filter, wbs_id=None)
    if kind == "Status":
        return replace(filter, status=tuple(s for s in filter.status if s != value))
    if kind == "Float":
        return replace(filter, categories=tuple(c for c in filter.categories if c != value))
    if kind == "Resource":
        kept = frozenset(
            r
            for r in filter.resources
            if (vocab.resources.get(r, ("", ""))[0] or vocab.resources.get(r, ("", ""))[1]) != value
        )
        return replace(filter, resources=kept)
    if label == "Milestones":
        return replace(filter, milestones=False)
    if label == "Level of effort":
        return replace(filter, loe=False)
    if kind == "Search":
        return replace(filter, search="")
    if kind == filter.code_type:  # "Zone: B2"
        kept = frozenset(c for c in filter.code_ids if vocab.codes.get(c, ("", "", ""))[1] != value)
        return replace(filter, code_ids=kept, code_type=filter.code_type if kept else None)
    return filter


# --- a word the file and the lexicon do not hold -------------------------------------------

SUGGEST = 0.5  # difflib ratio from which a label is offered for an unknown word ("commiss" / "commissioning" = 0.7)


def suggestions(word: str, vocab: Vocabulary, limit: int = 3) -> list[tuple[str, str, float]]:
    """The labels of the file an unknown word may have meant: (kind, label, ratio), best first,
    over the WBS nodes (code, name, name words and their synonyms) and the resources; at most
    ``limit``, each at least SUGGEST. The page offers them as buttons; a click teaches the word."""
    import difflib

    word = fold(word)
    best: dict[tuple[str, str], float] = {}
    labels = [("wbs", label) for label in vocab.wbs.values()]
    labels += [("resource", short or name) for short, name in vocab.resources.values()]
    for kind, label in labels:
        code, _, name = label.partition(" · ")
        said = [_plain(code), _plain(name)] if kind == "wbs" else [_plain(label)]
        said += [w for w in re.split(r"[^a-z0-9]+", _plain(name if kind == "wbs" else label)) if len(w) >= 4]
        said = _with_synonyms([w for w in said if w], vocab.lexicon)
        ratio = max((difflib.SequenceMatcher(None, word, candidate).ratio() for candidate in said), default=0.0)
        if ratio >= SUGGEST:
            best[(kind, label)] = max(best.get((kind, label), 0.0), ratio)
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0][1]))
    return [(kind, label, round(ratio, 2)) for (kind, label), ratio in ranked[:limit]]


def learn(lexicon: Lexicon, word: str, label: str) -> Lexicon:
    """The lexicon with ``word`` read as ``label`` (a WBS label "CODE · name", or a resource name):
    one group of the word, the code and the name, so the grammar's node candidates reach it."""
    code, _, name = label.partition(" · ")
    group = [w for w in dict.fromkeys(_plain(t) for t in (word, code, name)) if w]
    merged = {k: list(v) for k, v in lexicon.items()}
    for member in group:
        merged.setdefault(member, []).extend(w for w in group if w != member and w not in merged.get(member, []))
    return {k: tuple(dict.fromkeys(v)) for k, v in merged.items()}


def learned_toml(pairs: list[tuple[str, str]]) -> str:
    """The words taught this session as a lexicon file (``[[group]] words = [...]``), to put in the
    folder XERSCOPE_LEXICON names so every session reads them."""
    lines = ["# Words taught in the Gantt Ask field: each read as the label it was matched to.", ""]
    for word, label in pairs:
        code, _, name = label.partition(" · ")
        words = list(dict.fromkeys(t for t in (word, code, name) if t))
        lines += ["[[group]]", "words = [" + ", ".join(json_quote(w) for w in words) + "]", ""]
    return "\n".join(lines)


def json_quote(text: str) -> str:
    import json

    return json.dumps(text, ensure_ascii=False)


# --- the answer, in words, from the funnel's rows ----------------------------------------

_FRENCH_WORDS = """
    le la les des du de un une en dans et ou pour sur avec non pas quasi critique critiques jalon jalons
    terminé terminée terminés démarré démarrée démarrés cours retard bloque lot chantier tâches activités
    fin début équipe fournisseur études achats mécanique électricité génie
    """
_FRENCH = frozenset(_FRENCH_WORDS.split())


def language(text: str) -> str:
    """ "fr" when the sentence reads as French (accents or French words), "en" otherwise."""
    words = set(re.split(r"[^a-zà-ÿ]+", text.lower()))
    return "fr" if any(c in "àâçéèêëîïôûùüÿ" for c in text) or len(words & _FRENCH) >= 1 else "en"


_WORDS = {
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
        "start": "earliest start {date}",
        "resource": "with {name}",
        "loe": "level of effort",
        "named": 'named "{text}"',
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
        "start": "premier début {date}",
        "resource": "avec {name}",
        "loe": "niveau d'effort",
        "named": "nommée(s) « {text} »",
    },
}


def answer(filter: Filter, funnel: Funnel, vocab: Vocabulary, lang: str = "en") -> str:
    """One sentence from the funnel's rows, in the language of the question: the count, what was
    asked (node, status, float, resource, milestones, LOE, search), then the worst total float
    and the latest finish of the rows. Every number is a column of the frame (``total_float_d``
    in working days, ``finish``); nothing is estimated. Empty rows: a sentence saying so."""
    words = _WORDS["fr" if lang == "fr" else "en"]
    rows = funnel.rows
    n = len(rows)
    if n == 0:
        return words["none"]
    if filter.milestones:
        head = words["milestone_one"] if n == 1 else words["milestone_many"].format(n=n)
    else:
        head = words["one"] if n == 1 else words["many"].format(n=n)
    parts = [head]
    parts += [words["float"][c] for c in filter.categories if c in words["float"]]
    parts += [words["status"][st] for st in filter.status if st in words["status"]]
    if filter.loe:
        parts.append(words["loe"])
    if filter.wbs_id and filter.wbs_id in vocab.wbs:
        parts.append(words["in"].format(label=vocab.wbs[filter.wbs_id]))
    if filter.resources:
        names = [
            vocab.resources[r][0] or vocab.resources[r][1] for r in sorted(filter.resources) if r in vocab.resources
        ]
        if names:
            parts.append(words["resource"].format(name=", ".join(names)))
    if filter.search:
        parts.append(words["named"].format(text=filter.search))
    sentence = " ".join(parts)
    details = []
    ranked = worst_float_first(rows)
    if len(ranked) and pd.notna(ranked["total_float_d"].iloc[0]):
        worst = ranked.iloc[0]
        details.append(words["worst"].format(f=f"{worst['total_float_d']:+.0f}", code=worst["task_code"]))
    finishes = rows["finish"].dropna() if "finish" in rows else pd.Series(dtype="datetime64[ns]")
    if len(finishes):
        details.append(words["finish"].format(date=f"{finishes.max():%d/%m/%Y}"))
    return sentence + (", " + ", ".join(details) if details else "") + "."


def worst_float_first(rows: pd.DataFrame) -> pd.DataFrame:
    """Rows by total float in hours, as P6 stores it (days of different calendars do not
    compare: -5 d of 10 h is -50 h, worse than -6 d of 8 h), then by Activity ID; no float
    (``total_float_d`` blank, as for complete work) last."""
    if "total_float_hr_cnt" not in rows or rows.empty:
        return rows
    hours = rows["total_float_hr_cnt"].where(rows["total_float_d"].notna())
    return rows.assign(_hours=hours).sort_values(["_hours", "task_code"], na_position="last").drop(columns="_hours")


# --- a summary of what came out, by a model, from computed values only ---------------------

FACT_ROWS = 10  # activities handed to a model for a summary: the worst floats first


def facts(funnel: Funnel, snapshot: Snapshot, limit: int = FACT_ROWS) -> dict:
    """What a model may read to summarise an answer: the funnel's steps and counts, the rows
    with the worst total float (Activity ID, float in working days, finish date), and the
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
    code_ids = frozenset(c for c in code_ids if vocab.codes[c][0] == code_type)
    status = tuple(s for s in STATUSES if s in _strings(data.get("status")))
    categories = tuple(c for c in CATEGORIES if c in _strings(data.get("float")))
    resources = frozenset(r for r in _strings(data.get("resource_ids")) if r in vocab.resources)
    search = data.get("search") if isinstance(data.get("search"), str) else ""
    matched = [f"WBS: {vocab.wbs[wbs_id]}"] if wbs_id else []
    matched += [f"Status: {s}" for s in status] + [f"Float: {c}" for c in categories]
    matched += [f"{code_type}: {vocab.codes[c][1]}" for c in sorted(code_ids)]
    matched += [f"Resource: {vocab.resources[r][0] or vocab.resources[r][1]}" for r in sorted(resources)]
    matched += ["Milestones"] * bool(data.get("milestones")) + ["Level of effort"] * bool(data.get("loe"))
    matched += [f"Search: {search.strip()}"] if search.strip() else []
    return Filter(
        wbs_id=wbs_id,
        status=status,
        categories=categories,
        code_type=code_type,
        code_ids=code_ids,
        resources=resources,
        milestones=bool(data.get("milestones")),
        loe=bool(data.get("loe")),
        search=search.strip(),
        matched=tuple(matched),
        source="model",
    )


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


# --- scoring a parser on sentences with known filters --------------------------------------

FIELDS = ("wbs_id", "status", "categories", "code_ids", "resources", "milestones", "loe", "search")


def load_cases(path) -> list[dict]:
    """Sentences with their expected filters, from a TOML file of ``[[case]]`` tables. Expected
    values name things as a planner would (a WBS code, a resource short name, ``"Zone:B2"`` for a
    code value) so a file of cases reads without ids; ``expected_filter`` resolves them."""
    import tomllib
    from pathlib import Path

    return list(tomllib.loads(Path(path).read_text(encoding="utf-8")).get("case", []))


def expected_filter(case: Mapping, vocab: Vocabulary) -> Filter:
    """The ``Filter`` a case expects, its names resolved against the vocabulary; a name the
    vocabulary does not hold raises, so a case cannot silently expect nothing."""
    by_code = {label.split(" · ")[0]: wbs_id for wbs_id, label in vocab.wbs.items()}
    wbs = case.get("wbs")
    if wbs is not None and wbs not in by_code:
        raise KeyError(f"WBS {wbs!r} is not in the file")
    code_ids, code_type = set(), None
    for item in case.get("codes", []):
        kind, _, value = item.partition(":")
        matches = [c for c, (t, v, _) in vocab.codes.items() if t == kind and v == value]
        if not matches:
            raise KeyError(f"code value {item!r} is not in the file")
        code_ids.add(matches[0])
        code_type = kind
    by_short = {short or name: rsrc_id for rsrc_id, (short, name) in vocab.resources.items()}
    for name in case.get("resources", []):
        if name not in by_short:
            raise KeyError(f"resource {name!r} is not in the file")
    return Filter(
        wbs_id=by_code.get(wbs) if wbs else None,
        status=tuple(s for s in STATUSES if s in case.get("status", [])),
        categories=tuple(c for c in CATEGORIES if c in case.get("float", [])),
        code_type=code_type,
        code_ids=frozenset(code_ids),
        resources=frozenset(by_short[n] for n in case.get("resources", [])),
        milestones=bool(case.get("milestones", False)),
        loe=bool(case.get("loe", False)),
        search=fold(case.get("search", "")),
    )


def score(cases: list[Mapping], vocab: Vocabulary, backend: Backend | None = None) -> pd.DataFrame:
    """One row per case: the sentence, whether every field matched (``exact``), one column per
    field (True when it matched) and the parser that answered. A ratio of a column is the share
    of cases it got right; ``exact`` is the share of sentences whose every filter was right."""
    rows = []
    for case in cases:
        expected = expected_filter(case, vocab)
        got = parse(case["text"], vocab, backend)
        fields = {name: getattr(got, name) == getattr(expected, name) for name in FIELDS}
        rows.append(
            {
                "text": case["text"],
                "exact": all(fields.values()),
                **fields,
                "source": got.source,
                "confidence": got.confidence,
            }
        )
    return pd.DataFrame(rows, columns=["text", "exact", *FIELDS, "source", "confidence"])


def ratios(scored: pd.DataFrame) -> dict[str, float]:
    """Share of cases right, overall (``exact``) and per field."""
    return {name: float(scored[name].mean()) if len(scored) else 0.0 for name in ("exact", *FIELDS)}


def by_confidence(scored: pd.DataFrame) -> pd.DataFrame:
    """Sentences and share right, for the confident answers (>= SURE) and the unsure ones: the
    confidence index is only worth showing if the unsure answers are indeed wrong more often."""
    sure = scored["confidence"] >= SURE
    return pd.DataFrame(
        {
            "sentences": [int(sure.sum()), int((~sure).sum())],
            "exact": [
                float(scored.loc[sure, "exact"].mean()) if sure.any() else float("nan"),
                float(scored.loc[~sure, "exact"].mean()) if (~sure).any() else float("nan"),
            ],
        },
        index=["sure", "unsure"],
    )
