"""analysis/query.py: a sentence becomes the Gantt page's filters, never a number."""

import pytest

from xerscope.analysis import query, wbs
from xerscope.analysis.query import Filter, Vocabulary
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

VOCAB = Vocabulary(
    wbs={"1": "CIV · Civil works", "2": "ENG · Ingénierie", "3": "MEC · Mechanical & electrical"},
    codes={"c1": ("Zone", "B2", "Zone B2 north"), "c2": ("Zone", "B3", ""), "c3": ("Phase", "P1", "Phase one")},
    resources={"r1": ("CREW", "Site crew"), "r2": ("VENDOR", "Vendor")},
)


def test_vocabulary_matches_the_page_widgets():
    assert list(STATUS.values()) == query.STATUSES
    assert query.CATEGORIES == CATEGORY_ORDER
    assert {"status", "float", "wbs", "codes"} <= set(VOCAB.to_prompt())


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
        ("site crew in progress", Filter(status=("In progress",), resources=frozenset({"r1"}))),  # name over short
        ("jalons en retard", Filter(categories=("Critical",), milestones=True)),
        ("hamacs vendor", Filter(loe=True, resources=frozenset({"r2"}))),
    ],
)
def test_keyword_grammar(text, expected):
    got = query.parse_keywords(text, VOCAB)
    assert expected_fields(got) == expected_fields(expected)


def expected_fields(expected: Filter) -> dict:
    return {k: v for k, v in expected.__dict__.items() if k not in ("matched", "ignored")}


def test_search_keeps_the_words_of_the_file_only():
    lexicon = Vocabulary(wbs=VOCAB.wbs, words=frozenset({"earthworks", "design"}))
    got = query.parse_keywords("génie civil earthworks design", lexicon)  # "génie civil" = civil works (synonyms)
    assert (got.wbs_id, got.search, got.ignored) == ("1", "earthworks design", ())
    got = query.parse_keywords("xyzzy earthworks", lexicon)
    assert (got.search, got.ignored) == ("earthworks", ("xyzzy",))
    assert "Search: earthworks" in got.matched
    assert query.parse_keywords("genie", lexicon) == Filter(ignored=("genie",))  # nothing to filter on
    assert query.parse_keywords("genie", VOCAB).search == "genie"  # lexicon unknown: every word searched


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
    assert vocab.resources["5001"] == ("CREW", "Site crew") and vocab.has_milestones and vocab.has_loe
    assert {"earthworks", "design", "c3020"} <= vocab.words
    prompt = vocab.to_prompt()
    assert set(prompt) == {"status", "float", "wbs", "codes", "resources", "milestones", "loe"}
    assert not any("earthworks" in str(v) for v in prompt.values())  # labels only, no activity
    assert query.fold(float("nan")) == "" and query.fold("Béton Armé") == "beton arme"


def test_fuzzy_matches_carry_a_confidence_and_leave_known_words_alone():
    lexicon = Vocabulary(wbs=VOCAB.wbs, resources=VOCAB.resources, words=frozenset({"equipment", "delivery"}))
    typo = query.parse_keywords("mecanque critque not strated", lexicon)
    assert (typo.wbs_id, typo.categories, typo.status) == ("3", ("Critical",), ("Not started",))
    assert query.FUZZY <= typo.confidence < 1.0
    exact = query.parse_keywords("mechanical critical", lexicon)
    assert exact.confidence == 1.0
    known = query.parse_keywords("equipment delivery", lexicon)  # "equipment" ~ "equipe" (crew): not a typo
    assert known.resources == frozenset() and known.search == "equipment delivery" and known.confidence == 1.0


def test_two_nodes_as_close_make_the_pick_unsure():
    lexicon = Vocabulary(wbs={"a": "ZA · Piping north", "b": "ZB · Piping south"})
    guess = query.parse_keywords("pipng", lexicon)  # both nodes score the same on "piping"
    assert guess.wbs_id == "a" and guess.confidence < query.SURE
    sure = query.parse_keywords("pipng north", lexicon)  # "north" names one node exactly
    assert sure.wbs_id == "a" and sure.confidence == 1.0


def test_filter_runs_as_a_funnel_of_named_steps(store):
    from xerscope.analysis import wbs as wbs_tree
    from xerscope.viz import categorise

    snapshot = store.latest
    nodes = wbs_tree.tree(snapshot)
    tasks = snapshot.activities.assign(category=categorise(snapshot.activities))
    asked = query.parse_keywords("critical not started in civil works", query.vocabulary(snapshot, nodes))
    funnel = query.apply(asked, tasks, snapshot, nodes)
    assert [step.label for step in funnel.steps] == ["WBS CIV · Civil works", "status Not started", "float Critical"]
    assert all(step.source == "ask" for step in funnel.steps)
    assert funnel.start == len(tasks) and funnel.steps[-1].left == len(funnel.rows)
    civ = tasks[tasks["wbs_id"] == "7003"]
    assert funnel.steps[0].left == len(civ) and len(funnel.steps[0].removed) == len(tasks) - len(civ)
    expected = civ[(civ["status"] == "Not started") & (civ["category"] == "Critical")]
    assert set(funnel.rows["task_code"]) == set(expected["task_code"]) and len(expected) > 0
    line = query.funnel_line(funnel)
    assert line.startswith(f"{len(tasks)} → WBS CIV · Civil works {len(civ)} → status Not started ")
    assert line.endswith(f"→ float Critical {len(expected)}")
    assert query.apply(query.Filter(), tasks, snapshot, nodes).steps == []  # nothing asked: one population, no step
    with_search = query.apply(query.Filter(search="earth", milestones=False), tasks, snapshot, nodes)
    assert with_search.steps[0].label == 'name contains "earth"' and with_search.rows["task_code"].tolist() == ["C3020"]


def test_lexicon_is_data_the_user_extends(tmp_path):
    builtin, errors = query.load_lexicon()
    assert errors == [] and "mechanical" in builtin["mecanique"] and "meca" in builtin["mechanical"]
    (tmp_path / "acme.toml").write_text(
        '[[group]]\nwords = ["CVC", "HVAC", "chauffage ventilation"]\n', encoding="utf-8"
    )
    (tmp_path / "bad.toml").write_text("[[group]\n", encoding="utf-8")
    mine, errors = query.load_lexicon(tmp_path)
    assert errors and errors[0].startswith("bad.toml:")
    assert mine["cvc"] == ("hvac", "chauffage ventilation") and mine["mecanique"] == builtin["mecanique"]
    lexicon = Vocabulary(wbs={"h": "HVAC · HVAC works"}, lexicon=mine)
    assert query.parse_keywords("CVC en cours", lexicon).wbs_id == "h"  # the company's word finds its node
    assert query.parse_keywords("CVC en cours", Vocabulary(wbs={"h": "HVAC · HVAC works"})).wbs_id is None
