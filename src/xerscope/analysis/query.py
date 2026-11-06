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
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

import pandas as pd

from ..xer import Snapshot
from ..xer.model import STATUS
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
"""A parser that may decline (None): a model, step two; the keyword grammar is the fallback."""


def vocabulary(snapshot: Snapshot, nodes: pd.DataFrame | None = None) -> Vocabulary:
    """``nodes`` is ``analysis.wbs.tree``/``rollup`` output (``wbs_id``, ``wbs_code``, ``wbs_name``);
    ``snapshot.wbs`` when not given. The project node and the synthetic root are left out."""
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
    )


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
# words that carry no filter, dropped before the leftover becomes a text search
_STOP_WORDS = """
    a au aux avec ce ces cette d de des du en et l la le les ou pour qui que quoi sur un une tout toute
    tous toutes dans lot phase partie est sont ont c qu celles ceux montre montrer affiche afficher voir
    filtre filtrer activite activites tache taches noeud branche moi
    the an and or of in on for with all every any at to from by is are that which ones show list display
    filter task tasks activity activities wbs node branch me
    """
_STOP = frozenset(_STOP_WORDS.split())


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

    def record(position: int, label: str) -> None:
        matched.append((position, label))

    # near-critical before critical: "quasi critique" must not leave "critique" to the next pass
    for category in ("Near critical", "Critical", "Normal"):
        folded, found = _take(folded, _CATEGORY_PHRASES[category])
        if found:
            result = replace(result, categories=(*result.categories, category))
            record(found[0], f"Float: {category}")
    for status, phrases in _STATUS_PHRASES.items():
        folded, found = _take(folded, phrases)
        if found:
            result = replace(result, status=(*result.status, status))
            record(found[0], f"Status: {status}")

    folded, found = _take(folded, _MILESTONE_PHRASES)
    if found:
        result = replace(result, milestones=True)
        record(found[0], "Milestones")
    folded, found = _take(folded, _LOE_PHRASES)
    if found:
        result = replace(result, loe=True)
        record(found[0], "Level of effort")

    # WBS: the longest node label (code, then name, then any word of the name of 4+ letters) found in the text
    best: tuple[int, str, str] | None = None
    for wbs_id, label in vocab.wbs.items():
        code, _, name = label.partition(" · ")
        candidates = [fold(code), fold(name)]
        candidates += [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) >= 4 and w not in _STOP]
        for candidate in candidates:
            if (
                candidate
                and (best is None or len(candidate) > len(best[0]))
                and _phrase_pattern([candidate]).search(folded)
            ):
                best = (candidate, wbs_id, label)
    if best:
        folded, found = _take(folded, [best[0]])
        result = replace(result, wbs_id=best[1])
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
        for candidate in sorted((fold(short), fold(name)), key=len, reverse=True):
            if len(candidate) >= 2 and candidate not in _STOP and _phrase_pattern([candidate]).search(folded):
                folded, found = _take(folded, [candidate])
                result = replace(result, resources=result.resources | {rsrc_id})
                record(found[0], f"Resource: {short or name}")
                break

    # what is left is a text search, kept to the words the file holds (Activity IDs and names)
    rest = [w for w in folded.split() if w not in _STOP and len(w) > 1]
    known = rest if vocab.words is None else [w for w in rest if w in vocab.words]
    ignored = tuple(w for w in rest if w not in known)
    if known:
        search = " ".join(known)
        result = replace(result, search=search)
        record(folded.find(known[0]), f"Search: {search}")
    return replace(result, matched=tuple(label for _, label in sorted(matched)), ignored=ignored)


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


# --- a local language model as Backend (step two) ---------------------------------------

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


def llm_backend(url: str, timeout: float = 20.0) -> Backend:
    """A ``Backend`` on a llama.cpp server (OpenAI-compatible ``/v1/chat/completions``) at
    ``url``, answering with JSON constrained by the schema. The request carries the sentence and
    ``Vocabulary.to_prompt()`` only. Any failure (server down, slow, bad answer) is None, and the
    keyword grammar answers."""
    import json
    import urllib.request

    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"XERSCOPE_QUERY_URL must be an http(s) URL, not {url!r}")
    endpoint = url.rstrip("/") + "/v1/chat/completions"

    def ask(text: str, vocab: Vocabulary) -> Filter | None:
        body = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": _SYSTEM + json.dumps(vocab.to_prompt(), ensure_ascii=False)},
                    {"role": "user", "content": text},
                ],
                "response_format": {"type": "json_schema", "json_schema": {"name": "filter", "schema": _SCHEMA}},
                "temperature": 0,
            }
        ).encode()
        request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 # nosec B310 (http(s) checked above)
                answer = json.loads(response.read().decode())
            data = json.loads(answer["choices"][0]["message"]["content"])
        except Exception:  # noqa: BLE001  # whatever failed, the grammar answers
            return None
        return from_answer(data, vocab) if isinstance(data, dict) else None

    return ask
