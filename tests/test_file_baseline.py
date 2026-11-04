"""The PROJECT rows of a file and the P6 Project Baseline pointer (sum_base_proj_id / orig_proj_id)."""

import io
import zipfile

import pandas as pd
from file_projects import BASELINE_DATE, two_projects

from xerscope.analysis import builtin_standards
from xerscope.anonymize import Anonymizer
from xerscope.app.diagnostic import ANALYSED, BASELINE_OF_ANALYSED, diagnostic_frames, projects_table
from xerscope.xer import build_snapshot, parse_text


def _snapshot(**kw):
    return build_snapshot(parse_text(two_projects(**kw), source="two.xer"))


def test_projects_block_has_one_row_per_project_with_pointers_and_role():
    table = projects_table(_snapshot()).set_index("proj_id")
    assert table.index.tolist() == ["1", "2"]
    assert table["tasks"].tolist() == [2, 2]
    assert table.loc["1", ["sum_base_proj_id", "orig_proj_id", "role"]].tolist() == ["2", "", ANALYSED]
    assert table.loc["2", ["sum_base_proj_id", "orig_proj_id", "last_baseline_update_date", "role"]].tolist() == [
        "",
        "1",
        BASELINE_DATE,
        BASELINE_OF_ANALYSED,
    ]


def test_projects_block_leaves_the_role_empty_when_the_pointer_names_another_project():
    table = projects_table(_snapshot(pointer="3")).set_index("proj_id")
    assert table["role"].tolist() == [ANALYSED, ""]


def test_projects_block_of_a_file_without_pointer_columns():
    from xerkit import snap

    table = projects_table(snap([{"task_code": "A1"}]))
    assert table[["proj_id", "tasks", "sum_base_proj_id", "role"]].values.tolist() == [["1", 1, "", ANALYSED]]


def test_projects_block_of_an_anonymous_download_renames_the_codes_and_keeps_the_ids():
    raw = parse_text(two_projects(), source="two.xer")
    anonymizer = Anonymizer.from_raws([raw])
    frames = {"01b_projects": diagnostic_frames(build_snapshot(raw), None, builtin_standards()["P6"])["01b_projects"]}
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames(frames))) as archive:
        text = archive.read("01b_projects.csv").decode("utf-8-sig")
    shown = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    assert "UPD" not in text and "BL," not in text
    assert shown["proj_short_name"].str.startswith("XP").all()
    assert shown[["proj_id", "sum_base_proj_id", "orig_proj_id"]].values.tolist() == [["1", "2", ""], ["2", "", "1"]]
