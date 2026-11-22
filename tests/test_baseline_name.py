"""The P6 Project Baseline a file holds is named as P6's Maintain Baselines names it.

Source: Oracle P6 Professional help, Create a baseline ("the baseline title uses the project name and a
suffix of - Bx", the name can be changed) and Maintain Baselines dialog box (Baseline Name); the name is
the baseline project's own, PROJWBS.wbs_name of its project node ("Project Node", XER data map).
"""

import pytest
from file_projects import two_projects

from xerscope.analysis.baseline import baseline_in_file
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
