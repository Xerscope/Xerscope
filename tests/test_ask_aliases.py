"""Other words for what the file says (analysis/ask/lexer.py: ``_code_aliases``, ``_word_aliases``).

A planner names a discipline by its code's name, a word of it, a trade synonym, or a phrase the
lexicon groups with the code the Activity IDs carry. Each case below is read by hand: the activities
the sentence must keep, and the filter the funnel shows.
"""

import pytest
from xerkit import active, parse_text, snap, todo, xer_text

from xerscope.analysis import query
from xerscope.analysis.task_filters import branch_tasks
from xerscope.analysis.wbs import tree
from xerscope.viz import categorise
from xerscope.xer import build_snapshot

NAMES = {
    "Discipline GC": "Génie civil",
    "Discipline EL": "Électricité",
    "Discipline CVC": "Chauffage ventilation climatisation",
}


@pytest.fixture(scope="module")
def coded():
    """A1010, A1020 (in progress) GC; A2010 EL; A3010 CVC. "Coffrage voile GC" also says GC in its name."""
    tasks = [
        todo("A1010", task_name="Terrassement zone A"),
        active("A1020", task_name="Coffrage voile GC"),
        todo("A2010", task_name="Tirage câbles"),
        todo("A3010", task_name="Pose gaines"),
    ]
    codes = [("A1010", "Discipline", "GC"), ("A1020", "Discipline", "GC"), ("A2010", "Discipline", "EL"),
             ("A3010", "Discipline", "CVC")]  # fmt: skip
    text = xer_text(tasks, codes=codes)
    for generated, name in NAMES.items():
        text = text.replace(generated, name)
    return build_snapshot(parse_text(text, source="t.xer"))


def read(snapshot, sentence, groups=()):
    tasks = branch_tasks(snapshot, None, hide_loe=False)
    tasks = tasks.assign(category=categorise(tasks))
    vocab = query.vocabulary(snapshot, tree(snapshot), query.lexicon_from_groups(list(groups)))
    ask = query.parse_keywords(sentence, vocab)
    funnel = query.apply(ask, tasks, snapshot, tree(snapshot), None)
    return sorted(funnel.rows["task_code"]), list(ask.ignored), query.funnel_line(funnel)


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(
    ("sentence", "kept"),
    [
        ("climatisation", ["A3010"]),  # a word only CVC's name holds, and no activity name uses
        ("ventilation non commencées", ["A3010"]),
        ("génie civil", ["A1010", "A1020"]),  # the name, as before
    ],
)
def test_a_word_of_a_code_name_reads_as_that_code(coded, sentence, kept):
    codes, ignored, line = read(coded, sentence)
    assert codes == kept and ignored == [] and "Discipline" in line


@pytest.mark.oracle("standard")
def test_a_trade_synonym_of_a_code_reads_as_that_code(coded):
    """The lexicon groups "clim" with CVC: "clim" keeps A3010; "clim en cours" keeps none (A3010 is not
    started), and still reads both filters."""
    assert read(coded, "clim", [["CVC", "clim"]])[0] == ["A3010"]
    codes, ignored, line = read(coded, "clim en cours", [["CVC", "clim"]])
    assert codes == [] and ignored == [] and "In progress" in line and "Discipline CVC" in line


@pytest.mark.oracle("standard")
def test_a_word_activities_also_use_stays_a_search_word():
    """ "coffrage" is in a code name and in an activity name: searched in the names, never read as
    the code (only GC-coded "Coffrage voile" says it)."""
    tasks = [todo("A1", task_name="Coffrage voile"), todo("A2", task_name="Pose")]
    text = xer_text(tasks, codes=[("A2", "Lot", "CF")]).replace("Lot CF", "Coffrage et ferraillage")
    codes, ignored, line = read(build_snapshot(parse_text(text, source="t.xer")), "coffrage")
    assert codes == ["A1"] and 'name contains "coffrage"' in line


@pytest.mark.oracle("standard")
def test_a_phrase_grouped_with_the_ids_code_searches_that_code():
    """IDs carry the discipline (GC-1010); the lexicon groups "génie civil" with GC: the phrase searches
    "gc" in the IDs and names, and keeps the two GC activities."""
    plan = snap([todo("GC-1010", task_name="Terrassement"), active("GC-1020", task_name="Coffrage"),
                 todo("EL-2010", task_name="Câbles")])  # fmt: skip
    codes, ignored, line = read(plan, "génie civil en cours", [["GC", "génie civil"]])
    assert codes == ["GC-1020"] and ignored == [] and 'name contains "gc"' in line
    assert read(plan, "génie civil")[1] == ["genie", "civil"]  # without the lexicon: words left out, as before
