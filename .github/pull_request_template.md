## Problem

<!-- What is wrong or missing, and how it shows (a check count, a date, a page). -->

## Change

<!-- What changes, file by file or rule by rule. Source for any P6 or standard behaviour (Oracle page, DECM metric ID, 14-Point item). -->

<!-- A value moved in tests/golden/standards.json, FLOORS or a standard TOML: one line each, as the
values workflow prints them (scripts/check_value_justification.py), e.g.
FLOORS/H10: 0.96 -> 0.97 — held-out corpus, test_p6_heldout at this commit
dcma/DCMA-01.target: "<= 5%" -> "<= 4%" — DCMA-EA PAM 200.1 §4.1
-->

## Verification

<!-- Commands run and what they printed. Say which tests skipped and why (no Java, reference files not fetched). -->

```
uv run pytest -rs
uvx ruff check src tests scripts
```

## Checklist

- [ ] No real schedule, activity name, project code, company name or file path in the diff, the tests or this description
- [ ] A moved number comes with a test that fails before and passes after, and its evidence (P6 export, held-out corpus, MPXJ, hand calculation)
- [ ] `tests/golden/standards.json` unchanged, or its diff reviewed and each moved value justified above (`ID: old -> new — source`)
- [ ] No `FLOORS` value lowered in `tests/test_p6_heldout.py`; a raised one justified above
- [ ] Docs updated where behaviour changed (`docs/standards.md`, `docs/formulas.md`, `docs/cpm.md`, `docs/backlog.md`)
