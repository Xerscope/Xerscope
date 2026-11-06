"""The Gantt Ask field's keyword grammar, scored on sentences with known filters (tests/ask/).

dev.toml holds the sentences the grammar was tuned on; heldout.toml the sentences written before
the grammar was run on them, never used to tune it. FLOORS records each set's share of sentences
whose every filter was right at the last measurement: a change that lowers one fails here, and a
change that raises one should raise the floor. The held-out misses are the synonyms the file does
not hold ("mécanique" for "Mechanical", "mise en service" for "Commissioning"): the model backend's
job, scored by `xerscope ask-bench --url`, never in this suite.

If a model is ever trained on a folder of real XER files, split by file (and by project), never by
sentence: two sentences on one file share its lexicon, and a sentence-level split leaks it. Keep the
held-out files untouched while tuning the prompt or the grammar, exactly as heldout.toml here.
"""

from pathlib import Path

import pandas as pd
import pytest

from xerscope.analysis import query
from xerscope.analysis.query import Vocabulary

ASK = Path(__file__).parent / "ask"
FLOORS = {"dev": 1.00, "heldout": 1.00}  # share of sentences with every filter right (ratios()["exact"])


@pytest.fixture(scope="module")
def lexicon(store):
    return query.vocabulary(store.latest)


@pytest.mark.parametrize("name", list(FLOORS))
def test_share_of_sentences_right_never_drops(lexicon, name):
    cases = query.load_cases(ASK / f"{name}.toml")
    assert len(cases) >= 20
    scored = query.score(cases, lexicon)
    assert set(scored["source"]) == {"keywords"}
    share = query.ratios(scored)["exact"]
    missed = scored.loc[~scored["exact"], "text"].tolist()
    assert share >= FLOORS[name], f"{name}: {share:.0%} < {FLOORS[name]:.0%}; missed {missed}"


def test_every_field_is_scored_and_a_wrong_expectation_is_an_error(lexicon):
    scored = query.score([{"text": "critical", "float": ["Critical"]}, {"text": "critical", "wbs": "CIV"}], lexicon)
    assert scored["exact"].tolist() == [True, False] and scored.loc[1, "wbs_id"] is not True
    assert set(query.ratios(scored)) == {"exact", *query.FIELDS}
    with pytest.raises(KeyError):
        query.expected_filter({"text": "x", "wbs": "NOPE"}, lexicon)
    with pytest.raises(KeyError):
        query.expected_filter({"text": "x", "resources": ["NOBODY"]}, lexicon)


def test_a_model_backend_is_scored_as_such(lexicon):
    answer = query.Filter(categories=("Critical",), source="model")
    scored = query.score([{"text": "late", "float": ["Critical"]}], lexicon, backend=lambda text, vocab: answer)
    assert scored["exact"].tolist() == [True] and scored["source"].tolist() == ["model"]


def test_confidence_buckets():
    scored = pd.DataFrame(
        {"exact": [True, True, False, True], "confidence": [1.0, 0.95, 0.85, 0.82]}, columns=["exact", "confidence"]
    )
    buckets = query.by_confidence(scored)
    assert buckets["sentences"].tolist() == [2, 2]
    assert buckets.loc["sure", "exact"] == 1.0 and buckets.loc["unsure", "exact"] == 0.5


def test_the_grammar_covers_the_whole_lexicon_of_the_demo(lexicon):
    """Every label of the loaded file, said by code, name, synonym, in both languages: 100 %. A
    file whose labels the grammar cannot name lists them, for a company's lexicon file."""
    scored, missed = query.coverage(lexicon)
    assert missed == [], missed
    labels = set(scored["label"])
    assert {"WBS CIV · Civil works", "resource CREW", "status Not started", "float Critical", "milestones"} <= labels
    assert len(scored) >= 40 and scored["exact"].all()


def test_coverage_names_what_a_file_needs_in_its_lexicon():
    vocab = Vocabulary(wbs={"h": "HVAC · HVAC works", "c": "CIV · Civil works"}, words=frozenset())
    scored, missed = query.coverage(vocab)
    assert missed == [] or missed == ["WBS HVAC · HVAC works"]  # "hvac" alone is a word the grammar reads as is
    with_company_word = Vocabulary(
        wbs=vocab.wbs, words=frozenset(), lexicon={**vocab.lexicon, "hvac": ("cvc",), "cvc": ("hvac",)}
    )
    assert query.parse_keywords("cvc", with_company_word).wbs_id == "h"
