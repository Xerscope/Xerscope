# ADR-0029: A folder typed in the Files window is read only under one root

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-20 (`9e824e7`, the root and its check; `4c86900`, the check rewritten as a guard CodeQL reads) |
| Scope | `src/xerscope/app/session.py` (`folder_root`, `folder_under_root`), `src/xerscope/app/files_window.py` (`_folder_boxes`), `src/xerscope/app/loading.py` (`_chosen_items`); `tests/test_folder_root.py`; `docs/user-guide.md`, "Environment variables" |
| Sources | `9e824e7` "Files window: a typed folder is read only under one root"; `4c86900` "Files window: the root check written as a guard CodeQL reads"; CodeQL alert "Uncontrolled data used in path expression" (path injection, high); [docs/refactor-front-plan.md](../refactor-front-plan.md) "Folder typed in the Files window: read under one root (decided, 2026-11-20)"; [README.md](../../README.md) "Web app" (configuration table); [SECURITY.md](../../SECURITY.md) |

## Context

The Files window ("Files and baseline", `files_window._window`) offers, on a local instance, an
upload field and a text field "…or read a folder" (key `files_folder`, drawn by
`_files_section`): a folder of the server
whose `.xer` files are listed for ticking (`_folder_boxes`) and read on Done
(`loading._chosen_items`). Both used to take the typed text as it came
(`Path(folder).expanduser()`), so the field listed and read any folder the app's process could
read.

A remote deployment never shows that field: with `XERSCOPE_DATA_LOCKED` the window offers no
folder field and no upload, only the files of `XERSCOPE_DATA` (ADR-0025). A local instance,
though, can be exposed to another user of the same machine (`xerscope app --host 0.0.0.0`), who
could then point it at any readable tree. CodeQL (ADR-0028) reported the two reads as path
injection, "Uncontrolled data used in path expression", severity high.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Dismiss the alert: pre-existing, local instance only | none | the alert stays standing, and a local instance shared on one machine still reads any readable tree |
| **One root: a typed folder is accepted only when its resolved path lies under `XERSCOPE_FOLDER_ROOT`, else the folder `XERSCOPE_DATA` names, else the home directory; refused with a message naming the root (chosen)** | two functions in `session.py`, two call sites, one README row | a user whose exports live on another drive sets the variable once |
| An allow-list of several roots | a list to parse and document | more configuration for a case one variable already covers |

The plan records the choice as the maintainer's: no CodeQL alert left standing.

## Decision

**The root.** `session.folder_root()` returns the first set of `XERSCOPE_FOLDER_ROOT`,
`XERSCOPE_DATA` and the home directory (`Path.home()`), with `~` expanded and every symbolic link
resolved (`os.path.realpath`).

**The check.** `session.folder_under_root(folder)` resolves the typed text the same way
(`realpath(expanduser(folder))`), then returns:

- `Path(root)` when the resolved path is the root itself;
- the resolved path when it starts with the root followed by the path separator
  (`root + os.sep`), so a sibling whose name only starts like the root (`/data/exportsx` for
  `/data/exports`) is outside;
- `None` otherwise, `..` included once resolved.

Normalisation first, then a prefix test returning the value only inside the branch where it
holds: the shape CodeQL recognises as a sanitiser. `9e824e7` wrote it as one compound condition
whose fall-through CodeQL could not read; `4c86900` gave it this form with the same results.

**The two call sites.** `files_window._folder_boxes` shows
`Folder outside <root>: set XERSCOPE_FOLDER_ROOT to read another tree` and lists nothing when the
check returns `None`; otherwise it lists the `.xer` files of the resolved path, and names its
widget keys by a SHA-256 of that path (the path never appears in the page's CSS classes).
`loading._chosen_items` reads nothing outside the root and keys the series' signature on the
resolved path.

## Consequences

Positive:

- A path typed in the page cannot walk the server's file system beyond one tree; the CodeQL
  alert is closed in the code, not dismissed.
- The default needs no setting: the demo folder and a usual `XERSCOPE_DATA` are inside the root
  (the whole-app digest on the demo series was identical before and after, `9e824e7`).

Negative:

- A folder on another drive or outside the home directory needs `XERSCOPE_FOLDER_ROOT`; the
  refusal says so.
- Uploads are not concerned: they are held in the session's memory and never written to disk.

## Verification

- `tests/test_folder_root.py::test_the_root_is_the_variable_then_the_data_folder_then_home`
  (home, then `XERSCOPE_DATA`, then `XERSCOPE_FOLDER_ROOT`).
- `tests/test_folder_root.py::test_a_folder_under_the_root_is_accepted_and_one_outside_or_climbing_out_is_not`
  (the root, a subfolder, `exports/..`, a folder elsewhere, `root/../elsewhere`, a sibling whose
  name starts like the root).
- `tests/test_folder_root.py::test_the_files_window_refuses_a_folder_outside_the_root`
  (`AppTest`: a demo folder outside the root typed in `files_folder` gives the "Folder outside"
  error and no file box).
- CodeQL (`.github/workflows/codeql.yml`, `security-and-quality`) on every pull request and push
  to `main`.

## References

- `src/xerscope/app/session.py`: `folder_root`, `folder_under_root`, `data_locked`.
- `src/xerscope/app/files_window.py`: `_window` (the window), `_files_section` (the `files_folder`
  field, absent when the data is locked), `_folder_boxes`.
- `src/xerscope/app/loading.py`: `_chosen_items`.
- [docs/user-guide.md](../user-guide.md), "Environment variables" (`XERSCOPE_FOLDER_ROOT`,
  `XERSCOPE_DATA_LOCKED`); [SECURITY.md](../../SECURITY.md) (in scope: a folder typed in the Files
  window read only under `XERSCOPE_FOLDER_ROOT`); [docs/architecture.md](../architecture.md) §7
  (`session.py`); [docs/refactor-front-plan.md](../refactor-front-plan.md), "Folder typed in the
  Files window: read under one root (decided, 2026-11-20)"; [CHANGELOG.md](../../CHANGELOG.md)
  `[Unreleased]`.
- Related: ADR-0016 (the Streamlit app), ADR-0024 (local first), ADR-0025 (the locked remote
  deployment), ADR-0028 (CodeQL).
