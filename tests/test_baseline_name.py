"""The P6 Project Baseline a file holds is named as P6's Maintain Baselines names it.

Source: Oracle P6 Professional help, Create a baseline ("the baseline title uses the project name and a
suffix of - Bx", the name can be changed) and Maintain Baselines dialog box (Baseline Name); the name is
the baseline project's own, PROJWBS.wbs_name of its project node ("Project Node", XER data map).
"""

import pytest
from file_projects import two_projects

from xerscope.analysis.baseline import baseline_in_file, other_project_baselines, project_codes
from xerscope.xer import load_snapshot

pytestmark = pytest.mark.oracle("standard")

PROJECT_NODES = [
    "%T\tPROJWBS",
    "%F\twbs_id\tproj_id\tparent_wbs_id\twbs_short_name\twbs_name\tproj_node_flag",
    "%R\t10\t1\t\tUPD\tTerminal works\tY",
    "%R\t20\t2\t\tBL\tTerminal works - B1\tY",
]


def _with_project_nodes(text: str) -> str:
    """``text`` with the project node of each of its two projects, named as P6 names them."""
    lines = text.splitlines()
    end = lines.index("%E")
    return "\n".join(lines[:end] + PROJECT_NODES + lines[end:]) + "\n"


def _baseline(text: str):
    snapshot = load_snapshot(text.encode(), name="two.xer")
    return baseline_in_file(snapshot, text.encode())


def test_a_named_baseline_reads_its_name_then_its_project_id():
    baseline = _baseline(_with_project_nodes(two_projects()))
    assert baseline.label == "Terminal works - B1 (BL, P6 Project Baseline in two.xer)"
    assert baseline.source.startswith("P6 Project Baseline in the file (Terminal works - B1, BL, last update ")


def test_a_baseline_without_a_project_node_keeps_its_project_id_alone():
    """No PROJWBS project node: the file holds no name apart from the Project ID, the label is as before."""
    baseline = _baseline(two_projects())
    assert baseline.label == "BL (P6 Project Baseline in two.xer)"
    assert baseline.source.startswith("P6 Project Baseline in the file (BL, last update ")


def _sidebar_warnings(tmp_path, monkeypatch, flag: str) -> list[str]:
    from pathlib import Path

    from conftest import read_folder
    from streamlit.testing.v1 import AppTest

    import xerscope

    (tmp_path / "two.xer").write_text(two_projects(flag=flag))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    app = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    app = read_folder(app.run())
    assert not app.exception, [element.value for element in app.exception]
    return [element.value.replace("\\", "") for element in app.sidebar.warning]


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("N", ["1 update uses a user's primary baseline in P6: xerscope reads the project baseline."]),
        ("Y", []),
        ("", []),
    ],
)
def test_an_update_measured_against_a_users_primary_baseline_is_named(tmp_path, monkeypatch, flag, expected):
    """Project Details > Settings, "Baseline for earned value calculation" (Oracle P6 help): N reads as each
    user's primary baseline, which the file does not carry; Y (the project baseline) and blank say nothing."""
    warnings = _sidebar_warnings(tmp_path, monkeypatch, flag)
    assert [line for line in warnings if "primary baseline" in line] == expected


def test_the_debug_table_names_the_baseline_of_each_update_by_its_name_and_project_id():
    """Debug block 5, ``baseline_used_table``: one row per update, the baseline as Maintain Baselines names
    it, "name (Project ID)", the Project ID alone when the file holds no other name, "none" without one.
    The anonymous download keeps the kind and dates, not the file, the name or the sentence."""
    from xerscope.app.xml_baselines import baseline_used_table

    named = _baseline(_with_project_nodes(two_projects()))
    bare = _baseline(two_projects())
    update = load_snapshot(two_projects().encode(), name="two.xer")
    table = baseline_used_table([update, update, update], [named, bare, None])
    assert table["baseline"].tolist() == ["Terminal works - B1 (BL)", "BL", "none"]
    assert table["last_update"].notna().tolist() == [True, True, False]
    anonymous = baseline_used_table([update], [named], anonymous=True)
    assert list(anonymous.columns) == ["data_date", "kind", "found_by", "last_update"]


def test_a_check_that_reads_a_baseline_names_it_in_the_results_table():
    """Health page, ``summary_frame``: P6-13 reads the Project Baseline, so its row names it, "name (Project ID)"
    and how it was found; P6-01 reads none, so its cell stays empty. Planned dates are named as such."""
    import dataclasses

    from xerscope.analysis import AnalysisContext, builtin_standards, run_standard
    from xerscope.analysis.baseline import KIND_PROBABLE, Baseline
    from xerscope.analysis.checks import summary_frame

    update = load_snapshot(two_projects().encode(), name="two.xer")
    baseline = dataclasses.replace(_baseline(_with_project_nodes(two_projects())), kind=KIND_PROBABLE)
    p6 = builtin_standards()["P6"]
    against = summary_frame(run_standard(p6, AnalysisContext(update, None, baseline))).set_index("id")["baseline"]
    assert against["P6-13"] == "Terminal works - B1 (BL) · probable"
    assert against["P6-01"] == ""
    planned = summary_frame(run_standard(p6, AnalysisContext(update, None, Baseline.planned(update))))
    assert planned.set_index("id").loc["P6-13", "baseline"] == "planned dates"


def _update(flag: str):
    """An update (project 1, Project ID "1") whose Project Baseline pointer names project 9, held by no file here."""
    return load_snapshot(two_projects(pointer="9", flag=flag).encode(), name=f"update-{flag or 'blank'}.xer")


def test_other_project_baselines_leave_out_the_updates_that_do_not_use_the_project_baseline():
    """other_project_baselines docstring: the updates naming a project other than the baseline's are listed
    under that Project ID, "updates whose earned value does not use the project baseline (flag N), or that
    name none, are left out". Y and blank stay; N goes (uses_project_baseline is False for N only)."""
    separate = load_snapshot(two_projects().encode(), name="separate.xer")  # project 1: the pointer 9 is another
    uses, blank, primary = _update("Y"), _update(""), _update("N")
    assert other_project_baselines(separate, [uses, blank, primary]) == {"9": [uses, blank]}
    assert other_project_baselines(separate, [primary]) == {}


def test_a_project_code_is_the_first_one_a_file_of_the_series_gives():
    """project_codes: proj_id -> code over every file; the same proj_id coded two ways keeps the first
    file's code (setdefault), here project 2 is FIRST in the earlier file, SECOND in the later."""
    earlier = load_snapshot(two_projects(baseline_code="FIRST").encode(), name="earlier.xer")
    later = load_snapshot(two_projects(baseline_code="SECOND").encode(), name="later.xer")
    assert project_codes([earlier, later]) == {"1": "UPD", "2": "FIRST"}
