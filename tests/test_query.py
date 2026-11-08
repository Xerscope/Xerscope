"""analysis/query.py: a sentence becomes the Gantt page's filters, never a number."""

import pandas as pd
import pytest
from asklex import LEXICON

from xerscope.analysis import query, wbs
from xerscope.analysis.query import Filter, Vocabulary
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

VOCAB = Vocabulary(
    wbs={"1": "CIV · Civil works", "2": "ENG · Ingénierie", "3": "MEC · Mechanical & electrical"},
    codes={"c1": ("Zone", "B2", "Zone B2 north"), "c2": ("Zone", "B3", ""), "c3": ("Phase", "P1", "Phase one")},
    resources={"r1": ("CREW", "Site crew"), "r2": ("VENDOR", "Vendor")},
    lexicon=LEXICON,
)


LATE = ("Late (finish after baseline finish)", query.Atom("late"))


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
        ("en retard mechanical", Filter(wbs_id="3", clauses=(LATE,))),  # late = P6-12, not Critical
        ("zone B2 not started", Filter(status=("Not started",), code_type="Zone", code_ids=frozenset({"c1"}))),
        ("B2 et B3", Filter(code_type="Zone", code_ids=frozenset({"c1", "c2"}))),
        ("B2 P1", Filter(code_type="Zone", code_ids=frozenset({"c1"}))),  # one code type at a time
        ("earthworks", Filter(search="earthworks")),
        ("show me the earthworks in CIV", Filter(wbs_id="1", search="earthworks")),
        ("site crew in progress", Filter(status=("In progress",), resources=frozenset({"r1"}))),  # name over short
        ("jalons en retard", Filter(milestones=True, clauses=(LATE,))),
        ("hamacs vendor", Filter(loe=True, resources=frozenset({"r2"}))),
    ],
)
def test_keyword_grammar(text, expected):
    got = query.parse_keywords(text, VOCAB)
    assert expected_fields(got) == expected_fields(expected)


def expected_fields(expected: Filter) -> dict:
    return {k: v for k, v in expected.__dict__.items() if k not in ("matched", "ignored")}


def test_search_keeps_the_words_of_the_file_only():
    lexicon = Vocabulary(wbs=VOCAB.wbs, words=frozenset({"earthworks", "design"}), lexicon=LEXICON)
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
    vocab = query.vocabulary(snapshot, wbs.tree(snapshot), LEXICON)
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
    lexicon = Vocabulary(
        wbs=VOCAB.wbs, resources=VOCAB.resources, words=frozenset({"equipment", "delivery"}), lexicon=LEXICON
    )
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
    asked = query.parse_keywords("critical not started in civil works", query.vocabulary(snapshot, nodes, LEXICON))
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
    assert query.load_lexicon() == ({}, [])  # no lexicon ships with the package
    (tmp_path / "acme.toml").write_text(
        '[[group]]\nwords = ["CVC", "HVAC", "chauffage ventilation"]\n', encoding="utf-8"
    )
    (tmp_path / "bad.toml").write_text("[[group]\n", encoding="utf-8")
    mine, errors = query.load_lexicon(tmp_path)
    assert errors and errors[0].startswith("bad.toml:")
    assert mine["cvc"] == ("hvac", "chauffage ventilation") and "mecanique" not in mine
    lexicon = Vocabulary(wbs={"h": "HVAC · HVAC works"}, lexicon=mine)
    assert query.parse_keywords("CVC en cours", lexicon).wbs_id == "h"  # the company's word finds its node
    assert query.parse_keywords("CVC en cours", Vocabulary(wbs={"h": "HVAC · HVAC works"})).wbs_id is None


def test_no_lexicon_file_is_packaged_or_tracked_under_src():
    import subprocess
    from pathlib import Path

    import xerscope

    package = Path(xerscope.__file__).parent
    assert not [p for p in package.rglob("*.toml") if "lexicon" in p.parts or p.parent.name == "lexicon"]
    root = package.parent.parent
    tracked = subprocess.run(
        ["git", "ls-files", "src"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.split()
    assert not [p for p in tracked if "lexicon" in p and p.endswith(".toml")], tracked


def test_the_answer_is_a_sentence_over_the_rows_in_the_questions_language(store):
    from xerscope.analysis import wbs as wbs_tree
    from xerscope.viz import categorise

    snapshot = store.latest
    nodes = wbs_tree.tree(snapshot)
    tasks = snapshot.activities.assign(category=categorise(snapshot.activities))
    vocab = query.vocabulary(snapshot, nodes, LEXICON)
    asked = query.parse_keywords("critiques non démarrés en génie civil", vocab)
    funnel = query.apply(asked, tasks, snapshot, nodes)
    rows = funnel.rows
    worst = rows.loc[rows["total_float_d"].idxmin()]
    said = query.answer(asked, funnel, vocab)
    assert said.startswith(f"{len(rows)} activities critical not started in CIV · Civil works; ")
    assert f"worst float {worst['total_float_d']:+.0f} wd ({worst['task_code']})" in said
    assert f"latest finish {rows['finish'].max():%d/%m/%Y}." in said
    lang = query.language("critiques non démarrés en génie civil")
    french = query.answer(asked, funnel, vocab, lang)  # L1: the question's language
    assert lang == "fr" and french.startswith(
        f"{len(rows)} activités critique(s) non démarrée(s) dans CIV · Civil works; "
    )
    english = query.parse_keywords("milestones", vocab)
    said = query.answer(english, query.apply(english, tasks, snapshot, nodes), vocab)
    assert said.startswith(f"{int(tasks['is_milestone'].sum())} milestones; ")
    nothing = query.parse_keywords("xyzzy", vocab)  # nothing understood, a word left out: no row, never every row
    shown = query.apply(nothing, tasks, snapshot, nodes)
    assert shown.rows.empty and [step.label for step in shown.steps] == ["nothing understood"]
    assert query.answer(nothing, shown, vocab, "fr") == (
        "Rien de compris : aucune activité affichée. Le mot « xyzzy » n'est ni dans ce fichier ni dans le lexique."
    )
    empty = query.apply(query.Filter(search="nobodyhasthisname"), tasks, snapshot, nodes)
    assert (
        query.answer(query.Filter(search="nobodyhasthisname"), empty, vocab, "fr") == "Aucune activité ne correspond."
    )
    assert query.language("what is late in procurement") == "en" and query.language("jalons en retard") == "fr"
    # phrases of the grammar vote; a tie goes to the accent, else English
    assert [query.language(t) for t in ("marge négative", "late milestones", "C3020", "critique not started")] == [
        "fr",
        "en",
        "en",
        "en",
    ]
    late = query.parse_keywords("jalons sans successeur", vocab)
    assert "sans successeur" in query.answer(late, query.apply(late, tasks, snapshot, nodes), vocab, "fr")


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
    vocab = query.vocabulary(snapshot, wbs_tree.tree(snapshot), LEXICON)
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


def _demo(store):
    from xerscope.viz import categorise

    snapshot = store.latest
    nodes = wbs.tree(snapshot)
    tasks = snapshot.activities.assign(category=categorise(snapshot.activities))
    return snapshot, nodes, tasks, query.vocabulary(snapshot, nodes, LEXICON)


def _rows(text, store) -> set[str]:
    snapshot, nodes, tasks, vocab = _demo(store)
    return set(query.apply(query.parse_keywords(text, vocab), tasks, snapshot, nodes).rows["task_code"])


@pytest.mark.parametrize(
    ("text", "complement_of"),
    [
        ("not critical", "critical"),
        ("non critique", "critique"),
        ("pas critique", "critique"),
        ("not complete", "complete"),
        ("non terminées", "terminées"),
        ("not in progress", "in progress"),
        ("not normal", "normal"),
        ("sauf jalons", "jalons"),
    ],
)
def test_a_negation_is_the_complement_in_the_page_population(store, text, complement_of):
    _, _, tasks, _ = _demo(store)
    asked, positive = _rows(text, store), _rows(complement_of, store)
    assert positive and asked == set(tasks["task_code"]) - positive


def test_or_is_a_union_across_facets_and_binds_tighter_than_and(store):
    _, _, tasks, _ = _demo(store)
    critical = set(tasks.loc[tasks["category"] == "Critical", "task_code"])
    complete = set(tasks.loc[tasks["status"] == "Complete", "task_code"])
    assert _rows("critique ou terminé", store) == critical | complete and critical and complete
    civ = set(tasks.loc[tasks["wbs_code"] == "CIV", "task_code"])
    assert _rows("critique ou terminé en génie civil", store) == (critical | complete) & civ
    assert _rows("non critique ou terminé", store) == (set(tasks["task_code"]) - critical) | complete
    assert _rows("pas non critique", store) == critical  # double negation


def test_search_words_are_each_found_in_any_order(store):
    """H3: "installation piping" finds "Piping installation" (each word, not one phrase)."""
    assert _rows("installation piping", store) == _rows("piping installation", store) == {"X4020"}
    lexicon = Vocabulary(wbs={}, words=frozenset({"pump", "motor", "test"}))
    asked = query.parse_keywords("motor pump", lexicon)
    assert asked.search == "motor pump"
    import pandas as pd

    from xerscope.analysis.ask.funnel import all_words

    rows = pd.DataFrame({"task_code": ["A1", "A2"], "task_name": ["Pump motor test", "Motor alignment"]})
    assert all_words(rows, asked.search.split()).tolist() == [True, False]


def test_a_clause_holding_an_unknown_word_is_not_applied_and_is_named():
    for text in ("pas xyzzy critique", "critique xyzzy"):
        got = query.parse_keywords(text, Vocabulary(wbs={}, words=frozenset()))
        assert (got.categories, got.clauses, got.ignored) == (("Critical",), (), ("xyzzy",))
    got = query.parse_keywords("critique ou xyzzy", Vocabulary(wbs={}, words=frozenset()))
    assert got.empty and got.ignored == ("xyzzy",)  # an OR with an unknown operand: nothing applied


def test_late_is_p6_late_activities_and_negative_float_is_its_own_set(store):
    """Late = P6 Check Schedule Late Activities (P6-12, 101248): open, forecast finish later than the
    baseline finish in working time (46278), the planned finish without one. The set, not P6-12's
    population: P6-12 leaves milestones and LOE out of its count, "jalons en retard" keeps them.
    "Marge négative" is total float < 0 (P6-14). Critical is a third set."""
    from rulekit import codes, run_on_store

    from xerscope.analysis.baseline import Baseline

    snapshot, nodes, tasks, vocab = _demo(store)
    first = Baseline.from_snapshot(store.first)
    late = set(query.apply(query.parse_keywords("en retard", vocab), tasks, snapshot, nodes, first).rows["task_code"])
    flagged = set(codes(run_on_store(store, len(store) - 1, "P6-12")))
    other = set(tasks.loc[tasks["is_milestone"] | tasks["is_loe"], "task_code"])
    assert flagged and flagged <= late and late - flagged <= other
    bl = tasks[["task_code"]].join(first.frame[["bl_finish"]], on="task_code")["bl_finish"]
    by_hand = snapshot.work_hours(tasks["clndr_id"], bl.combine_first(tasks["target_end_date"]), tasks["finish"]) > 0
    assert late == set(tasks.loc[by_hand & ~tasks["is_complete"], "task_code"])
    negative = set(tasks.loc[~tasks["is_complete"] & (tasks["total_float_hr_cnt"] < 0), "task_code"])
    assert _rows("marge négative", store) == _rows("negative float", store) == negative
    assert _rows("late", store) != _rows("critique", store)
    planned = query.apply(query.parse_keywords("late", vocab), tasks, snapshot, nodes)  # no baseline: planned finish
    assert set(planned.rows["task_code"]) == set(
        tasks.loc[
            ~tasks["is_complete"]
            & (snapshot.work_hours(tasks["clndr_id"], tasks["target_end_date"], tasks["finish"]) > 0),
            "task_code",
        ]
    )


@pytest.mark.parametrize(
    ("text", "column", "check"),
    [
        ("float < 10", "total_float_d", lambda tf: tf < 10),  # a number without unit: working days
        ("marge totale au moins 15 jours", "total_float_d", lambda tf: tf >= 15),
        ("float zero", "total_float_d", lambda tf: tf == 0),
        ("float < 80h", "total_float_hr_cnt", lambda tf: tf < 80),
        ("durée supérieure à 20 jours", "original_d", lambda od: od > 20),
        ("avancement > 50%", "pct_complete", lambda pct: pct > 50),
    ],
)
def test_a_comparison_reads_the_column_in_its_unit(store, text, column, check):
    _, _, tasks, _ = _demo(store)
    open_float = column.startswith("total_float")
    population = tasks[~tasks["is_complete"]] if open_float else tasks
    expected = set(population.loc[check(population[column]).fillna(False), "task_code"])
    assert expected and _rows(text, store) == expected


def test_long_durations_are_the_p6_check_schedule_set(store):
    """P6 Check Schedule "Long Durations" (101248): remaining duration over x = 352 h."""
    _, _, tasks, _ = _demo(store)
    assert _rows("long durations", store) == set(tasks.loc[tasks["remain_drtn_hr_cnt"] > 352, "task_code"])


def test_dates_count_from_the_data_date(store):
    """Demo data date 2026-10-19 (a Monday): this week = [19/10, 26/10), next week = [26/10, 02/11)."""
    snapshot, _, tasks, vocab = _demo(store)
    assert snapshot.data_date == pd.Timestamp("2026-10-19 08:00")
    week = (pd.Timestamp("2026-10-26"), pd.Timestamp("2026-11-02"))
    starting = set(tasks.loc[(tasks["start"] >= week[0]) & (tasks["start"] < week[1]), "task_code"])
    assert starting and _rows("starting next week", store) == _rows("commence la semaine prochaine", store) == starting
    finishing = set(tasks.loc[tasks["finish"] < pd.Timestamp("2027-01-01"), "task_code"])
    assert _rows("finissent avant fin décembre", store) == finishing
    active = set(tasks.loc[(tasks["start"] < week[1]) & (tasks["finish"] >= week[0]), "task_code"])
    assert _rows("next week", store) == active and active > starting
    got = query.parse_keywords("starting next week", vocab)
    assert got.matched == ("Start 26/10/2026–01/11/2026",) and got.wbs_id is None  # not "setting" (MEC)


def test_constraints_open_ends_and_longest_path(store):
    from xerscope.analysis.p6.check_schedule import P6_HARD_CONSTRAINTS, SOFT_CONSTRAINTS
    from xerscope.analysis.populations import constrained_by, has_predecessor_in_project, has_successor_in_project

    snapshot, _, tasks, _ = _demo(store)
    soft = set(tasks.loc[constrained_by(tasks, SOFT_CONSTRAINTS, ignore_started_starts=True), "task_code"])
    hard = set(tasks.loc[constrained_by(tasks, P6_HARD_CONSTRAINTS, ignore_started_starts=True), "task_code"])
    assert soft == {"P2040", "X4050"} and _rows("soft constraints", store) == soft
    assert _rows("hard constraints", store) == hard and _rows("contraintes", store) >= soft
    no_pred = set(tasks.loc[~has_predecessor_in_project(snapshot, tasks) & ~tasks["has_external_pred"], "task_code"])
    no_succ = set(tasks.loc[~has_successor_in_project(snapshot, tasks) & ~tasks["has_external_succ"], "task_code"])
    assert no_pred and _rows("sans prédécesseur", store) == no_pred and _rows("sans successeur", store) == no_succ
    assert _rows("open ends", store) == no_pred | no_succ
    assert _rows("longest path", store) == set(tasks.loc[tasks["on_longest_path"], "task_code"])


def test_the_hard_constraint_filter_names_the_p6_set():
    """P6 Professional's hard set (Check Schedule, 101248) differs from DCMA's and EPPM's: the
    chip and the answer name it, in P6's own constraint names."""
    vocab = Vocabulary(wbs={}, words=frozenset())
    names = "Mandatory Start, Start On, Mandatory Finish, Finish On"
    for text in ("hard constraints", "contraintes dures", "mandatory constraint"):
        assert query.parse_keywords(text, vocab).matched == (f"With a hard constraint (P6: {names})",), text
    hard = query.Atom("constraint", "hard")
    assert query.said(hard, vocab, "fr") == f"avec contrainte dure (P6 : {names})"
    assert query.said(query.Atom("constraint", "soft"), vocab) == "with a soft constraint"


def test_an_activity_id_is_that_activity_exactly(store):
    assert _rows("C3020", store) == {"C3020"}
    assert _rows("c3020 ou c3030", store) == _rows("c3020 c3030", store) == {"C3020", "C3030"}


def test_a_typo_is_bounded_never_an_id_never_a_common_word_onto_a_node():
    """M8: an Activity ID is never read as another; a common word is never a node by a fuzzy
    score ("starting" is not "Equipment setting"); "long" is no alias of a node."""
    vocab = Vocabulary(
        wbs={"1": "MEC · Mechanical & electrical", "2": "PRC · Procurement"},
        words=frozenset({"a1001", "setting", "long", "lead", "equipment"}),
        node_words={"1": frozenset({"setting"})},
        lexicon=LEXICON,
    )
    for text in ("A1000", "a1005", "starting"):
        got = query.parse_keywords(text, vocab)
        assert got.empty and got.ignored == (query.fold(text),), text
    assert query.parse_keywords("equipmnt", vocab).search == "equipment"  # a typo on a name word: read, unsure
    assert query.parse_keywords("mecanque critque", vocab).wbs_id == "1"


def test_unknown_words_cost_no_more_than_a_few_lookups():
    """L8: 30 unknown words against 20 000 words of a file: at most MAX_FUZZY words are tried, each
    against the words of the same first letter and close length."""
    import random
    import time

    rng = random.Random(1)
    word = lambda n: "".join(rng.choice("abcdefghij") for _ in range(n))  # noqa: E731
    vocab = Vocabulary(wbs={}, words=frozenset(word(rng.randint(5, 12)) for _ in range(20_000)))
    sentence = " ".join(word(9) for _ in range(30))
    start = time.perf_counter()
    got = query.parse_keywords(sentence, vocab)
    assert time.perf_counter() - start < 0.5 and len(got.ignored) + len(got.search.split()) == 30
    assert len(query.parse_keywords("x" * 5000, vocab).ignored) <= 2  # read up to MAX_CHARS


def test_a_word_of_another_loaded_file_is_understood_on_the_displayed_update():
    """The vocabulary covers every loaded file: "pump" names an activity of an earlier update
    only; on the displayed update it is understood (and finds no row), not unknown."""
    from xerkit import snap, todo

    earlier = snap([todo("A1", task_name="Pump alignment")], data_date="2026-03-02 08:00")
    shown = snap([todo("A2", task_name="Valve test")], data_date="2026-03-09 08:00")
    alone = query.parse_keywords("pump", query.vocabulary(shown))
    assert alone.empty and alone.ignored == ("pump",)
    vocab = query.vocabulary(shown, others=[earlier])
    for text, expected in (("pump", "word:pump"), ("A1", "id:A1"), ("valve", "word:valve")):
        got = query.parse_keywords(text, vocab)
        assert (query.canonical(got, vocab), got.ignored) == (expected, ()), text
    rows = query.apply(query.parse_keywords("pump", vocab), shown.activities, shown).rows
    assert rows.empty  # understood, and no activity of this update holds it


# --- variants generated from the files (analysis/ask/generated.py) ---------------------------

NAMES = [  # written by hand: each group below, and the pairs that must stay apart
    "Mec. installation", "Mechanical test", "Fondation pieux", "Fondations radier", "Béton coulage",
    "Beton armé", "Montage pompe", "Montages pompes", "Installation vanne", "Instalation câbles", "Pose câble",
    "Poste HT", "Pre-test", "Prefabrication", "Excavation", "Excavatoin", "Canal", "Canaux", "Piping", "Paving",
]  # fmt: skip
GROUPS = [  # plural (FR/EN, -al/-aux), abbreviation with its dot, one letter apart at 6+ letters
    ["cable", "cables"], ["canal", "canaux"], ["fondation", "fondations"], ["instalation", "installation"],
    ["mec", "mechanical"], ["montage", "montages"], ["pompe", "pompes"],
]  # fmt: skip
APART = [("pose", "poste"), ("pre", "prefabrication"), ("excavation", "excavatoin"), ("piping", "paving")]


def test_variants_are_grouped_by_written_rules_within_one_column():
    from xerkit import snap, todo

    file = snap(
        [todo(f"A{i}", task_name=name) for i, name in enumerate(NAMES)],
        wbs=[{"wbs_id": "10", "proj_id": "1", "wbs_short_name": "W", "wbs_name": "Pompes", "proj_node_flag": "N"}],
    )
    groups = query.variants([file])
    assert groups == {"TASK.task_name": GROUPS}  # every group expected, none other: precision and recall 1
    together = {frozenset(g) for g in groups["TASK.task_name"]}
    assert not any({a, b} <= g for a, b in APART for g in together)
    # "Pompes" (a WBS name) and "pompe" (an activity name) stay apart: a group never crosses a column
    assert "PROJWBS.wbs_name" not in groups
    assert query.variants([file]) == groups  # deterministic
    assert query.variant_counts(groups) == {"TASK.task_name": 7}


def test_the_demo_series_holds_no_variant(store):
    """The demo's names have no plural pair, abbreviation or near-spelling within a column: no
    group, so no false one ("complete" / "completion", "piping" / "paving", "setting" / "site")."""
    assert query.variants(list(store)) == {}


def test_variants_read_within_their_column_only():
    variants = query.lexicons({"TASK.task_name": [["fondation", "fondations"], ["travaux", "works"]]})
    vocab = Vocabulary(wbs={"1": "CIV · Civil works"}, words=frozenset({"fondations", "works"}), variants=variants)
    assert query.parse_keywords("fondation", vocab).search == "fondations"  # a variant of an activity name word
    got = query.parse_keywords("travaux", vocab)  # a group of the names column: a search, not the WBS node
    assert (got.wbs_id, got.search) == (None, "works")
    on_wbs = Vocabulary(wbs=vocab.wbs, words=vocab.words, variants={"PROJWBS.wbs_name": variants["TASK.task_name"]})
    assert query.parse_keywords("travaux", on_wbs).wbs_id == "1"  # the same group on the WBS column names the node


def test_a_generated_file_is_read_back_per_column(tmp_path):
    groups = {"TASK.task_name": [["pompe", "pompes"]], "RSRC.rsrc_name": [["grue", "grues"]]}
    (tmp_path / "generated.toml").write_text(query.variants_toml(groups), encoding="utf-8")
    assert query.load_variants(tmp_path) == groups
    assert query.load_lexicon(tmp_path) == ({}, [])  # column groups never join the global lexicon
    merged = query.lexicons(groups, {"TASK.task_name": [["vanne", "vannes"]]})
    assert merged["TASK.task_name"] == {
        "pompe": ("pompes",),
        "pompes": ("pompe",),
        "vanne": ("vannes",),
        "vannes": ("vanne",),
    }
