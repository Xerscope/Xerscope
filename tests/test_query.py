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


def test_the_answer_is_a_sentence_over_the_rows_in_the_questions_language(store):
    from xerscope.analysis import wbs as wbs_tree
    from xerscope.viz import categorise

    snapshot = store.latest
    nodes = wbs_tree.tree(snapshot)
    tasks = snapshot.activities.assign(category=categorise(snapshot.activities))
    vocab = query.vocabulary(snapshot, nodes)
    asked = query.parse_keywords("critiques non démarrés en génie civil", vocab)
    funnel = query.apply(asked, tasks, snapshot, nodes)
    rows = funnel.rows
    worst = rows.loc[rows["total_float_d"].idxmin()]
    said = query.answer(asked, funnel, vocab)  # English whatever the question's language
    assert said.startswith(f"{len(rows)} activities critical not started in CIV · Civil works, ")
    assert f"worst float {worst['total_float_d']:+.0f} wd ({worst['task_code']})" in said
    assert f"latest finish {rows['finish'].max():%d/%m/%Y}." in said
    french = query.answer(asked, funnel, vocab, "fr")  # kept for a French interface one day
    assert french.startswith(f"{len(rows)} activités critique(s) non démarrée(s) dans CIV · Civil works, ")
    english = query.parse_keywords("milestones", vocab)
    said = query.answer(english, query.apply(english, tasks, snapshot, nodes), vocab)
    assert said.startswith(f"{int(tasks['is_milestone'].sum())} milestones, ")
    nothing = query.parse_keywords("xyzzy", vocab)  # an ignored word: every row; a search for a name nobody has
    empty = query.apply(query.Filter(search="nobodyhasthisname"), tasks, snapshot, nodes)
    assert query.answer(nothing, empty, vocab, "fr") == "Aucune activité ne correspond."
    assert query.language("what is late in procurement") == "en" and query.language("jalons en retard") == "fr"


def test_an_unknown_word_gets_the_closest_labels_and_can_be_taught():
    vocab = Vocabulary(
        wbs={"1": "CIV · Civil works", "5": "COM · Commissioning", "2": "ENG · Ingénierie"},
        resources={"r1": ("CREW", "Site crew")},
        words=frozenset({"earthworks"}),
    )
    offers = query.suggestions("commiss", vocab)
    assert offers[0][:2] == ("wbs", "COM · Commissioning") and offers[0][2] >= query.SUGGEST
    assert query.suggestions("xyzzy", vocab) == []  # nothing close: nothing offered
    assert query.parse_keywords("commiss", vocab).wbs_id is None  # not a typo close enough (FUZZY)
    taught = query.learn(vocab.lexicon, "commiss", "COM · Commissioning")
    assert "commissioning" in taught["commiss"] and "commiss" in taught["com"]
    assert query.parse_keywords("commiss", Vocabulary(wbs=vocab.wbs, lexicon=taught)).wbs_id == "5"
    text = query.learned_toml([("commiss", "COM · Commissioning"), ("bétonnage", "CIV · Civil works")])
    assert '[[group]]\nwords = ["commiss", "COM", "Commissioning"]' in text and '"bétonnage"' in text
    import tomllib

    assert len(tomllib.loads(text)["group"]) == 2  # a file load_lexicon reads back


def test_a_chip_taken_off_drops_its_filter():
    asked = query.parse_keywords("critical not started in civil works zone B2 site crew milestones", VOCAB)
    assert asked.wbs_id == "1" and asked.code_ids == frozenset({"c1"}) and asked.resources == frozenset({"r1"})
    assert query.without(asked, "WBS: CIV · Civil works", VOCAB).wbs_id is None
    assert query.without(asked, "Status: Not started", VOCAB).status == ()
    assert query.without(asked, "Float: Critical", VOCAB).categories == ()
    assert (
        query.without(asked, "Zone: B2", VOCAB).code_ids == frozenset()
        and query.without(asked, "Zone: B2", VOCAB).code_type is None
    )
    assert query.without(asked, "Resource: CREW", VOCAB).resources == frozenset()
    assert query.without(asked, "Milestones", VOCAB).milestones is False
    assert query.without(asked, "Search: nothing", VOCAB) == asked  # a label the filter does not carry: unchanged


def test_the_files_own_words_name_their_node(store):
    """The automatic lexicon: a word of the activity names under one node alone names that node
    (and stays a search in it); a word under several nodes names none."""
    from xerscope.analysis import wbs as wbs_tree

    snapshot = store.latest
    vocab = query.vocabulary(snapshot, wbs_tree.tree(snapshot))
    assert {"foundations", "earthworks", "roads"} <= vocab.node_words["7003"]  # CIV
    assert {"piping", "instrumentation"} <= vocab.node_words["7004"]  # MEC
    assert "installation" in vocab.node_words["7004"]  # every "installation" activity is under MEC
    assert "equipment" not in {w for words in vocab.node_words.values() for w in words}  # PRC and MEC both
    assert "design" in vocab.node_words["7001"]  # every "design" activity is under ENG
    assert "complete" not in vocab.node_words["7003"] and "site" not in vocab.node_words["7003"]  # a status, a resource
    assert query.parse_keywords("fondations", vocab).search == "foundations"  # a synonym of an own word: searched as it
    got = query.parse_keywords("foundations", vocab)
    assert got.wbs_id == "7003" and got.search == "foundations"
    got = query.parse_keywords("equipment", vocab)
    assert got.wbs_id is None and got.search == "equipment"
    got = query.parse_keywords("installation", vocab)  # an own word of MEC, also a synonym of CIV's "erection"
    assert got.wbs_id == "7004" and got.search == "installation"
    assert query.vocabulary(snapshot).node_words["7003"] >= {"foundations"}  # without the tree: own node


def test_type_name_and_value_said_together_ask_one_question():
    """ "Phase P1", both "Phase" types holding a "P1": one question, value and type in each choice
    (maintainer decision, 2026-11-08); the answer filters on that value alone."""
    from test_code_types_blind import GLOBAL_P1, PROJECT_P1, _code_snapshot

    s = _code_snapshot()
    vocab = query.vocabulary(s)
    got = query.parse_keywords("Phase P1", vocab)
    assert got.code_ids == frozenset() and {c.word for c in got.clarify} == {"P1"}
    assert {c.value: c.label for c in got.clarify} == {
        GLOBAL_P1: "P1 — Phase (global)",
        PROJECT_P1: "P1 — Phase (project)",
    }
    got = query.parse_keywords("Phase P1", vocab, {"P1": PROJECT_P1})
    assert got.code_ids == frozenset({PROJECT_P1}) and got.clarify == () and got.search == ""


def test_a_chosen_type_offers_its_values_then_the_value_filters():
    """ "Phase", two "Phase" types: the type is asked first, then its values; nothing is filtered
    before a value is picked."""
    from test_code_types_blind import GLOBAL_P1, GLOBAL_P2, _code_snapshot

    s = _code_snapshot()
    vocab = query.vocabulary(s)
    got = query.parse_keywords("Phase", vocab, {"Phase": "Phase (global)"})
    assert got.code_ids == frozenset()
    assert [(c.word, c.value, c.label) for c in got.clarify] == [
        ("Phase", GLOBAL_P1, "P1 — Phase (global)"),
        ("Phase", GLOBAL_P2, "P2 — Phase (global)"),
    ]
    got = query.parse_keywords("Phase", vocab, {"Phase": GLOBAL_P1})
    assert got.code_type == "Phase (global)" and got.code_ids == frozenset({GLOBAL_P1}) and got.clarify == ()
