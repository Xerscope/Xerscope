"""scripts/mutation.py: what it reads from mutmut's results, and what --check lets through."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mutation import compare, main, measure  # noqa: E402


def row(mutants, killed, unchecked=0):
    return {
        "mutants": mutants,
        "killed": killed,
        "survived": mutants - killed - unchecked,
        "no_tests": 0,
        "unchecked": unchecked,
    }


BASELINE = {"src/a.py": row(200, 150), "src/b.py": row(40, 10)}


def results(tmp_path, **codes_by_module):
    """A mutants/ folder as mutmut 3.8.1 leaves it: one <module>.meta per mutated file."""
    for name, codes in codes_by_module.items():
        meta = tmp_path / "mutants" / "src" / f"{name}.py.meta"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps({"exit_code_by_key": {f"m{i}": code for i, code in enumerate(codes)}}))
    return tmp_path / "mutants"


def test_counts_read_from_the_exit_codes(tmp_path):
    """Exit codes of mutmut 3.8.1 (stats.status_by_exit_code): 1 and 3 killed, 0 survived,
    5 and 33 no test, None not checked; anything else (36 timeout) is none of these.

    a: codes 1 1 3 0 0 5 33 None None 36 -> 10 mutants, 3 killed, 2 survived, 2 without test, 2 unchecked.
    """
    mutants = results(tmp_path, a=[1, 1, 3, 0, 0, 5, 33, None, None, 36])
    assert measure(mutants) == {"src/a.py": {"mutants": 10, "killed": 3, "survived": 2, "no_tests": 2, "unchecked": 2}}


def test_same_scores_pass():
    assert compare(BASELINE, BASELINE) == ([], [])


def test_lower_score_fails_even_with_more_mutants_killed():
    """a: 150/200 = 75.0 % before; 152/210 = 72.4 % now: two more killed, a lower share."""
    worse, better = compare(BASELINE | {"src/a.py": row(210, 152)}, BASELINE)
    assert worse == ["src/a.py: 150/200 (75.0 %) -> 152/210 (72.4 %)"]
    assert better == []


def test_same_share_on_another_count_passes():
    """a: 150/200 before, 75/100 now: the same 75 %."""
    assert compare(BASELINE | {"src/a.py": row(100, 75)}, BASELINE) == ([], [])


def test_higher_score_is_listed_not_failed():
    """b: 10/40 = 25.0 % before, 11/40 = 27.5 % now."""
    worse, better = compare(BASELINE | {"src/b.py": row(40, 11)}, BASELINE)
    assert worse == []
    assert better == ["src/b.py: 10/40 (25.0 %) -> 11/40 (27.5 %)"]


def test_module_of_the_baseline_not_measured_fails():
    worse, _ = compare({"src/a.py": BASELINE["src/a.py"]}, BASELINE)
    assert worse == ["src/b.py: not measured"]


def test_unchecked_mutants_fail():
    """b: 10 killed of 40 as before, 3 of the 40 never run: the run is not complete."""
    worse, _ = compare(BASELINE | {"src/b.py": row(40, 10, unchecked=3)}, BASELINE)
    assert worse == ["src/b.py: 3 mutants left unchecked"]


def test_new_module_is_listed_not_checked():
    worse, better = compare(BASELINE | {"src/c.py": row(10, 0)}, BASELINE)
    assert worse == []
    assert better == ["src/c.py (new): 0/10 (0.0 %)"]


def test_check_exit_code(tmp_path):
    """a: 4 mutants, 2 killed. Baseline 2/4 passes; baseline 3/4 fails; no result at all fails."""
    mutants = results(tmp_path, a=[1, 1, 0, 0])
    baseline = tmp_path / "baseline.json"
    out = ["--mutants", str(mutants), "--out", str(tmp_path / "out.json")]
    baseline.write_text(json.dumps({"src/a.py": row(4, 2)}))
    assert main([*out, "--check", str(baseline)]) == 0
    baseline.write_text(json.dumps({"src/a.py": row(4, 3)}))
    assert main([*out, "--check", str(baseline)]) == 1
    assert main(["--mutants", str(tmp_path / "none"), "--out", str(tmp_path / "out.json")]) == 1


def test_the_mutation_job_runs_weekly_or_by_hand_and_caps_the_memory_of_a_mutant():
    """mutation.yml never runs on a pull request or a push (a full run takes about an hour and a half): every
    Monday and by hand only. mutmut runs under a limit of address space, so a mutant that loops and
    allocates without end is a killed mutant, not a lost runner."""
    workflow = (ROOT / ".github" / "workflows" / "mutation.yml").read_text(encoding="utf-8")
    on = workflow[workflow.index("\non:") : workflow.index("\nconcurrency:")]
    triggers = re.findall(r"^  (\w+):", on, re.M)
    assert triggers == ["workflow_dispatch", "schedule"]
    assert re.search(r"^  schedule:\n    - cron: \"\d+ \d+ \* \* 1\"", on, re.M)
    steps = workflow[workflow.index("\njobs:") :]
    limit = re.search(r"^    timeout-minutes: (\d+)", steps, re.M)  # GitHub's default lets a stuck run last 6 hours
    assert limit and 94 < int(limit.group(1)) <= 180  # above the measured full run, under twice that
    assert steps.count("mutmut run") == 1
    assert re.search(r"run: \|\n\s+ulimit -v \d+\n\s+uv run mutmut run\n", steps)
    assert steps.index("mutmut run") < steps.index("scripts/mutation.py")
    assert "--check tests/mutation_baseline.json" in steps
    # every job of tests.yml gates the publish (tests/test_docker.py): the mutation job is not one of them
    assert "mutmut" not in (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
