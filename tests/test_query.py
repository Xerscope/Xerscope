"""analysis/query.py: a sentence becomes the Gantt page's filters, never a number."""

import pytest

from xerscope.analysis import query, wbs
from xerscope.analysis.query import Filter, Vocabulary
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

VOCAB = Vocabulary(
    wbs={"1": "CIV · Civil works", "2": "ENG · Ingénierie", "3": "MEC · Mechanical & electrical"},
    codes={"c1": ("Zone", "B2", "Zone B2 north"), "c2": ("Zone", "B3", ""), "c3": ("Phase", "P1", "Phase one")},
)


def test_vocabulary_matches_the_page_widgets():
    assert list(STATUS.values()) == query.STATUSES
    assert query.CATEGORIES == CATEGORY_ORDER
    assert set(VOCAB.to_prompt()) == {"status", "float", "wbs", "codes"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", Filter()),
        ("   ", Filter()),
        ("critical not started in civil works", Filter(wbs_id="1", status=("Not started",), categories=("Critical",))),
        ("critiques non démarrées CIV", Filter(wbs_id="1", status=("Not started",), categories=("Critical",))),
        ("quasi critique en cours", Filter(status=("In progress",), categories=("Near critical",))),  # not "Critical"
        ("ingenierie terminée", Filter(wbs_id="2", status=("Complete",))),
        ("en retard mechanical", Filter(wbs_id="3", categories=("Critical",))),
        ("zone B2 not started", Filter(status=("Not started",), code_type="Zone", code_ids=frozenset({"c1"}))),
        ("B2 et B3", Filter(code_type="Zone", code_ids=frozenset({"c1", "c2"}))),
        ("B2 P1", Filter(code_type="Zone", code_ids=frozenset({"c1"}))),  # one code type at a time
        ("earthworks", Filter(search="earthworks")),
        ("show me the earthworks in CIV", Filter(wbs_id="1", search="earthworks")),
    ],
)
def test_keyword_grammar(text, expected):
    got = query.parse_keywords(text, VOCAB)
    assert expected_fields(got) == expected_fields(expected)


def expected_fields(expected: Filter) -> dict:
    return {k: v for k, v in expected.__dict__.items() if k != "matched"}


def test_matched_phrases_read_in_sentence_order():
    got = query.parse_keywords("civil works critical not started", VOCAB)
    assert got.matched == ("WBS: CIV · Civil works", "Float: Critical", "Status: Not started")
    assert query.parse_keywords("nothing here", VOCAB).matched == ("Search: nothing here",)


def test_backend_answers_first_and_its_failures_fall_back():
    answer = Filter(wbs_id="3")
    assert query.parse("anything", VOCAB, backend=lambda text, vocab: answer) == answer
    assert query.parse("critical", VOCAB, backend=lambda text, vocab: None).categories == ("Critical",)

    def broken(text, vocab):
        raise ConnectionError("model down")

    assert query.parse("critical", VOCAB, backend=broken).categories == ("Critical",)
    assert query.parse("", VOCAB, backend=broken) == Filter()  # an empty sentence never calls the backend


def test_vocabulary_from_the_demo(store):
    snapshot = store.latest
    vocab = query.vocabulary(snapshot, wbs.tree(snapshot))
    assert vocab.wbs["7003"] == "CIV · Civil works" and "7000" not in vocab.wbs  # project node left out
    assert query.vocabulary(snapshot).wbs == vocab.wbs  # same names straight from snapshot.wbs
    assert query.parse_keywords("CIV critique", vocab).wbs_id == "7003"
    assert query.fold(float("nan")) == "" and query.fold("Béton Armé") == "beton arme"
