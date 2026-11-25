# ADR-0020: The Gantt 'Ask' field is a deterministic bilingual grammar over the file's own lexicon; no language model is deployed

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-06 (`71377b4`, #141: the Ask field, a keyword grammar with an optional model backend); the grammar in `analysis/ask/` from 2026-11-09 (`989308e`, #166); the language-model path removed on 2026-11-09 (`100f201`, #172) |
| Scope | `src/xerscope/analysis/query.py` (entry point), `src/xerscope/analysis/ask/` (`answer.py`, `bench.py`, `clauses.py`, `filters.py`, `funnel.py`, `generated.py`, `grammar.py`, `lexer.py`, `lexicon.py`, `parser.py`, `suggested.py`, `text.py`, `vocab.py`), `src/xerscope/app/views/gantt.py`, `app/loading.py` (`lexicon`, `session_lexicon`, `teach`), `src/xerscope/cli.py` (`ask-bench`); `tests/ask/` |
| Sources | `71377b4` "Gantt: an "Ask" field reads a sentence into the page's filters, a funnel and an answer (#141)"; `989308e` "Ask (1/4): grammar, comparisons, dates, constraints, logic, longest path (#166)"; `100f201` "Ask (5/5): remove the unused language-model path (#172)"; [docs/deploy.md §10](../deploy.md) (the measurement of the model); [docs/architecture.md §7](../architecture.md) "The Gantt "Ask" field: talking to the schedule without a model reading it"; [CONTRIBUTING.md](../../CONTRIBUTING.md) "Where a change goes"; Oracle P6 help 101248 (P6 Check Schedule: Late Activities, hard constraints) and 46278 (finish variance in working time), which "late" follows |

## Context

On the Gantt page a planner looks for "critical not started in civil works" and would otherwise
tick three widgets. A field that reads the sentence must keep xerscope's rule: every number traces
to a formula and a population (ADR-0010). The sentences are French or English, use the company's
own trade words and carry typos. The labels to match (WBS nodes, activity-code values, resources)
are the file's own and number in the hundreds on a real schedule.

The deployment runs on a NAS CPU (ADR-0024), without a GPU. A filter applied silently on a wrong
reading would show wrong rows with no warning, and a reading that cannot be scored cannot be held
by the test suite.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| A small generative model reading the sentence (and possibly the activities), served by llama.cpp in an optional compose service (built in `71377b4`, measured, removed in `100f201`) | a container, a model file, a network between them | Qwen3.5-2B Q4: 55 % of the held-out sentences understood against the grammar's 100 %, about 19 s a sentence on a 4-core x86 faster than the NAS; 17 of 20 answer summaries passed a value check and about a third of those misused a value (docs/deploy.md §10); answers vary with quantisation, build and prompt, so no floor can hold them |
| A model kept to routing over the file's labels, the grammar answering when it declines (`parse()` with an optional `Backend`, `71377b4`) | the same container, and a second path to test | at worst a wrong label; nothing in the app called it once the grammar covered the held-out sentences; only `ask-bench --url/--summary` reached it, code the suite could not prove (`100f201`) |
| **A deterministic bilingual keyword grammar over the file's own lexicon, scored on held-out sentences with floors (chosen)** | the grammar and its phrase tables to maintain in `analysis/ask/` | a synonym the file and the lexicon do not hold is not understood; it is named, and offered as a correction |

## Decision

**A sentence becomes a `Filter`, never a number.** `analysis/query.py` is the one entry point the
rest of xerscope imports; the grammar lives in `analysis/ask/`. `parse_keywords` reads the sentence
(`MAX_CHARS = 300` characters; the rest is named as left out) into a `Filter`: WBS node, statuses,
float categories, activity-code values, resources, milestones, LOE, search words, and `clauses` for
what no widget says. A filter is a set the user could have built with the page's widgets, and is
intersected with them.

**The lexicon is the file's own.** `ask/vocab.py:vocabulary` builds a `Vocabulary` once per update
from the snapshot: WBS nodes with their code and name, activity-code values and types, resources,
Activity IDs, the words of the activity names, whether the file has milestones and LOE, the data
date. Words of the activity names found under one WBS node alone become that node's aliases. On top
of it come the company's trade words (`ask/lexicon.py:load_lexicon`, from the folder
`XERSCOPE_LEXICON` names, none shipped with the package, ADR-0021) and the files' own variants
(`ask/generated.py`: case and accents, French or English plurals, an abbreviation with its dot).

**The grammar.** `ask/lexer.py` matches the grammar's phrases first, longest first, then a typo on
a grammar phrase, then the file's labels and name words. `ask/parser.py` is a recursive descent:
juxtaposition is AND, OR binds tighter than AND, NOT is the complement in the page's population,
parentheses group (`ask/grammar.py`: `Atom`, `Not`, `And`, `Or`). Comparisons on float, durations
and % complete, and dates counted from the data date are clauses (`ask/clauses.py`). "Late" reads
P6 Check Schedule's Late Activities (P6-12): open activities forecast to finish later than their
baseline finish, in working time, the planned finish standing in where the page's baseline has
none (`ask/funnel.py:_late`); "negative float" is a float comparison. Both languages are read by one grammar;
the answer is given in the question's language (`query.language`).

**Nothing is silent.** A word nothing holds is set aside and named in the answer ("The word ... is
in neither this file nor the lexicon."), the other filters apply, and the page offers the closest
labels of the file (`query.suggestions`, difflib from `SUGGEST = 0.5`); a click teaches the word
for the session (`loading.teach`, `query.learn`) and appends the correction to `suggested/`
(`ask/suggested.py`). A typo close enough (`FUZZY = 0.85`) is read at once at a lower confidence;
the confidence is 1.0 for exact phrases, the weakest fuzzy ratio otherwise, lowered when two WBS
nodes score within `MARGIN = 0.05`; under `SURE = 0.9` the page says "unsure". A word that names
several activity-code values or types is filtered on none: the page asks back (`Filter.clarify`).
A sentence of which nothing was understood but words were left out keeps no row, never every
row.

**The answer is a trace and a template.** The page runs the filter as a `populations.Funnel`
(`ask/funnel.py:apply`): one named step per filter understood, source `"ask"` (ADR-0010). The
caption (`query.funnel_line`) and the "Population, step by step" table are the funnel; the count is
the last step's `left`. `query.answer` says it in one sentence from a template over columns of the
frame: the count, what was asked, the worst total float and the latest finish. Each understood
filter is a chip whose × drops it (`query.without`). `query.facts` (the funnel's steps and counts,
the worst floats: values, never a name) remains as what a model would be given; nothing in the app
calls it.

**Measured, with floors.** `xerscope ask-bench PATH` scores the grammar on sentences with known
filters (`--cases`, repeatable), on the file's own lexicon (`--self`, `query.coverage`: the labels
the grammar cannot name), with a lexicon folder (`--lexicon`) and on the anonymised copy of a real
file (`--anonymize`). `tests/ask/dev.toml` holds the sentences the grammar was tuned on;
`tests/ask/heldout.toml` sentences written before the grammar was run on them, never used to tune
it; `tests/ask/cases.toml` the grammar cases with hand-written filters.
`tests/test_ask_bench.py` holds the floors: `FLOORS = {"dev": 1.00, "heldout": 1.00}` and
`UNDERSTOOD = 1.00`; a change that lowers one fails.

**No model, no network.** The model client, its prompts and schema, `ask-bench --url / --key /
--ca / --summary` and the compose service were removed (`100f201`). No module of `src/` imports a
network library.

## Consequences

Positive:

- Every count the Ask field gives is a funnel of named steps over the page's rows; the user sees
  what each understood word removed.
- The grammar answers in milliseconds on the whole lexicon, on the NAS CPU, with no container,
  model file or network access.
- Its accuracy is a number the suite holds: a change cannot lower the dev, held-out or cases
  floors.

Negative:

- Synonyms the file does not hold ("mécanique" for "Mechanical & electrical") need the company's
  lexicon (ADR-0021); the generic test lexicon is `tests/asklex.py`.
- Every new sentence shape is grammar code in `analysis/ask/` (CONTRIBUTING.md: "A word or phrase
  of the Gantt Ask field" goes there, never in a page).
- A new model measurement needs a measurement client again: `ask-bench` scores the grammar only
  ([docs/backlog.md](../backlog.md), "App": "Gantt "Ask", a model", which lists what would change
  the measurement).

## Verification

- `tests/test_ask_bench.py::test_share_of_sentences_right_never_drops` (dev and held-out floors),
  `::test_share_of_the_grammar_cases_understood_never_drops`,
  `::test_coverage_names_what_a_file_needs_in_its_lexicon`.
- `tests/test_fuzz_ask.py::test_any_sentence_is_read_applied_and_answered`,
  `::test_every_phrase_of_the_grammar_alone_is_read_applied_and_answered`,
  `::test_the_sentences_use_the_grammar_of_both_languages` (Hypothesis; `HYPOTHESIS_PROFILE=ci`
  runs 1000 examples).
- `tests/test_query.py::test_filter_runs_as_a_funnel_of_named_steps`,
  `::test_an_unknown_word_gets_the_closest_labels_and_can_be_taught`,
  `::test_a_clause_holding_an_unknown_word_is_not_applied_and_is_named`,
  `::test_no_lexicon_file_is_packaged_or_tracked_under_src`.
- `tests/test_ask_limits.py` (a sentence naming many nodes, and the labels offered for unknown
  words, each under a second on a large file); `tests/test_ask_ambiguous_codes_blind.py`,
  `tests/test_ask_value_two_types_blind.py` (the question asked back).
- `tests/test_app.py::test_gantt_ask_asks_which_code_value_then_filters_on_the_one_clicked`.
- `tests/test_docker.py::test_nothing_in_src_reaches_the_network` (no `urllib`, `socket`,
  `http.client`, `requests`, `httpx`, `aiohttp` or `websocket` import in `src/xerscope`).

## References

- `src/xerscope/analysis/query.py`: module docstring, `facts`, the re-exported API (`parse_keywords`,
  `apply`, `funnel_line`, `answer`, `language`, `suggestions`, `learn`, `without`, `coverage`,
  `score`, `understood`).
- `src/xerscope/analysis/ask/parser.py` (`parse_keywords`, `MAX_CHARS`), `ask/lexer.py`,
  `ask/grammar.py`, `ask/clauses.py`, `ask/filters.py` (`Filter`, `Choice`), `ask/funnel.py`
  (`apply`), `ask/answer.py` (`answer`, `SUGGEST`), `ask/text.py` (`FUZZY`, `MARGIN`, `SURE`),
  `ask/vocab.py` (`Vocabulary`, `vocabulary`), `ask/bench.py`.
- `src/xerscope/cli.py`: `_args_ask_bench`, `_cmd_ask_bench` (`xerscope ask-bench --help`).
- `tests/ask/dev.toml`, `tests/ask/heldout.toml`, `tests/ask/cases.toml`, `tests/asklex.py`.
- [docs/deploy.md](../deploy.md) §10; [docs/architecture.md](../architecture.md) §7, "The Gantt
  "Ask" field".
- Related: ADR-0010 (the funnel), ADR-0016 (the Gantt page), ADR-0021 (the lexicon folders),
  ADR-0024 (local-first deployment).
