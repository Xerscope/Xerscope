"""The Gantt Ask field's keyword grammar, scored on sentences with known filters (tests/ask/).

dev.toml holds the sentences the grammar was tuned on; heldout.toml the sentences written before
the grammar was run on them, never used to tune it. FLOORS records each set's share of sentences
whose every filter was right at the last measurement: a change that lowers one fails here, and a
change that raises one should raise the floor. The held-out misses are the synonyms the file does
not hold ("mécanique" for "Mechanical", "mise en service" for "Commissioning"): a lexicon file's
job (XERSCOPE_LEXICON).

Keep heldout.toml untouched while tuning the grammar.
"""

from pathlib import Path

import pandas as pd
import pytest
from asklex import LEXICON

from xerscope.analysis import query
from xerscope.analysis.query import Vocabulary

ASK = Path(__file__).parent / "ask"
FLOORS = {"dev": 1.00, "heldout": 1.00}  # share of sentences with every filter right (ratios()["exact"])
# share of tests/ask/cases.toml understood exactly (query.understood): raise it when it goes up, never lower it
UNDERSTOOD = 1.00


@pytest.fixture(scope="module")
def lexicon(store):
    return query.vocabulary(store.latest, lexicon=LEXICON)


@pytest.mark.parametrize("name", list(FLOORS))
def test_share_of_sentences_right_never_drops(lexicon, name):
    cases = query.load_cases(ASK / f"{name}.toml")
    assert len(cases) >= 20
    scored = query.score(cases, lexicon)
    share = query.ratios(scored)["exact"]
    missed = scored.loc[~scored["exact"], "text"].tolist()
    assert share >= FLOORS[name], f"{name}: {share:.0%} < {FLOORS[name]:.0%}; missed {missed}"


@pytest.mark.oracle("property")
def test_share_of_the_grammar_cases_understood_never_drops(store):
    """tests/ask/cases.toml: FR and EN sentences (the audit's battery, negations, OR, IDs,
    comparisons, dates, constraints, logic, unknown words), each with its filter written by hand."""
    from xerscope.analysis import wbs

    snapshot = store.latest
    vocab = query.vocabulary(snapshot, wbs.tree(snapshot), LEXICON)
    cases = query.load_cases(ASK / "cases.toml")
    assert len(cases) >= 80
    scored = query.understood(cases, vocab)
    share = float(scored["exact"].mean())
    missed = [f"{r.text!r}: {r.got!r} != {r.expect!r}" for r in scored[~scored["exact"]].itertuples()]
    assert share >= UNDERSTOOD, f"{share:.0%} < {UNDERSTOOD:.0%}; missed {missed}"


@pytest.mark.oracle("property")
def test_the_words_a_case_names_as_ignored_are_compared_with_the_words_the_parser_drops(lexicon):
    """An operator with nothing to apply to is dropped and reported ("or", "not"): a case that
    names it is understood, a case that names another word or none is not."""
    named = query.understood([{"text": "critical or", "expect": "float:Critical", "ignored": ["or"]}], lexicon)
    assert named["exact"].tolist() == [True]
    assert [list(words) for words in named["ignored"]] == [["or"]]
    wrong = query.understood([{"text": "not", "expect": "", "ignored": []}], lexicon)
    assert wrong["exact"].tolist() == [False]
    assert [list(words) for words in wrong["ignored"]] == [["not"]]


@pytest.mark.oracle("property")
def test_every_field_is_scored_and_a_wrong_expectation_is_an_error(lexicon):
    scored = query.score([{"text": "critical", "float": ["Critical"]}, {"text": "critical", "wbs": "CIV"}], lexicon)
    assert scored["exact"].tolist() == [True, False]
    # Row 1 expects WBS CIV but "critical" names no WBS: only the wbs_id field is wrong (hand reading).
    assert scored["wbs_id"].tolist() == [True, False]
    assert scored["categories"].tolist() == [True, False]  # row 1 sets no float filter, "critical" reads as Critical
    assert query.ratios(scored)["wbs_id"] == 0.5
    assert query.ratios(scored)["exact"] == 0.5
    assert (scored["exact"] == scored[list(query.FIELDS)].all(axis=1)).all()
    assert set(query.ratios(scored)) == {"exact", *query.FIELDS}
    with pytest.raises(KeyError):
        query.expected_filter({"text": "x", "wbs": "NOPE"}, lexicon)
    with pytest.raises(KeyError):
        query.expected_filter({"text": "x", "resources": ["NOBODY"]}, lexicon)


def test_confidence_buckets():
    scored = pd.DataFrame(
        {"exact": [True, True, False, True], "confidence": [1.0, 0.95, 0.85, 0.82]}, columns=["exact", "confidence"]
    )
    buckets = query.by_confidence(scored)
    assert buckets["sentences"].tolist() == [2, 2]
    assert buckets.loc["sure", "exact"] == 1.0 and buckets.loc["unsure", "exact"] == 0.5


@pytest.mark.oracle("property")
def test_the_grammar_covers_the_whole_lexicon_of_the_demo(lexicon):
    """Every label of the loaded file, said by code, name, synonym, in both languages: 100 %. A
    file whose labels the grammar cannot name lists them, for a company's lexicon file."""
    scored, missed = query.coverage(lexicon)
    assert missed == [], missed
    labels = set(scored["label"])
    assert {"WBS CIV · Civil works", "resource CREW", "status Not started", "float Critical", "milestones"} <= labels
    assert len(scored) >= 40 and scored["exact"].all()
    # Phrases written from tests/asklex.py (synonym groups, accents folded), not from bench.self_cases:
    # a WBS is said by its code, its name and each long synonym of the words of its name.
    texts = scored.groupby("label")["text"].apply(set)
    assert {"CIV", "Civil works", "genie civil", "civils"} <= texts["WBS CIV · Civil works"]
    assert {"COM", "Commissioning", "mise en service", "essais"} <= texts["WBS COM · Commissioning"]
    assert {"PRC", "Procurement", "achats", "approvisionnement", "purchasing"} <= texts["WBS PRC · Procurement"]


@pytest.mark.oracle("property")
def test_coverage_names_what_a_file_needs_in_its_lexicon():
    vocab = Vocabulary(wbs={"h": "HVAC · HVAC works", "c": "CIV · Civil works"}, words=frozenset())
    scored, missed = query.coverage(vocab)
    assert missed == []
    # "Complete" is the status Complete for the grammar, so a WBS titled "Complete" cannot be named: it is missed.
    done = Vocabulary(wbs={"a": "DONE · Complete"}, words=frozenset())
    done_scored, done_missed = query.coverage(done)
    assert done_missed == ["WBS DONE · Complete"]
    assert not done_scored.loc[done_scored["label"] == "WBS DONE · Complete", "exact"].any()
    assert done_scored.loc[done_scored["label"] != "WBS DONE · Complete", "exact"].all()
    with_company_word = Vocabulary(
        wbs=vocab.wbs, words=frozenset(), lexicon={**vocab.lexicon, "hvac": ("cvc",), "cvc": ("hvac",)}
    )
    assert query.parse_keywords("cvc", with_company_word).wbs_id == "h"
