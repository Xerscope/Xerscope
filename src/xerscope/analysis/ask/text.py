"""Matching text the way a planner types it: folded, whole words, a typo at most."""

from __future__ import annotations

import difflib
import functools
import re
import unicodedata
from collections.abc import Mapping

import pandas as pd

# A typo is read only between a word of 5+ letters, no digit, and a name or grammar phrase of
# 5+ letters starting with the same letter, at a difflib ratio of FUZZY or more ("mecanque" /
# "mecanique" = 0.94; "starting" / "setting" = 0.80, refused). At most MAX_FUZZY words of a
# sentence are tried per pass, each against the names of close length only: no pass grows as
# unknown words x the file's words.
FUZZY = 0.85
MAX_FUZZY = 5
MARGIN = 0.05  # a fuzzy WBS pick whose runner-up node scores within this is unsure (two clusters as close)
SURE = 0.9  # confidence at or above which the page shows no "unsure" mark

# words that carry no filter, dropped before the leftover becomes a text search. "tâche",
# "task", "activité" do not filter the activity type: milestones stay in "tâches critiques".
_STOP_WORDS = """
    a au aux avec ce ces cette d de des du en l la le les pour qui que quoi sur un une tout toute
    tous toutes dans lot phase partie est sont ont c qu celles ceux montre montrer affiche afficher voir
    filtre filtrer activite activites tache taches noeud branche moi
    the an of in on for with all every any at to from by is are that which ones show list display
    filter task tasks activity activities wbs node branch me
    """
STOP = frozenset(_STOP_WORDS.split())

_LEXEME = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}"  # 2026-12-31
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"  # 31/12, 31/12/2026
    r"|[a-z0-9]+(?:[.,]\d+)?"  # words, Activity IDs, numbers (10, 10.5, 10,5)
    r"|<=|>=|[<>=%(),]"
)


def fold(text) -> str:
    """Lower-case without accents, for matching: fold("Béton") == "beton"."""
    text = "" if text is None or (not isinstance(text, str) and pd.isna(text)) else str(text)
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def plain(text: str) -> str:
    """A label as the folded sentence spells it: letters and digits, single spaces ("Mechanical &
    electrical" -> "mechanical electrical")."""
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()


def words_of(text: str) -> list[str]:
    """The folded words (letters and digits) of a text."""
    return [w for w in re.split(r"[^a-z0-9]+", fold(text)) if w]


_WITH_UNIT = re.compile(r"(\d+(?:[.,]\d+)?)(d|j|h|hr|hrs|jo|wd)")


def tokens(text: str) -> list[str]:
    """The folded sentence as tokens: words, numbers, dates, comparison signs, parentheses; a
    number glued to its unit ("10d", "8h") is two tokens."""
    found = []
    for token in _LEXEME.findall(fold(text).replace("≤", "<=").replace("≥", ">=")):
        glued = _WITH_UNIT.fullmatch(token)
        found += list(glued.groups()) if glued else [token]
    return found


def phrase_pattern(phrases: list[str]) -> re.Pattern:
    alternatives = sorted({fold(p) for p in phrases}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, alternatives)) + r")(?![a-z0-9])")


def take(text: str, phrases: list[str]) -> tuple[str, list[int]]:
    """Blank every occurrence of the phrases in ``text``; where each was found, in order."""
    found: list[int] = []

    def blank(match: re.Match) -> str:
        found.append(match.start())
        return " " * len(match.group(0))

    return phrase_pattern(phrases).sub(blank, text), found


# common words a typo pass never reads as a label ("long" is not "Long-lead", "next" not "nest")
_COMMON_WORDS = """
    next this last long short week weeks month start starting end ending time first early high low big small
    new old more less what which when where how why who need want give make take see get set week today
    prochain prochaine dernier derniere semaine mois debut fin long longue court courte tous quand quel quelle
    """
COMMON = frozenset(_COMMON_WORDS.split())


def typo_word(word: str) -> bool:
    """A word a typo pass may read: 5+ letters, no digit (never an Activity ID: "A1000" is not
    "A1001"), not a stop word nor a common word."""
    return len(word) >= 5 and not any(c.isdigit() for c in word) and word not in STOP and word not in COMMON


def closest(words: list[str], phrases: list[str], spaced: bool = False) -> tuple[str, str, float] | None:
    """The word closest to one of the phrases (5+ letters, same first letter, length within 2;
    single words unless ``spaced``), with the ratio, when at least FUZZY: a typo ("critque",
    "fondation") still finds its phrase, at a lower confidence. The first MAX_FUZZY words only."""
    best = None
    for word in [w for w in words if typo_word(w.split()[-1])][:MAX_FUZZY]:  # the typo is in the last word
        candidates = [p for p in _near(phrases, word) if spaced or " " not in p]
        for phrase in difflib.get_close_matches(word, candidates, n=1, cutoff=FUZZY):
            ratio = difflib.SequenceMatcher(None, word, phrase).ratio()
            if best is None or ratio > best[2]:
                best = (word, phrase, ratio)
    return best


def _near(phrases, word: str) -> list[str]:
    """The phrases a typo on ``word`` may stand for: same first letter, length within 2, 5+ letters."""
    if isinstance(phrases, Index):
        return phrases.near(word)
    return [p for p in phrases if len(p) >= 5 and p[:1] == word[:1] and abs(len(p) - len(word)) <= 2]


@functools.lru_cache(maxsize=4)
def index(words: frozenset[str]) -> Index:
    """The ``Index`` of a vocabulary's words, built once per vocabulary."""
    return Index(words)


class Index:
    """A file's words by first letter and length, built once: a typo looks at a handful of them."""

    def __init__(self, words) -> None:
        self.buckets: dict[tuple[str, int], list[str]] = {}
        for word in sorted(words):
            if len(word) >= 5:
                self.buckets.setdefault((word[0], len(word)), []).append(word)

    def near(self, word: str) -> list[str]:
        return [w for n in range(len(word) - 2, len(word) + 3) for w in self.buckets.get((word[:1], n), [])]


def with_synonyms(words: list[str], lexicon: Mapping[str, tuple[str, ...]]) -> list[str]:
    """``words`` and, for each, the words of its group: what a sentence may say for it."""
    seen = dict.fromkeys(words)
    for word in words:
        seen.update(dict.fromkeys(lexicon.get(word, ())))
    return list(seen)
