#!/usr/bin/env bash
# Fail if a range of commits adds a lint/test/complexity exception or touches a protected file.
# usage: no_exceptions.sh <base> [<head>]
set -u
cd /home/user/Xerscope
base=$1; head=${2:-HEAD}; fail=0
if [ "$head" = WORKTREE ]; then head=""; fi
added=$(git diff "$base" $head -- src tests scripts pyproject.toml | grep '^+' | grep -v '^+++')
markers='noqa|nosec|pragma|type: *ignore|fmt: *skip|fmt: *off|xfail|skipif|pytest\.skip|mark\.skip|importorskip|per-file-ignores|extend-ignore|^\+\s*ignore *=|KNOWN *=|# *C901|# *PLR|max-complexity|cognitive|radon|complexipy|ignore_imports|forbidden_modules|assert_frame_equal\(.*check_'
# a marker line removed and added with the same text is a move, not an addition
removed=$(git diff "$base" $head -- src tests scripts pyproject.toml | grep '^-' | grep -v '^---' | cut -c2- | sed 's/^[[:space:]]*//' | sort -u)
hits=$(printf '%s\n' "$added" | grep -E -i "$markers" | while IFS= read -r line; do
  text=$(printf '%s' "$line" | cut -c2- | sed 's/^[[:space:]]*//')
  printf '%s\n' "$removed" | grep -qxF -- "$text" || printf '%s\n' "$line"
done)
if [ -n "$hits" ]; then echo "EXCEPTION MARKERS ADDED:"; echo "$hits"; fail=1; fi
protected='tests/fitness_baseline.json tests/mutation_baseline.json tests/golden pyproject.toml tests/test_architecture.py tests/test_fitness.py tests/test_characterization.py tests/test_page_golden.py scripts/fitness.py scripts/duplication.py scripts/same_code.py scripts/accessibility.py .github'
touched=$(git diff --name-only "$base" $head -- $protected)
if [ -n "$touched" ]; then echo "PROTECTED FILES TOUCHED:"; echo "$touched"; fail=1; fi
# existing tests modified (allowed only if declared): list them
modified_tests=$(git diff --name-only --diff-filter=M "$base" $head -- tests)
[ -n "$modified_tests" ] && { echo "EXISTING TESTS MODIFIED (must be declared in the commit message):"; echo "$modified_tests"; }
deleted=$(git diff "$base" $head -- tests | grep -E '^-\s*(def test_|assert )' | head -5)
[ -n "$deleted" ] && { echo "TEST/ASSERT LINES REMOVED:"; echo "$deleted"; fail=1; }
[ $fail -eq 0 ] && echo "no_exceptions: clean ($base..$head)"
exit $fail
