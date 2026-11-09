"""scripts/check_value_justification.py on made-up base/head files and pull request descriptions."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "check_value_justification.py"
_spec = importlib.util.spec_from_file_location("check_value_justification", SCRIPT)
cvj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvj)

GOLDEN = cvj.GOLDEN
FLOORS = cvj.FLOORS_FILE
DCMA = "src/xerscope/standards/dcma.toml"


def golden(value, status="pass", flagged=("K5040",)):
    metric = {"flagged": list(flagged), "status": status, "value": value}
    return json.dumps({"demo": {"A_2026-08-31.xer": {"DCMA/DCMA-01": metric}}})


def floors_file(**floors):
    return f'"""doc"""\n\nimport pytest\n\nFLOORS = {floors!r}\n\nDATES = ["early_start"]\n'


def standard(target="<= 5%", source="PAM 200.1 §4.1", params=None):
    params_line = f"params = {{ max_days = {params} }}\n" if params is not None else ""
    return (
        '[standard]\nid = "DCMA"\nname = "DCMA 14-Point"\n\n'
        f'[[metric]]\nid = "DCMA-01"\nname = "Logic"\nrule = "dcma_01_logic"\ntarget = "{target}"\n'
        f'{params_line}source = "{source}"\n'
    )


def test_nothing_moved_needs_no_line():
    files = {GOLDEN: (golden(4.17), golden(4.17)), FLOORS: (floors_file(H1=1.0), floors_file(H1=1.0))}
    assert cvj.check(files, "") == ([], [])


def test_a_moved_golden_value_needs_its_line():
    files = {GOLDEN: (golden(4.17), golden(8.33, flagged=("K5040", "K5050")))}
    lowered, missing = cvj.check(files, "")
    assert lowered == []
    assert missing == [
        'demo/A_2026-08-31.xer/DCMA/DCMA-01/flagged: ["K5040"] -> ["K5040", "K5050"] — <source>',
        "demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33 — <source>",
    ]


def test_the_printed_line_completed_with_a_source_justifies_the_value():
    files = {GOLDEN: (golden(4.17, status="pass"), golden(8.33, status="fail"))}
    body = """## Change

- demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33 — PAM 200.1 §4.1, hand count in test_rules.py
* demo/A_2026-08-31.xer/DCMA/DCMA-01/status: "pass" -> "fail" — same
"""
    assert cvj.check(files, body) == ([], [])


def test_a_line_without_source_or_with_other_values_does_not_count():
    files = {GOLDEN: (golden(4.17), golden(8.33))}
    for body in (
        "demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33",  # no source
        "demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33 — <source>".replace("<source>", ""),
        "demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 9.0 — P6 export",  # not the new value
        "DCMA-01: 4.17 -> 8.33 — P6 export",  # not the value's ID
    ):
        assert cvj.check(files, body)[1] == ["demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33 — <source>"], body


def test_a_line_inside_an_html_comment_does_not_count():
    files = {FLOORS: (floors_file(H10=0.96), floors_file(H10=0.97))}
    body = "<!-- e.g.\nFLOORS/H10: 0.96 -> 0.97 — held-out corpus\n-->"
    assert cvj.check(files, body)[1] == ["FLOORS/H10: 0.96 -> 0.97 — <source>"]


def test_added_and_removed_golden_values_read_absent():
    old = json.dumps({"demo": {"A.xer": {"P6/P6-01": {"value": 1.0}}}})
    new = json.dumps({"demo": {"A.xer": {"P6/P6-02": {"value": 2.0}}}})
    assert cvj.check({GOLDEN: (old, new)}, "")[1] == [
        "demo/A.xer/P6/P6-01/value: 1.0 -> absent — <source>",
        "demo/A.xer/P6/P6-02/value: absent -> 2.0 — <source>",
    ]


def test_a_floor_raised_needs_its_line_and_is_not_lowered():
    files = {FLOORS: (floors_file(H1=0.99, H2=0.9), floors_file(H1=1.0, H2=0.9))}
    assert cvj.check(files, "") == ([], ["FLOORS/H1: 0.99 -> 1.0 — <source>"])
    assert cvj.check(files, "FLOORS/H1: 0.99 -> 1.0 — test_p6_heldout on corpus pin abc123") == ([], [])


def test_a_floor_lowered_or_removed_fails_even_when_justified():
    files = {FLOORS: (floors_file(H1=0.99, H2=0.9), floors_file(H1=0.98))}
    body = "FLOORS/H1: 0.99 -> 0.98 — regression accepted\nFLOORS/H2: 0.9 -> absent — set dropped"
    lowered, missing = cvj.check(files, body)
    assert lowered == ["FLOORS/H1: 0.99 -> 0.98 lowered", "FLOORS/H2: 0.9 removed"]
    assert missing == []


def test_a_standard_target_and_param_need_a_line_prose_does_not():
    files = {DCMA: (standard(params=44), standard(target="<= 4%", source="PAM 200.1 §4.1, reworded", params=45))}
    assert cvj.check(files, "")[1] == [
        "dcma/DCMA-01.params.max_days: 44 -> 45 — <source>",
        'dcma/DCMA-01.target: "<= 5%" -> "<= 4%" — <source>',
    ]


def test_a_new_standard_file_lists_its_values_from_absent():
    lines = cvj.check({"src/xerscope/standards/new.toml": (None, standard())}, "")[1]
    assert lines == [
        'new.id: absent -> "DCMA" — <source>',
        'new/DCMA-01.rule: absent -> "dcma_01_logic" — <source>',
        'new/DCMA-01.target: absent -> "<= 5%" — <source>',
    ]


def test_the_command_reads_the_base_commit_and_the_description(tmp_path):
    """End to end in a throwaway repository: a lowered floor and an unjustified golden value fail."""

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=tmp_path, check=True)

    (tmp_path / "tests" / "golden").mkdir(parents=True)
    (tmp_path / "src" / "xerscope" / "standards").mkdir(parents=True)
    (tmp_path / GOLDEN).write_text(golden(4.17))
    (tmp_path / FLOORS).write_text(floors_file(H1=0.99))
    (tmp_path / DCMA).write_text(standard())
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True)
    base = base.stdout.strip()

    def run(body):
        env = {"PR_BODY": body, "PATH": "/usr/bin:/bin"}
        return subprocess.run(
            [sys.executable, str(SCRIPT), base], cwd=tmp_path, capture_output=True, text=True, env=env, check=False
        )

    assert run("").returncode == 0
    (tmp_path / GOLDEN).write_text(golden(8.33))
    (tmp_path / FLOORS).write_text(floors_file(H1=0.98))
    out = run("")
    assert out.returncode == 1
    assert "FLOORS/H1: 0.99 -> 0.98 lowered" in out.stdout
    assert "demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33 — <source>" in out.stdout
    (tmp_path / FLOORS).write_text(floors_file(H1=0.99))
    assert run("demo/A_2026-08-31.xer/DCMA/DCMA-01/value: 4.17 -> 8.33 — P6 export").returncode == 0
