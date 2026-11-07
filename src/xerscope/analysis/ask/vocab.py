"""The names a sentence can refer to in one update: the file's own labels."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from ...xer import Snapshot
from ..wbs import ROOT
from .grammar import CATEGORIES, GRAMMAR_WORDS, STATUSES
from .lexicon import Lexicon
from .text import COMMON, STOP, tokens, words_of


@dataclass(frozen=True)
class Vocabulary:
    """WBS nodes, activity-code values, resources, the words of the activity names.

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
    lexicon: Lexicon = field(default_factory=dict)  # trade words read as one (load_lexicon)
    # the file's own aliases, drawn at the file's load: the words of the activity names that appear
    # under ONE WBS node only ("foundations", "earthworks" -> Civil works; "piping" -> Mechanical &
    # electrical), wbs_id -> words. A word under several nodes names none of them (a search).
    node_words: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # the Activity IDs holding a digit, as the sentence's tokens spell them -> the ID: an ID said
    # is that activity exactly ("C3020", never "C30201")
    ids: Mapping[tuple[str, ...], str] = field(default_factory=dict)
    data_date: pd.Timestamp | None = None  # what "this week", "next month" count from

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


def vocabulary(snapshot: Snapshot, nodes: pd.DataFrame | None = None, lexicon: Lexicon | None = None) -> Vocabulary:
    """``nodes`` is ``analysis.wbs.tree``/``rollup`` output (``wbs_id``, ``wbs_code``, ``wbs_name``);
    ``snapshot.wbs`` when not given. The project node and the synthetic root are left out.
    ``lexicon``: the company's trade words (``load_lexicon``), none by default."""
    wbs = wbs_labels(snapshot.wbs if nodes is None else nodes)
    resources = resource_names(snapshot)
    activities = snapshot.activities
    return Vocabulary(
        wbs=wbs,
        codes=code_values(snapshot),
        resources=resources,
        words=name_words(activities),
        has_milestones=bool(activities["is_milestone"].any()),
        has_loe=bool(activities["is_loe"].any()),
        lexicon={} if lexicon is None else lexicon,
        node_words=node_words(activities, wbs, nodes, resources),
        ids=activity_ids(activities),
        data_date=snapshot.data_date,
    )


def activity_ids(activities: pd.DataFrame) -> dict[tuple[str, ...], str]:
    """The Activity IDs that hold a digit, keyed by their tokens ("EL-100" -> ("el", "100"))."""
    codes = activities["task_code"].dropna().astype(str)
    return {tuple(tokens(code)): code for code in codes if any(c.isdigit() for c in code) and tokens(code)}


def wbs_labels(frame: pd.DataFrame) -> dict[str, str]:
    """wbs_id -> "CODE · name", the project node and the synthetic root left out."""
    codes_column = "wbs_code" if "wbs_code" in frame else "wbs_short_name"
    flags = frame["proj_node_flag"] if "proj_node_flag" in frame else pd.Series("N", index=frame.index)
    labels = {}
    for wbs_id, code, name, flag in zip(frame["wbs_id"], frame[codes_column], frame["wbs_name"], flags, strict=True):
        if isinstance(wbs_id, str) and wbs_id and wbs_id != ROOT and flag != "Y":
            labels[wbs_id] = " · ".join(s for s in (code, name) if isinstance(s, str) and s)
    return labels


def code_values(snapshot: Snapshot) -> dict[str, tuple[str, str, str]]:
    """code_id -> (type, value, description) of the file's activity codes."""
    values = snapshot.code_values
    if values.empty:
        return {}
    rows = zip(values["code_id"], values["code_type"], values["value"], values["name"], strict=True)
    return {code_id: (str(kind), str(value), "" if pd.isna(name) else str(name)) for code_id, kind, value, name in rows}


def resource_names(snapshot: Snapshot) -> dict[str, tuple[str, str]]:
    """rsrc_id -> (short name, name) of the resources assigned in the file."""
    assigned = snapshot.assignments
    if assigned.empty or "rsrc_id" not in assigned:
        return {}
    named = assigned.dropna(subset=["rsrc_id"]).drop_duplicates("rsrc_id")
    rows = zip(named["rsrc_id"], named["rsrc_short_name"], named["rsrc_name"], strict=True)
    return {
        rsrc_id: tuple("" if pd.isna(s) else str(s) for s in (short, name))
        for rsrc_id, short, name in rows
        if isinstance(rsrc_id, str) and rsrc_id
    }


def name_words(activities: pd.DataFrame) -> frozenset[str]:
    """Every folded word (2+ characters) of the Activity IDs and names."""
    text = " ".join(activities["task_code"].astype(str)) + " " + " ".join(activities["task_name"].astype(str))
    return frozenset(w for w in words_of(text) if len(w) > 1)


def node_words(
    activities: pd.DataFrame,
    wbs: Mapping[str, str],
    nodes: pd.DataFrame | None,
    resources: Mapping[str, tuple[str, str]],
) -> dict[str, frozenset[str]]:
    """The automatic lexicon: for each node, the words (4+ letters, no stop word, no grammar
    word, no node's or resource's name word) of its activities' names that no other node's
    activities use. With ``nodes`` (the tree, with ``ancestors``) an activity counts for every
    node above it, so a word specific to a branch names the branch; without it, its own node."""
    above = _above(wbs, nodes)
    reserved = _reserved(wbs, resources)
    holders: dict[str, set[str]] = {}
    for wbs_id, name in zip(activities["wbs_id"], activities["task_name"], strict=True):
        if not isinstance(wbs_id, str):
            continue
        for word in set(words_of(name)) - reserved:
            if len(word) >= 4 and not word.isdigit():
                for node in above.get(wbs_id, [wbs_id] if wbs_id in wbs else []):
                    holders.setdefault(word, set()).add(node)
    result: dict[str, set[str]] = {}
    for word, owners in holders.items():
        owner = _deepest(owners, above)
        if owner is not None:
            result.setdefault(owner, set()).add(word)
    return {wbs_id: frozenset(words) for wbs_id, words in result.items()}


def _above(wbs: Mapping[str, str], nodes: pd.DataFrame | None) -> dict[str, list[str]]:
    """wbs_id -> the node and the nodes above it (the tree's ``ancestors``); {} without the tree."""
    if nodes is None or "ancestors" not in nodes:
        return {}
    return {
        wbs_id: [a for a in ancestors if a in wbs]
        for wbs_id, ancestors in zip(nodes["wbs_id"], nodes["ancestors"], strict=True)
    }


def _reserved(wbs: Mapping[str, str], resources: Mapping[str, tuple[str, str]]) -> set[str]:
    """Words no node may take as its own: stop words, common words, the grammar's, the labels' own."""
    reserved = set(STOP) | set(GRAMMAR_WORDS) | set(COMMON)
    reserved |= {w for label in wbs.values() for w in words_of(label)}
    return reserved | {w for short, name in resources.values() for w in words_of(f"{short} {name}")}


def _deepest(owners: set[str], above: Mapping[str, list[str]]) -> str | None:
    """The deepest node holding the word alone: with the tree, a word under one leaf is held by
    the leaf and every node above it; the leaf is the one with no other holder below it."""
    if len(owners) == 1:
        return next(iter(owners))
    if not above:
        return None
    leaves = [o for o in owners if not any(o in above.get(other, []) and other != o for other in owners)]
    return leaves[0] if len(leaves) == 1 else None
