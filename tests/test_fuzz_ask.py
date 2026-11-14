"""Fuzzing the Ask field of the Gantt: any sentence gives a filter and an answer, never a crash.

The sentence is what a user types. It is read (``parse_keywords``), applied to the rows
(``apply``) and answered (``answer``), as the Gantt page does; the page shows a message for one
failure only, a sentence nested past the recursive parser (RecursionError). The property, over
sentences made of the grammar's own phrases, words and Task IDs of the demo series, numbers, dates
(possible or not), operators, parentheses and arbitrary text: the three calls return, or the first
raises RecursionError.

Measured on 1000 sentences: 62 % have a part understood, 43 % give a clause, 81 % narrow the rows.
None makes Ask ask a question back (the demo file has no ambiguous code): the answers to such a
question are held by tests/test_ask_ambiguous_codes_blind.py and
tests/test_ask_value_two_types_blind.py, not here.

``HYPOTHESIS_PROFILE=ci`` runs 1000 examples instead of 200 (tests/conftest.py).
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from xerscope.analysis import query
from xerscope.analysis import wbs as wbs_tree
from xerscope.analysis.ask.filters import Filter
from xerscope.analysis.ask.grammar import TABLE
from xerscope.viz import categorise

PHRASES = sorted({" ".join(words) for words in TABLE})
NOISE = ["(", ")", "((", "))", ">", "<", ">=", "=", "-", "+", "10", "0", "-5", "10j", "5 days", "3 semaines",
         "12/03", "31/02/2026", "2026-13-40", "99/99", "et", "ou", "and", "or", "not", "sans", "pas", ",", ";",
         "'", '"', "%", "é", "\u2028", "\x00", "entre", "between", "avant", "après", "before", "after"]  # fmt: skip


@pytest.fixture(scope="module")
def page(store):
    """What the Gantt page hands to Ask for the latest update of the demo series."""
    snapshot = store.latest
    nodes = wbs_tree.tree(snapshot)
    tasks = snapshot.activities.assign(category=categorise(snapshot.activities))
    return snapshot, nodes, tasks, query.vocabulary(snapshot, nodes)


@pytest.fixture(scope="module")
def file_words(store) -> list[str]:
    """The words of the task names and the Task IDs of the same update: what a user would type."""
    tasks = store.latest.activities
    return sorted({word for name in tasks["task_name"] for word in str(name).split()} | set(tasks["task_code"]))


def sentences(file_words: list[str]):
    """Up to nine tokens joined by spaces (a phrase of the grammar, a word of the file, noise, a few
    arbitrary characters), or sixty arbitrary characters."""
    token = st.one_of(
        st.sampled_from(PHRASES), st.sampled_from(file_words), st.sampled_from(NOISE), st.text(max_size=6)
    )
    return st.one_of(st.lists(token, max_size=9).map(" ".join), st.text(max_size=60))


def read_and_answer(sentence: str, page) -> Filter | None:
    """The three calls of the Gantt page, in its order. Returns the filter read, or None when the
    sentence nests too deep to be read (the one failure the page shows a message for)."""
    snapshot, nodes, tasks, vocabulary = page
    try:
        ask = query.parse_keywords(sentence, vocabulary)
    except RecursionError:
        return None
    assert isinstance(ask, Filter)
    funnel = query.apply(ask, tasks, snapshot, nodes, None)
    assert len(funnel.rows) <= len(tasks)  # a filter never adds a row
    assert isinstance(query.answer(ask, funnel, vocabulary, query.language(sentence)), str)
    return ask


@pytest.mark.oracle("property")
@given(data=st.data())
def test_any_sentence_is_read_applied_and_answered(data, page, file_words):
    # the sentence is drawn here, not in @given: its words come from the demo file, a fixture
    read_and_answer(data.draw(sentences(file_words)), page)


def test_every_phrase_of_the_grammar_alone_is_read_applied_and_answered(page):
    """Each phrase once, on its own: no kind of filter is left to the luck of the draw above (a
    filter that few phrases give, level of effort for one, comes up in 2 % of the random sentences)."""
    for phrase in PHRASES:
        assert read_and_answer(phrase, page) is not None, phrase


def test_the_sentences_use_the_grammar_of_both_languages():
    """The property is only worth its inputs: several hundred phrases, English and French."""
    assert len(PHRASES) > 300
    assert "critical" in PHRASES and "critique" in PHRASES
