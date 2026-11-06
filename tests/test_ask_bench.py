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

import pytest

from xerscope.analysis import query

ASK = Path(__file__).parent / "ask"
FLOORS = {"dev": 1.00, "heldout": 0.80}  # share of sentences with every filter right (ratios()["exact"])


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
