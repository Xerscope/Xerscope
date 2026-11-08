"""The files' variants (analysis/ask/generated.py): plurals and abbreviations are grouped; two
words one letter apart are never grouped, only listed for review by `xerscope lexicon build`.

Measured on public XER files, the one-letter rule joined different words ("screed" / "screen",
"coarse" / "course", "lighting" / "lightning") and no frequency tells them from a typo
("gybsum" / "gypsum"): the maintainer copies the true typos into curated/."""

from __future__ import annotations

from xerkit import snap, todo, xer_text

from xerscope import cli
from xerscope.analysis import query

NAMES = [
    "Screed floor L1", "Screeds floor L2", "Screen wall", "Screens north", "Gypsum board", "Gybsum partition",
    "Slab pour", "Slabs cure", "Elec. panel", "Electrical test",
]  # fmt: skip
SAFE = [["elec", "electrical"], ["screed", "screeds"], ["screen", "screens"], ["slab", "slabs"]]
TO_REVIEW = [("gybsum", "gypsum"), ("screed", "screen"), ("screeds", "screens")]


def _file():
    return snap([todo(f"A{i}", task_name=name) for i, name in enumerate(NAMES)])


def _together(groups: list[list[str]], a: str, b: str) -> bool:
    return any({a, b} <= set(g) for g in groups)


def test_one_letter_apart_never_groups_nor_chains_groups():
    groups = query.variants([_file()])
    assert groups == {"TASK.task_name": SAFE}  # plurals and the abbreviation only
    for a, b in TO_REVIEW:
        assert not _together(groups["TASK.task_name"], a, b), (a, b)


def test_one_letter_apart_is_listed_for_review_with_its_column():
    assert query.near_spellings([_file()]) == {"TASK.task_name": TO_REVIEW}
    # a plural is one letter apart too: already grouped, it is not to review
    assert query.near_spellings([snap([todo("A1", task_name="Screed"), todo("A2", task_name="Screeds")])]) == {}


def test_ask_reads_screen_without_screed():
    """The variants come from every export; the update shown holds "screed" only: "screen" is
    unknown there and must not be read as "screed" through a variant group."""
    shown = snap([todo("B1", task_name="Screed floor L1"), todo("B2", task_name="Slab pour")])
    vocab = query.vocabulary(shown, variants=query.lexicons(query.variants([_file()])))
    got = query.parse_keywords("screen", vocab)
    assert query.apply(got, shown.activities, shown).rows.empty and got.ignored == ("screen",)
    slabs = query.apply(query.parse_keywords("slabs", vocab), shown.activities, shown).rows
    assert list(slabs["task_name"]) == ["Slab pour"]  # a plural is still read through its group


def _build(tmp_path, capsys, folders=("generated", "curated", "suggested")) -> tuple[int, str]:
    source = tmp_path / "xer"
    source.mkdir()
    (source / "a.xer").write_text(xer_text([todo(f"A{i}", task_name=name) for i, name in enumerate(NAMES)]))
    out = tmp_path / "lexicon"
    for folder in folders:
        (out / folder).mkdir(parents=True)
    code = cli.main(["lexicon", "build", str(source), "--out", str(out)])
    return code, capsys.readouterr().out


def test_lexicon_build_writes_safe_groups_and_lists_the_pairs_to_review(tmp_path, capsys):
    code, out = _build(tmp_path, capsys)
    assert code == 0 and "screed" not in out  # the output prints counts, never a word
    generated = tmp_path / "lexicon" / "generated"
    assert query.load_variants(generated) == {"TASK.task_name": SAFE}
    report = (generated / "report.txt").read_text(encoding="utf-8")
    section = report.split("to review (one letter apart, not used):\n", 1)[1]
    assert section.splitlines()[:3] == [f"TASK.task_name: {a}, {b}" for a, b in TO_REVIEW]


def test_lexicon_build_names_a_missing_folder(tmp_path, capsys):
    for missing in ("generated", "suggested"):
        root = tmp_path / missing
        root.mkdir()
        folders = [f for f in ("generated", "curated", "suggested") if f != missing]
        code, out = _build(root, capsys, folders)
        assert code != 0
        expected = f"create {root / 'lexicon' / missing} owned by the app account, see docs/deploy.md §10"
        assert expected in out and "Traceback" not in out
        assert not (root / "lexicon" / missing).exists()  # never created by the build
