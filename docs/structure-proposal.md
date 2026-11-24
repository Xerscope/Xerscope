# Proposition : ranger l'arborescence de `src/xerscope` et `tests/`

Statut : proposition. Rien n'a été modifié dans le dépôt (vérifié à `dd6c71b`). Périmètre : des déplacements et des découpages sans changement de comportement, sans nouvelle dépendance, sans plugin, sans injection de dépendances et sans moteur générique.

## Problème

Le dépôt n'est pas désordonné dans son ensemble. Les couches (`xer`, `store`, `analysis`, `viz`, `app`, `cli`) sont fixées par ADR-0001 et vérifiées par `tests/test_architecture.py`. Les vrais problèmes sont localisés et mesurés.

1. **`xer/model.py` (1728 lignes, MI 4.4, rang C) regroupe cinq responsabilités** : les listes de colonnes et les tables de codes P6, les lecteurs de valeurs, le contrat et la classe `Snapshot`, la sélection de projet avec l'en-tête, et la chaîne de construction. Quatorze modules d'analyse et d'app importent des tables et des lecteurs au même endroit que les internes de construction.
2. **`cli.py` (1037 lignes, MI 5.07, rang C)** :
   - Environ un tiers du fichier (L653-993) est la logique du lexique Ask et d'`ask-bench`, pas du câblage d'arguments.
   - `APP_PATH` (L16) dépend de l'emplacement de `cli.py`.
   - Ses 43 imports paresseux sont relatifs (`from .export import …`, `from .crosscheck import …`, `from .app import diagnostic`…). Leur cible dépend donc elle aussi de l'emplacement du fichier.
3. **Le CLI charge Streamlit pour `pv-compare`.** `app/diagnostic.py:38` prend `as_dates` dans `ui`, qui importe streamlit et enregistre le composant Gantt. Or `as_dates` est défini dans `table_filters.py:27`, qui n'importe pas Streamlit.
4. **Les sérialiseurs CSV et zip génériques vivent dans le module Power BI** (`export.py`). `anonymize` dépend donc de `export`, et à travers lui de `store`.
5. **`analysis/explain.py` (981 lignes) mêle deux sujets** :
   - l'explication d'un `CheckResult` (L1-313) ;
   - un catalogue de textes de page (L314-981).
   Le catalogue contient 15 citations `fichier:ligne` (`charts.py:70-83`, `config.py:12`, `store.py:231-236`, `ui.py:400-405`, `debug.py:379-381`…), dont certaines sont déjà périmées.
6. **Des fichiers de test servent de bibliothèques** à d'autres tests : 12 modules `test_*` sont importés par d'autres tests. De plus, `conftest.py` sert à la fois de conftest et de module d'aides. Tant que ce point n'est pas réglé, aucun test ne peut changer de dossier.
7. **Des dettes plus petites** :
   - `task_filters` importe `fold` via la façade Ask.
   - `fitness_baseline.json` est en partie périmé (voir PR 0a).
   - `scripts/accessibility.py:41` donne une liste de pages périmée.
   - La docstring de `app/state.py:1` est fausse.

Certaines choses ne sont **pas** des problèmes à corriger par un déplacement : la taille de `cpm.py` vient de la seule classe `_Run`, et celle d'`anonymize.py` de la seule classe `Anonymizer`. Elles relèvent de refactorings internes de méthodes.

## Options

| Option | Ce qu'elle fait | Coût | Limite |
|---|---|---|---|
| **A. Statu quo et petits correctifs** | Seulement les points 3 et 7, plus les citations de lignes dans `explain` | 4 à 5 PR de moins de 60 lignes | `model.py` et `cli.py` restent en rang C. Les tests ne peuvent toujours pas être déplacés. |
| **B. Découpages ciblés dans les couches existantes (recommandée)** | A, plus : découpage de `model.py` dans `xer/`, `cli` devient un paquet d'où sortent `ask` et le lexique, sérialiseurs vers `csv_safe`, catalogue de textes sorti d'`explain`, deux sous-paquets d'app (`baseline/`, `debug/`), kits de test | Environ 30 à 35 PR de 400 lignes au plus, dont 6 à 7 PR de docstrings préalables. Une PR (`READINGS`) dépasse le budget (Q1). Les chemins d'import changent dans environ 40 tests et environ 30 fichiers de doc. | `cpm.py` reste un module unique de rang C (le moteur, environ 2000 lignes). |
| **C. Regroupement complet par domaine** | B, plus : `analysis/{engine,forensics,builtin,progress}/`, `app/{widgets,sidebar}/`, tests en miroir du code, sous-dossiers de tests | Plus de 50 PR. Environ 150 sites d'import dans environ 90 fichiers, 6 fichiers de configuration indexés par chemin, 88 chemins de tests cités dans 52 fichiers. | Le gain est surtout cosmétique. Le miroir des tests serait arbitraire : 38 tests importent seulement `analysis`, et beaucoup en traversent 3 ou 4. Le risque d'un patch silencieusement manqué augmente. |

## Choix proposé : option B

Sources :
- **ADR-0001 et `tests/test_architecture.py`.** On garde les couches au sommet et on regroupe par fonctionnalité à l'intérieur d'une couche. Aucun paquet de fonctionnalité ne traverse les couches. On parle parfois de « package by layered feature » (phauer.com) ; cette formulation n'a pas pu être revérifiée hors ligne, et la règle repose de toute façon sur ADR-0001.
- **`scripts/same_code.py`.** Une définition de premier niveau se déplace sans changement. Une classe compte pour une seule définition, donc `_Run` ne se découpe pas. Limite à connaître : dans une fonction, `same_code` compare les imports par les noms qu'ils apportent, pas par le module. Un import relatif dont la cible change sans bruit n'est donc pas détecté (voir PR 7).
- **PEP 8.** Des noms de sous-paquets courts et sans tiret bas, et `__all__` pour l'API publique.
- **PEP 420 et le guide de packaging.** Chaque nouveau sous-paquet de code reçoit un `__init__.py` ordinaire, vide en dehors de sa docstring. `app/views/`, `sheets/`, `standards/` et `static/` restent des dossiers sans `__init__.py`.
- **pytest goodpractices.** Cette page recommande `--import-mode=importlib` pour les nouveaux projets. On garde quand même le mode `prepend`, parce que 41 lignes `from conftest import` en dépendent. On n'ajoute pas `pythonpath = ["tests"]` : avec `prepend`, `tests/` est déjà sur le chemin tant que les tests restent à plat. Le réglage ne servirait qu'à Q9, qui est reportée.
- **Doc `pickle` et caches.**
  - `Snapshot` traverse les processus `spawn` d'`app/reading.py`, en mémoire seulement. Une classe y est retrouvée par son nom qualifié.
  - `reading.py` n'importe que `xerscope.store` et `xerscope.xer`. Il suffit donc que `xer/snapshot.py` s'importe sans Streamlit.
  - Aucun pickle n'est stocké sur disque, et il n'y a ni `st.cache_data` ni cache persistant indexé par chemin de module.

Règle transversale : **pas de shim de compatibilité aux anciens chemins.**
- Les monkeypatchs des tests visent des globales de module (`model.file_baseline`, `cpm._comparison`, `cli.LEXICON_MAX_BYTES`, `'xerscope.analysis.checks.run_metric'`, etc.). Un shim leur ferait patcher une copie sans effet, sans aucun échec visible.
- Un import gardé seulement pour réexporter est aussi signalé par F401.
- On met donc à jour les importeurs dans la même PR.
- Seule exception : les façades existantes (`xer/__init__`, `analysis/__init__`, `analysis/query`), qui continuent de réexporter.
- `cli/__init__` n'importe de `common` que ce qu'il utilise lui-même (`_expand`, `_write_csv`, `_add_*`, `_when`). Il n'importe pas `INPUT_ERROR`, que seul `fail` utilise : `test_cli.py:17-20` passe à `cli.common.INPUT_ERROR`.

## Vérification (pour chaque PR)

```
uv run python scripts/same_code.py origin/main          # ne doit lister que des déplacements ; --ignore-docstrings seulement pour une PR de docstrings
uv run python scripts/duplication.py                    # rapport identique avant/après
uv run python scripts/fitness.py --check tests/fitness_baseline.json   # après régénération --out si une clé est nouvelle ou renommée, justification dans la PR
uv run pytest -n auto --dist loadfile                   # suite complète
git diff --exit-code origin/main -- tests/golden/       # goldens inchangés
uv run pytest --collect-only -q | sed 's#^tests/[^:]*::##' | sort > nodes.txt   # même liste avant/après (PR de tests)
uv run python scripts/oracle_report.py                  # mêmes totaux (PR de tests)
uv run ruff check --select D <nouveaux modules>         # un nouveau fichier n'a aucune entrée per-file-ignores
```

Justification des valeurs (`check_value_justification.py`) : `_worse` compte une clé nouvelle à partir de 0, ou du rang A. Tout module déplacé ou renommé exige donc, même pour un déplacement pur, une ligne de description de PR pour chaque mesure non nulle (`cc_max`, `cognitive_max`, et `mi_rank` s'il n'est pas A).

Contrôles supplémentaires selon la zone touchée :
- **CPM et CLI crosscheck** :
  - `uv run pytest tests/test_crosscheck_mpxj.py tests/test_reference.py` avec Java ;
  - puis `XERSCOPE_REQUIRE=reference,p6-corpus`, pour qu'un chemin de données faux échoue au lieu d'être ignoré.
  - Le CI par défaut ne lance jamais `xerscope crosscheck` : `test_cli.py` ne l'appelle pas, et les tests MPXJ s'ignorent sans Java.
- **App** : `uv build --wheel` dans le scratchpad, puis comparer `unzip -l` avant et après. On vérifie ainsi que `.streamlit/`, `static/`, `style.css` et `gantt.js`/`gantt.css` sont bien livrés.

---

## 1. Arborescence cible

Légende :
- `=` : inchangé ;
- `+` : nouveau fichier (code déplacé à l'identique) ;
- `~` : reste sous le même nom mais allégé ;
- `>` : déplacé (ancien chemin -> nouveau chemin) ;
- `(opt)` : optionnel, soumis à décision.

```
src/xerscope/
├── __init__.py                      =
├── config.py                        =
├── csv_safe.py                      ~ reçoit Fmt, CSV_FLOAT_FORMAT, csv_bytes, _bytes, zip_frames (depuis export.py)
├── export.py                        ~ garde export_tables, write_tables, zip_tables ; importe Fmt et _bytes de csv_safe
├── anonymize.py                     =
├── store.py                         = (seules les lignes d'import changent)
├── sample.py                        =
├── crosscheck.py                    = (opt : replié dans verify/__init__, voir Q5)
├── cli/                             > cli.py -> cli/__init__.py
│   ├── __init__.py                  ~ main, COMMANDS, _cmd_app, APP_PATH, autres sous-commandes
│   ├── __main__.py                  + 2 lignes et une docstring : garde `python -m xerscope.cli` (voir PR 7)
│   ├── common.py                    + fail, INPUT_ERROR, _expand, _add_*, _write_csv, _when
│   └── ask.py                       + ask-bench (L653-809) et lexicon (L811-993)
├── xer/
│   ├── __init__.py                  = (façade ; ses imports pointent vers les nouveaux modules)
│   ├── parser.py                    =
│   ├── codes.py                     + tables STATUS…SCHEDULE_OPTIONS (L106-195), ScheduleOption, constraints_label (L196)
│   ├── values.py                    + _blank_to_na, forecast_dates, to_datetime, to_number, _parse_date, percent_complete,
│   │                                  _ensure_cols, _require, _warn_unknown_codes, _unique (L202-313), EARLIEST/LATEST_DATE
│   ├── snapshot.py                  + listes de colonnes TASK_DATE_COLS…LABOR_COLS (L41-105), contrats de colonnes,
│   │                                  listes CODE/UDF, FileBaseline, file_baseline, _chain, Snapshot
│   ├── projects.py                  + _task_table, _project_table (L314-339), baseline_copies, _select_project, _file_projects,
│   │                                  _data_date, projects_text, HEADER_TABLES, FileHeader, read_header
│   ├── model.py                     ~ _BuildInputs, étapes de construction, _check_snapshot_columns, build_snapshot
│   ├── calendar.py                  =
│   ├── validate.py                  =
│   ├── pmxml.py                     = (opt : xer/pmxml/__init__.py + scan.py, voir Q6)
│   └── pmxml_scan.py                =
├── verify/                          = (__init__, mpxj_reader, mpxj_cpm, p6_corpus, shapes)
├── analysis/
│   ├── __init__.py                  = (même ordre d'import : dcma, decm, integrity, p6)
│   ├── explain.py                   ~ L1-313 : CheckResult -> Explanation, critical_definition
│   ├── readings.py                  + L314-981 : constantes de source, SPI_WINDOW_READING, *_READING, READINGS, schedule_reading
│   ├── cpm.py                       ~ (opt) sans critical_path_test, voir PR 14
│   ├── critical_path.py             + (opt) critical_path_test, CptResult, _DelayOutcome et aides (cpm.py:2268-2497)
│   ├── baseline.py, populations.py, wbs.py, task_filters.py, resource_placement.py,
│   │   rules.py, standards.py, checks.py, audit.py, integrity.py, evm.py, progress.py,
│   │   changelog.py, forensics.py, longest_path.py, baseline_resolution.py, query.py   =
│   ├── ask/ (13 modules)            =
│   └── dcma/, decm/, p6/            =
├── viz/                             = (charts.py, gantt.py, gantt.js, gantt.css)
├── app/
│   ├── __init__.py                  =
│   ├── streamlit_app.py, theme.py, style.css, static/, .streamlit/, views/ (11 pages)   =
│   ├── session.py, cache.py, downloads.py, sets.py, state.py, ui.py                    =
│   ├── glossary.py, table_filters.py, code_picker.py, explanation_panel.py, task_panel.py  = (opt widgets/, Q8)
│   ├── loading.py, files_window.py, baseline_warnings.py, reading.py                   = (opt sidebar/, Q8)
│   ├── baseline/                    +
│   │   ├── __init__.py              + (docstring seule)
│   │   ├── baseline_file.py         > app/baseline_file.py
│   │   ├── baseline_export.py       > app/baseline_export.py
│   │   ├── baselines.py             > app/baselines.py
│   │   ├── baseline_window.py       > app/baseline_window.py
│   │   └── xml_baselines.py         > app/xml_baselines.py
│   └── debug/                       +
│       ├── __init__.py              + (docstring seule)
│       ├── diagnostic.py            > app/diagnostic.py
│       ├── expected_finish_forms.py > app/expected_finish_forms.py
│       └── recalculation_departures.py > app/recalculation_departures.py
├── sheets/P6/*.md                   =
└── standards/*.toml                 =

tests/
├── conftest.py                      ~ fixtures, hooks, variables d'environnement, profils hypothesis
├── xerkit.py, rulekit.py, pmxmlkit.py, file_projects.py, asklex.py   =
├── appkit.py                        + aides AppTest (conftest.py:101-220) ; APP, _ok, app (test_app) ; PAGES (test_page_golden)
├── evidencekit.py                   + missing, REFERENCE_HINT, P6_CORPUS_HINT, mpxj_or_skip (depuis conftest)
├── cpmkit.py                        + random_network (depuis test_cpm_properties)
├── evkit.py                         + planned, progressed, DAY_MIN, SHAPES, random_update (depuis test_earned_schedule, test_ev_contracts)
│                                      + données EVM de test_evm_weekly et test_evm_code_filter
├── codekit.py                       + GLOBAL_P1/P2, PROJECT_P1, _code_snapshot, _code_text, _label (depuis test_code_types_blind)
├── glossarykit.py                   + PAGES (depuis test_glossary ; liste distincte, sans forensics)
├── pvkit.py, referencekit.py        + BASELINE, UPDATE, WED (test_pv_p6) ; REFERENCE_DATA, reference_names (test_characterization)
├── test_*.py (140)                  = à plat (les sous-dossiers relèvent de Q9)
├── reference/, golden/, ask/        =
└── fitness_baseline.json, mutation_baseline.json   =
```

Raison de chaque déplacement, en une ligne :
- `xer/model.py` -> `xer/codes.py` (tables, `ScheduleOption`, `constraints_label`) : ce que 14 modules importent réellement, sans tirer les internes de construction.
- `xer/model.py` -> `xer/values.py` : les lecteurs de valeurs sont la base commune ; on les place au plus bas pour éviter les cycles.
- `xer/model.py` -> `xer/snapshot.py` : le contrat de données lu par `store`, `analysis` et `app`, listes de colonnes comprises (`store.py:18` importe `LABOR_COLS`, `ASSIGNMENT_COLS_MODEL` et `REL_COLS_MODEL`). `Snapshot` et `file_baseline` restent dans le même module, parce que le monkeypatch l'exige.
- `xer/model.py` -> `xer/projects.py` : la sélection de projet et l'en-tête forment un sujet distinct, avec son propre point d'entrée `read_header`. `_task_table` et `_project_table` partent avec lui, sinon on a un cycle `projects <-> model`.
- `cli.py` -> `cli/__init__.py` : rend possible la sortie de la logique Ask ; la clé `LAYERS` reste `cli`.
- `cli.py` -> `cli/common.py` : les aides partagées doivent quitter `__init__` pour éviter le cycle `__init__` <-> `ask`.
- `cli.py` -> `cli/ask.py` : environ 340 lignes de logique de lexique et de benchmark, qui restent dans la couche cli (écriture de fichiers, affichage).
- `export.py` -> `csv_safe.py` (sérialiseurs) : « le seul écrivain CSV » selon sa propre docstring. `anonymize` ne dépend plus de `export` ni de `store`.
- `analysis/explain.py` -> `analysis/readings.py` : un découpage par consommateur (les pages de l'app), pas par standard.
- `app/{baseline_*,baselines,xml_baselines}.py` -> `app/baseline/` : les imports privés croisés restent dans un seul paquet. `BASELINE_DOMAIN` de `test_architecture` ne le justifie qu'en partie, car il contient aussi `baseline_warnings`, qui reste à la racine.
- `app/{diagnostic,expected_finish_forms,recalculation_departures}.py` -> `app/debug/` : un trio sans Streamlit (après 0d), utilisé par la page Debug et par `cli pv-compare`.
- `tests/conftest.py:101-220` -> `tests/appkit.py`, et les noms partagés des `test_*` -> des kits : un test ne doit pas être une bibliothèque. C'est le prérequis de tout déplacement futur.

## 2. Fichiers à découper

| Fichier | Contenu qui part | Destination | Nature |
|---|---|---|---|
| `xer/model.py` L106-196 | tables de codes P6, `ScheduleOption`, `constraints_label` | `xer/codes.py` | déplacement pur, précédé d'une PR de docstrings (D205, D102 : L141, L152) |
| `xer/model.py` L202-313 | lecteurs de valeurs, `_ensure_cols`, `_require`, `_unique`, `_warn_unknown_codes` (mêmes noms) | `xer/values.py` | déplacement pur, précédé d'une PR de docstrings (D205, D209, D103, D401 : L207, L221, L307, L362) |
| `xer/model.py` L41-105 et L392-513 sauf `_check_snapshot_columns` (L476) | listes de colonnes, contrats de colonnes, listes CODE/UDF | `xer/snapshot.py` | déplacement pur |
| `xer/model.py` L514-692 et `_chain` (L799) | `FileBaseline`, `file_baseline`, `Snapshot` | `xer/snapshot.py` | déplacement pur, précédé d'une PR de docstrings (D102, D205, D209 : L528-683) |
| `xer/model.py` L314-339, L999-1145, L1579-1617 | `_task_table`, `_project_table`, sélection de projet, `_data_date`, `FileHeader`, `read_header` | `xer/projects.py` | déplacement pur, précédé d'une PR de docstrings (D205, D209, D401 : L1000-1111, L1606) |
| `cli.py` | `fail`, `INPUT_ERROR`, `_expand`, `_add_*`, `_write_csv`, `_when` | `cli/common.py` | déplacement pur |
| `cli.py` L811-993 | lexicon (`_build_lexicon`, `_lexicon_report`, `_purge_suggestions`, `_lexicon_export`, `LEXICON_MAX_BYTES`…) | `cli/ask.py` | déplacement pur, précédé d'une PR de docstrings (D205, D209, D401 : L675-981) |
| `cli.py` L653-809 | ask-bench (`_anonymised_bench`, `_anonymised_case`) | `cli/ask.py` | déplacement pur |
| `cli.py:16` | `APP_PATH` : `Path(__file__).parent` -> `.parent.parent` | `cli/__init__.py` | **modification d'une ligne**, signalée par `same_code`, à annoncer |
| `cli.py`, 43 imports paresseux relatifs | `from .export …`, `from .crosscheck …`, `from .app …`, etc. | `from xerscope.…` absolu | **modification de lignes d'import**, invisible pour `same_code`, à annoncer et à contrôler par grep |
| `export.py` L25 et L37-82 | `Fmt`, `CSV_FLOAT_FORMAT`, `csv_bytes`, `_bytes`, `zip_frames` | `csv_safe.py` | déplacement pur ; `export` réimporte `Fmt` et `_bytes` (nom privé) pour `write_tables` et `zip_tables` |
| `analysis/explain.py` L314-981 | catalogue de textes de page | `analysis/readings.py` | déplacement pur en 3 PR, de bas en haut, précédé d'une PR de **modification de valeurs** (citations) et d'une PR de docstrings (D205, D209, D401 : L447, L930, L954, L972) |
| `analysis/cpm.py` L2268-2497 (opt) | `critical_path_test` et ses aides | `analysis/critical_path.py` | déplacement pur ; `_Run`, `_early` et `_late` ne bougent pas |
| `tests/conftest.py` L101-220 | aides AppTest ; `missing` et les indications | `tests/appkit.py`, `tests/evidencekit.py` | déplacement pur ; `same_code` ne couvre pas `tests/`, la preuve vient de la détection de renommage de git et de la liste des nœuds collectés |
| 12 modules `test_*` importés par d'autres tests | noms partagés | `cpmkit`, `evkit`, `appkit`, `codekit`, `glossarykit`, `pvkit`, `referencekit` ; `test_file_baseline._series_and_export` vers un kit ou `appkit` | déplacement pur (même preuve) |

Règle de la dette docstring :
- pyproject dit « A new file has no entry; … no line gains a rule », et CONTRIBUTING L203 dit la même chose.
- Un nouveau module n'a donc aucune entrée `per-file-ignores`.
- `ruff --select D` sur le code à déplacer donne environ 15 nouvelles paires, alors qu'il en reste 7 sous `MAX_DEBT` (267 permises, 260 utilisées).
- Chaque découpage est donc précédé d'une PR qui corrige les docstrings du code concerné, à son emplacement actuel (`same_code --ignore-docstrings`). D209 se corrige automatiquement ; D401 et D205 se corrigent à la main.
- Alternative : ne déplacer que du code qui passe déjà les règles D.

Découpages qui changent du code et ont donc chacun leur PR, toujours sans changement de comportement :
- `app/diagnostic.py:38` importe `as_dates` depuis `table_filters` : un import seul, `same_code` reste vert, et `APP_EDGES` est mis à jour. Vérifié : importer `table_filters`, `expected_finish_forms` et `recalculation_departures` ne charge pas streamlit.
- `analysis/task_filters.py:19` importe `fold` depuis `.ask.text` (une ligne).
- Les textes de `READINGS` citent des fonctions ou des constantes qui existent (par exemple `SPI_WINDOW_READING`, `charts.<fonction>`) ou perdent leurs numéros de ligne. **`charts.LABEL_DECIMALS` n'existe pas** : « trois décimales » (`charts.py:248`) n'a pas de constante à nommer, et en ajouter une serait un changement de code. C'est une **valeur affichée qui change** : il faut vérifier `test_readings`, et `pages.json` ne contient pas ces textes.
- La docstring de `app/state.py:1` (« page kit ») : PR de docstring.

## 3. Ce qui ne bouge pas, et pourquoi

- **`app/streamlit_app.py`, `.streamlit/config.toml`, `static/`, `style.css`, `theme.py`, `views/`** :
  - Leurs chemins sont calculés depuis `__file__` (`VIEWS`, `parents[2]`, `theme.STYLE`/`STATIC`) et depuis `cli.APP_PATH` (cwd). `config.toml` utilise des URL `app/static/...`.
  - Environ 15 tests construisent `AppTest` depuis `app/streamlit_app.py`.
  - Les noms de fichiers des pages sont des URL et les clés de `tests/golden/pages.json`. `scripts/accessibility.py` clique `a[href$='/name']`.
- **`viz/`** : petit et cohérent. `gantt.js`/`gantt.css` doivent rester à côté de `gantt.py` (`files(__package__)`, `test_viz.py:346,368`).
- **`xer/calendar.py`** : indexé par chemin dans le baseline de mutation et dans `[tool.mutmut] source_paths`.
- **`xer/parser.py`** : ADR-0002, fuzzing, 6 tests.
- **Le nom de couche `xer`** : pas de `xer/formats/`. Le nom est fixé dans `LAYERS`, dans les contrats fitness et dans ADR-0001, et il est utilisé par environ 74 imports.
- **`analysis/cpm.py` (classe `_Run`)** :
  - On ne peut pas la découper par phase de façon prouvable : une classe compte pour une seule définition dans `same_code`, et des mixins frôleraient le « moteur générique ».
  - Ses noms privés (`_Run`, `_Axes`, `_date_range`, `FLOAT_TYPE`…) sont importés par `verify/mpxj_cpm.py` et par des tests.
  - Pas de `analysis/engine/` : il faudrait modifier environ 45 imports, plus `LAYERS 'analysis.cpm'`, sans aucun gain de structure.
- **`analysis/{baseline,populations,rules,standards,checks,audit,wbs,task_filters,query}.py`** : presque tout les importe. `analysis.wbs.ROOT` est fixé dans `LAYERS['viz']`, et `query.py` reste la façade d'Ask (environ 19 importeurs).
- **`analysis/{p6,dcma,decm}/` et `integrity.py`** : un regroupement `builtin/` serait cosmétique. Il toucherait 7 clés fitness avec clones (lues comme des régressions « (new) »), `LONG`, les per-file-ignores et l'ordre d'enregistrement des règles.
- **`analysis/evm.py` et `progress.py`** : un découpage forcerait un import croisé entre paquets (`progress` -> `evm` en import paresseux), et `progress.py` figure dans le baseline de mutation. Sortir `pv_p6_comparison` reste possible plus tard (environ 500 lignes de diff, deux PR).
- **`rules.py`** : on garde `AnalysisContext` (environ 24 importeurs) et les fonctions `@rule`, qui s'enregistrent à l'import dans un ordre donné (voir Q7).
- **`anonymize.py`** : son rang C vient d'une classe. Le seul remède est un refactoring de méthodes, hors périmètre. Pas de paquet `privacy/`.
- **`config.py`, `store.py`, `sample.py`, `csv_safe.py` au sommet** : une seule responsabilité chacun, déjà au rang A. Les envelopper dans un paquet changerait les clés `LAYERS`, les contrats et une dizaine de citations, pour rien.
- **`app/session.py`, `cache.py`, `downloads.py`, `sets.py`, `state.py`** : la racine de l'app. Placer `cache` ou `baseline_warnings` dans `baseline/`, ou `sets` dans `widgets/`, créerait un cycle entre paquets.
- **`app/ui.py`** : reste à la racine. `runtime_table` calcule `parents[1]` et `test_app.py:2885` utilise la même formule, si bien qu'une erreur passerait inaperçue. Les découpages colonnes et formatage sont reportés (Q8).
- **`scripts/`** : 7 scripts, 1 267 lignes, à plat.
- **Dans `tests/`** :
  - `test_architecture.py` : importé par `fitness.py:40` et cité dans la doc.
  - `test_p6_heldout.py`, `golden/`, `fitness_baseline.json`, `mutation_baseline.json` : chemins codés en dur dans `check_value_justification.py`, `CODEOWNERS` et `mutation.yml`.
  - `test_p6_checksched.py` : cité dans le champ `source` de `p6.toml`, donc dans `pages.json`.
  - `test_crosscheck_mpxj.py`, `test_reference.py` : `tests.yml:168`.
  - `reference/` : clés de cache CI, CONTRIBUTING, `cli.py`, `dcma.toml`.
  - `test_app.PAGES` (`"views/*.py"`, avec forensics) : aucun autre test ne l'importe, il reste dans `test_app`.
- **Pas d'`__init__.py` dans `tests/`** : sinon `reference` deviendrait `tests.reference`.
- **Données de paquet, chemins de pages, baseline de mutation** : hatch livre tout ce qui est sous `src/xerscope`. `standards`, `sheets`, `files(__package__)` dans viz, le chemin `views/`, `pages.json` et le baseline de mutation ne sont pas touchés par les déplacements. Le filtre CI `src/` (`tests.yml:185`) couvre les nouveaux chemins.

## 4. Contraintes de déplacement et risques

À mettre à jour **dans la même PR** que le déplacement :

1. **`tests/test_architecture.py`** :
   - `LAYERS` est vérifié par égalité exacte, dans les deux sens.
   - Avec PR 1 :
     - `anonymize` passe de `{'xer','export'}` à `{'xer','csv_safe'}` ;
     - `csv_safe` reçoit une entrée si les sérialiseurs importent `config` ;
     - `app` gagne `csv_safe` (`downloads`, `views/health`, `views/debug`) et garde `export` à cause de `views/export` ;
     - `cli` gagne `csv_safe` (`_write_csv`).
   - `LAYERS['cli']` contient déjà `verify` : replier `crosscheck` (Q5) ne demande que de retirer `crosscheck`.
   - Avec PR 15, `cli` pointe vers `'app.debug.diagnostic'` (préfixe).
   - `APP_EDGES` doit d'abord être réécrit pour gérer les sous-paquets (PR 0b) :
     - clés en chemin pointé ;
     - `rglob` en excluant `views/` ;
     - `app_modules` ne doit plus utiliser `split('.')[2]`.
   - Le DAG ne porte que sur les **sous-paquets frères** (`baseline`, `debug`), sans la racine de l'app : `app/baseline/*` importe des modules racine (`session`, `ui`), et des modules racine (`cache`, `state`, `loading`, `files_window`, `baseline_warnings`, `downloads`) importent `baseline/*`. Un DAG qui inclurait la racine échouerait tout de suite.
   - Une règle `app.diagnostic` périmée retomberait silencieusement sur « tout `xerscope.app` est permis ».
2. **`tests/fitness_baseline.json`** :
   - Les clés sont relatives à `src/xerscope`. Un module déplacé est jugé comme nouveau (comparé à 0 ou au rang A).
   - Chaque PR de déplacement régénère donc le baseline avec `--out` et justifie chaque mesure non nulle des nouvelles clés (`cc_max`, `cognitive_max`) dans la description.
   - `cli/__init__.py` reste au rang C pendant les PR 7 à 9 : sans régénération dans la même PR, `fitness --check` échoue avec « (new) mi_rank: C ».
   - Le baseline est déjà périmé (voir PR 0a).
3. **`pyproject.toml`** :
   - Les clés `src/...` de `[tool.ruff.lint.per-file-ignores]` doivent exister (`test_docstrings.py:84`). Un nouveau fichier n'a pas d'entrée, et une ligne ne gagne aucune règle (voir §2).
   - Lors du renommage `cli.py` -> `cli/__init__.py`, l'entrée existante est renommée, sans nouvelle règle.
   - `[tool.mutmut]` : `source_paths` ne change pas ici. `pytest_add_cli_args_test_selection` liste 15 tests par chemin, et seul le job hebdomadaire les vérifie.
   - Pas de `pythonpath` (voir les sources).
4. **`tests/test_docstrings.py`** :
   - Les clés `LONG` sont en `path:qualname` (par exemple `analysis/cpm.py:_late`, `xer/calendar.py:TimeAxis`). Aucune des fonctions déplacées par la PR 14 n'est dans `LONG`.
   - Les citations pointées continuent de passer mais deviennent fausses. On les corrige dans une PR de docstrings (`same_code --ignore-docstrings`) :
     - `` ``xer.model.leveled`` `` dans `app/diagnostic.py:602` ;
     - `` ``xer.model.ScheduleOption`` `` dans `analysis/changelog.py:408` ;
     - `` ``xer.model._labor_hours`` `` dans `analysis/baseline.py:90` ;
     - `` ``cli._write_csv`` `` dans la docstring de module de `csv_safe.py`, après la PR 8.
5. **`tests/test_sheets.py`** :
   - L18 ne lit que `xer/model.py` : il faut lire tous les `xer/*.py` avant de déplacer les codes (PR 0c).
   - L19 n'est pas récursif : il faut un `rglob` avant tout futur sous-dossier de tests.
6. **Tests qui figent des noms de fichiers** :
   - `tests/test_downloads.py:148-160` exige que le seul `.to_csv(` soit dans `export.py:`. À mettre à jour dans la PR 1 (`csv_safe.py:`).
   - `tests/test_lexicon.py` : `P6_NAMES` est indexé par `path.relative_to(APP)` (`"diagnostic.py"` à L24, `"baseline_window.py"` à L40). Il faut passer à `debug/diagnostic.py` dans la PR 15 et à `baseline/baseline_window.py` dans la PR 16. Sinon les phrases P6 ne sont plus exemptées et `test_the_interface_speaks_the_lexicon` échoue.
   - `tests/test_docker.py:113` prend `"src/xerscope/cli.py"` comme exemple de chemin. Il passe toujours le filtre `src/` mais devient périmé : à mettre à jour dans la PR 7.
   - `tests/test_cli.py:17-20` : `cli.INPUT_ERROR` -> `cli.common.INPUT_ERROR` (PR 8). `tests/test_downloads.py:126` (`from xerscope.cli import _write_csv`) reste résolu, puisque `__init__` utilise `_write_csv`. On peut le pointer vers `cli.common` dans la même PR.
7. **Monkeypatchs** (la cible suit le nom, jamais de shim) :
   - `model.file_baseline` -> `snapshot.file_baseline` ;
   - `cli.LEXICON_MAX_BYTES` et `cli._lexicon_export` -> `cli.ask.*` ;
   - `cli.subprocess` reste valable tant que `_cmd_app` est dans `cli/__init__` ;
   - `xerscope.xer.read_pmxml_baseline` et `xerscope.xer.pmxml._index_by_parsing` ne changent pas ;
   - cibles d'app (`session.load_snapshot`, `baselines._file_baseline`, `baseline_export.resolutions`, `downloads.index_pmxml`…) : le module bouge avec le nom, donc on met à jour la chaîne de la cible.
8. **Imports relatifs et chemins calculés depuis `__file__`** : `same_code` ne voit ni un import relatif dont la cible change (il compare les noms importés, pas le module), ni un chemin calculé.
   - Contrôle à chaque PR qui renomme un module en paquet : `git grep -nE 'from \.[a-z]' -- src/xerscope/cli/`. Seuls `.common` et `.ask` peuvent rester.
   - Chemins à vérifier : `cli.APP_PATH` et le cwd de `test_docker.py:293`, `ui.runtime_table`, `theme`, `streamlit_app`.
9. **Pickle** : `Snapshot` passe par les workers `spawn`, et `xer/snapshot.py` doit s'importer sans Streamlit, ce qui est le cas. `reading.py` n'importe que `store` et `xer`, donc les `__init__.py` d'`app/baseline/` et d'`app/debug/` n'ont pas d'effet sur les workers. On les garde vides par principe, pas pour cette raison. Aucun pickle ni cache n'est indexé sur un chemin de module.
10. **Données de paquet** : rien ne bouge. Contrôle par `uv build` et `unzip -l` avant et après les PR d'app.
11. **Docs**, mises à jour à la main, car seules les docstrings de `src` sont vérifiées :
    - CONTRIBUTING « Where a change goes » (L119-128) ;
    - `docs/architecture.md` §1-5, §7 (le paragraphe « Import edges » change en même temps qu'`APP_EDGES`), la table des couches et « Layer rules » ;
    - ADR 0001, 0002, 0003, 0004, 0006, 0009, 0012, 0014-0016, 0019-0024, selon le module ;
    - `docs/formulas.md`, `docs/cpm.md`, `README.md` (arborescence L358), `SECURITY.md` (csv_safe) ;
    - commentaires (`config.toml`, `charts.py`, `anonymize.py:140`, `model.py:501`).
    - Méthode : `git grep -n '<ancien chemin>'` dans chaque PR.
12. **Textes affichés** : `analysis/explain.py:501` affiche `` `export.export_tables` ``, donc `export_tables` ne bouge pas. `app/ui.py:229` cite `explain.py`, et la citation reste vraie : `critical_definition` (L297) reste dans `explain.py`.
13. **Ordre et cycles** :
    - `model.py` se découpe de bas en haut : codes, values, snapshot (colonnes, puis classe), projects (avec `_task_table`/`_project_table`), et `model` garde la construction et `_check_snapshot_columns`. Chaque module n'importe que ceux d'avant. `model` importe `projects`, jamais l'inverse.
    - `cli` : `common` sort avant `ask`, sinon il y a un cycle avec `__init__`.
    - `readings` sort de bas en haut (tail, puis `READINGS`, puis constantes), pour que `readings` importe `explain` sans que l'inverse arrive jamais. Aucune définition ne traverse la frontière L313/314 dans un sens ou dans l'autre.
    - Les règles s'enregistrent dans le même ordre dans `analysis/__init__.py`.

**Risques** :
- Un patch silencieusement manqué si l'on ajoute un shim (d'où l'interdiction).
- Un import relatif qui change de cible sans bruit (PR 7) : d'où la réécriture en absolu et le contrôle par grep.
- Une donnée de test introuvable qui provoque un *skip* au lieu d'un échec : utiliser `XERSCOPE_REQUIRE`.
- Les tests MPXJ ignorés sans Java : lancer le job `crosscheck`.
- Le budget de dette docstring (7 paires) : d'où les PR de docstrings préalables.
- `cli/__init__` mesure environ 19.5 de MI après extraction : rang A, mais proche de la limite.
- Le CI hebdomadaire de mutation est le seul garde-fou sur les chemins de `mutmut`.
- Le coût honnête : environ 40 fichiers de tests et environ 30 fichiers de doc voient leurs chemins d'import ou leurs citations changer. Seules les façades (`xerscope.xer`, `xerscope.analysis`, `xerscope.cli:main`) restent stables.

## 5. Plan de PR ordonné

Taille : un bloc déplacé compte deux fois, et les tailles indiquées comprennent les retraits et les ajouts. Toutes les PR passent la vérification commune ci-dessus ; seuls les contrôles propres à chaque PR sont précisés ici. « Docs » désigne une PR de docstrings (`same_code --ignore-docstrings`) sur le code qui va bouger, à son emplacement actuel.

**Phase 0 : prérequis, aucun déplacement**

| # | PR | Diff | Vérification propre |
|---|---|---|---|
| 0a | Régénérer `fitness_baseline.json` : retirer `app/views/activity.py`, ajouter les 18 modules absents (`xer/pmxml_scan.py`, plusieurs modules d'app…), mettre à jour les valeurs périmées (`xer/model.py` MI 7.4 -> 4.4, `app/baselines.py` C -> A (46.5), `analysis/explain.py` MI 38.7 -> 25.05) | environ 40 (baseline) + environ 36 lignes de justification | `fitness --check` vert ; `check_value_justification` vert |
| 0b | `test_architecture` gère les sous-paquets d'app (clés pointées, `rglob`, DAG entre sous-paquets frères seulement, racine exclue), plus `docs/architecture.md` §7 | environ 60-80 | `pytest tests/test_architecture.py` ; contrats inchangés (`import_contracts_broken` = 0) |
| 0c | `test_sheets` lit tous les `xer/*.py` et passe à `rglob` | environ 6 | même liste de nœuds collectés ; mêmes totaux `oracle_report` |
| 0d | `diagnostic` importe `as_dates` depuis `table_filters` ; `APP_EDGES['diagnostic']` ; doc §7 | environ 10 | `python -c "import xerscope.app.diagnostic, sys; assert 'streamlit' not in sys.modules"` ; `same_code` vert |
| 0e | `task_filters` importe `fold` depuis `.ask.text` | environ 2 | `same_code` vert |
| 0f | Textes de `READINGS` : les 15 citations `fichier:ligne` deviennent des noms de fonctions ou de constantes existantes, ou perdent leurs numéros de ligne (pas de `LABEL_DECIMALS`, aucune constante ajoutée) | moins de 40 | `pytest tests/test_readings.py tests/test_page_golden.py` ; `git diff tests/golden` vide ; chaque valeur changée listée dans la PR |
| 0g | Docstrings pointées `xer.model.*` corrigées là où la cible est déjà connue, plus la docstring de `app/state.py` | environ 10 | `same_code --ignore-docstrings` |

**Phase 1 : cœur**

| # | PR | Diff | Vérification propre |
|---|---|---|---|
| 1 | `Fmt`, `CSV_FLOAT_FORMAT`, `csv_bytes`, `_bytes`, `zip_frames` : `export.py` -> `csv_safe.py` ; `export` réimporte `Fmt` et `_bytes` ; importeurs (`anonymize`, `cli`, `app/downloads`, `views/health`, `views/debug`) ; `views/export` garde `from xerscope.export import Fmt…`, résolu par la réimportation (ou le pointer vers `csv_safe`) ; `LAYERS` (`anonymize`, `csv_safe`, `app`, `cli`) ; `test_downloads.py:148-160` ; architecture.md, ADR-0022/0023, SECURITY.md | environ 180 | `pytest tests/test_anonymize* tests/test_downloads.py tests/test_export*` |
| 2a | Docs : D205, D102 dans les tables de codes | environ 10 | `ruff --select D` sur la plage |
| 2 | `xer/codes.py` (L106-196) ; environ 12 importeurs ; aucune entrée per-file-ignores | environ 300 | `test_sheets` vert ; `ruff --select D src/xerscope/xer/codes.py` |
| 3a | Docs : D205, D209, D103, D401 dans les lecteurs de valeurs | environ 15 | idem |
| 3 | `xer/values.py` (L202-313, aides privées sous le même nom) ; `test_audit_edges_xer`, `test_time_semantics` | environ 260 | aucun cycle (`python -c "import xerscope.xer"`) |
| 4 | `xer/snapshot.py` : listes de colonnes (L41-105), contrats de colonnes et listes CODE/UDF (L392-513 sauf `_check_snapshot_columns`, qui reste dans `model.py`) ; `store.py:18` ; `test_store` | environ 380 | `pytest tests/test_store.py` ; aucune erreur mypy nouvelle |
| 5a | Docs : D102, D205, D209 dans `FileBaseline`/`Snapshot` (L528-683) | environ 20 | idem |
| 5 | `xer/snapshot.py` : `FileBaseline`, `file_baseline`, `_chain`, `Snapshot` ; cible du monkeypatch de `test_file_baseline:709` | environ 400 | `pytest tests/test_file_baseline.py tests/test_reading.py` (pickle spawn) |
| 6a | Docs : D205, D209, D401 dans la sélection de projet (L1000-1111, L1606) | environ 15 | idem |
| 6 | `xer/projects.py`, avec `_task_table` et `_project_table` ; `store` (`projects_text`) ; `test_audit_edges_xer` ; CONTRIBUTING L119-121, ADR 0001-0004/0006/0012 (ou PR 6b de doc si le diff déborde) | environ 400 | pas de cycle `projects <-> model` ; `fitness` : `xer/model.py` passe de C à A |

**Phase 2 : CLI**

| # | PR | Diff | Vérification propre |
|---|---|---|---|
| 7 | `git mv cli.py cli/__init__.py` ; les 43 imports relatifs passent en `from xerscope.…` absolu (17 d'entre eux partiront ensuite dans `cli/ask.py`) ; `APP_PATH` passe à `.parent.parent` ; ajout de `cli/__main__.py` (docstring + `raise SystemExit(main())`) pour garder `python -m xerscope.cli`, et retrait du bloc `if __name__ == "__main__"` de L1036, devenu mort ; `test_docker.py:113` ; clé fitness et per-file-ignores renommées ; baseline régénéré (rang C justifié) | environ 100 | `pytest tests/test_cli.py tests/test_docker.py` ; `xerscope app --help` ; `python -m xerscope.cli --help` ; `xerscope crosscheck` avec Java ; `git grep -nE 'from \.[a-z]' src/xerscope/cli/` vide ; `same_code` ne signale que `APP_PATH`, le bloc `__main__` et les imports, tous annoncés |
| 8 | `cli/common.py` (aides), importé par `__init__` pour ce qu'il utilise ; `test_cli.py:17-20` -> `cli.common.INPUT_ERROR` ; baseline régénéré | environ 130 | `pytest tests/test_cli.py tests/test_audit_edges_app.py tests/test_downloads.py` ; `ruff` sans F401 |
| 9a | Docs : D205, D209, D401 dans L675-981 | environ 20 | idem |
| 9 | `cli/ask.py` : lexicon ; cibles `cli.ask.LEXICON_MAX_BYTES` et `cli.ask._lexicon_export` ; baseline régénéré | environ 380 | `pytest tests/test_cli.py tests/test_lexicon.py` |
| 10 | `cli/ask.py` : ask-bench ; docstring de `csv_safe` (`cli.common._write_csv`) ; ADR 0014/0020-0024 et docs | environ 340 | `pytest tests/test_ask_bench.py tests/test_cli.py` ; `fitness` : MI de `cli/__init__` au-dessus de 19, rang A |

**Phase 3 : analysis** (de bas en haut, `readings` importe `explain` et jamais l'inverse)

| # | PR | Diff | Vérification propre |
|---|---|---|---|
| 11a | Docs : D205, D209, D401 (L447, L930, L954, L972) ; docstrings de `viz/charts.py:74` et `test_page_golden.py:42` | environ 15 | `same_code --ignore-docstrings` |
| 11 | `analysis/readings.py` : tail L917-981 (`TSPI_*`, `schedule_reading` et ses aides) ; tests (`test_schedule_reading`, y compris la chaîne `'explain.schedule_reading'`) | environ 150 | goldens inchangés ; `pytest tests/test_explain.py tests/test_schedule_reading.py` |
| 12 | `READINGS` seul (une seule affectation, L505-914, 410 lignes), impossible à couper à une frontière de définition ; 7 vues, `app/ui` | environ 840 (**hors budget, Q1**) | goldens inchangés ; `pytest tests/test_readings.py` ; `same_code` |
| 13 | Constantes et lectures L314-504 (`P6`, `EVMS`…, `SPI_WINDOW_READING`, `*_READING`) ; importeurs restants | environ 400 | goldens inchangés ; `pytest tests/test_readings.py tests/test_explain.py` |
| 14 (opt) | `analysis/critical_path.py` (`critical_path_test`, L2268-2497) ; `rules.py:46` ; 2 tests ; docs/cpm.md (pas de `LONG`) | environ 460, donc au-dessus du budget : à couper en 2 ou à soumettre à Q1 | `pytest tests/test_cpm*.py tests/test_rules.py` ; `test_crosscheck_mpxj` avec Java |

**Phase 4 : app** (après 0b et 0d)

| # | PR | Diff | Vérification propre |
|---|---|---|---|
| 15 | `app/debug/` (le trio) ; `LAYERS['cli']` passe à `'app.debug.diagnostic'` ; `cli/__init__` pv-compare ; environ 26 imports de tests ; `test_lexicon.py` (`"debug/diagnostic.py"`) | environ 160 | `pytest tests/test_diagnostic.py tests/test_cli.py tests/test_lexicon.py` ; wheel identique en dehors des chemins |
| 16 | `app/baseline/` (5 modules) ; `APP_EDGES` ; environ 30 imports de src et de tests ; cibles de monkeypatch (`baselines._file_baseline`, `baseline_export.resolutions`) ; `test_lexicon.py` (`"baseline/baseline_window.py"`) ; doc §7, README | environ 260 | `pytest tests/test_app*.py tests/test_file_baseline.py tests/test_baseline_*.py tests/test_pmxml.py tests/test_lexicon.py` ; goldens |

**Phase 5 : tests** (preuve par la détection de renommage de git, la liste des nœuds et `oracle_report`)

| # | PR | Diff | Vérification propre |
|---|---|---|---|
| 17 | Aides AppTest de `conftest.py` (L101-220) -> `appkit.py` ; `missing` et les indications -> `evidencekit.py` ; environ 30 importeurs (`test_oracle_report` garde `import conftest` pour le hook) | environ 300 | liste de nœuds identique ; `XERSCOPE_REQUIRE=reference,p6-corpus pytest` |
| 18 | `cpmkit.random_network` ; 5 importeurs | environ 100 | idem |
| 19 | `evkit` : `test_earned_schedule`, `test_ev_contracts`, plus les données de `test_evm_weekly` (importées par `test_app:776`) et de `test_evm_code_filter` (`test_app:713`) | environ 250 | idem |
| 20 | `appkit` : `APP`, `_ok`, `app` (de `test_app`) et `PAGES` (noms nus, de `test_page_golden`, dont l'`APP` est identique) ; `glossarykit.PAGES` (de `test_glossary`, sans forensics) pour `test_widget_help:15` ; importeurs `test_widget_help`, `test_readings`, `test_table_contract` | environ 150 | idem |
| 21 | `codekit` (`test_code_types_blind` -> `test_app`, `test_ask_ambiguous_codes_blind`, `test_query` ×2) ; `pvkit` (`test_pv_p6` -> `test_cli` ×2) | environ 200 | idem |
| 22 | `referencekit` (`test_characterization` -> `test_audit:12`) ; `test_file_baseline._series_and_export` -> kit (`test_baseline_per_page`) | environ 150 | idem ; après cette PR, `git grep -nE '(from\|import) test_' tests/` est vide |

Les trois listes `PAGES` sont différentes et ne peuvent pas vivre byte-identiques dans un seul module : `test_app.PAGES` reste dans `test_app` (aucun autre test ne l'importe), `test_page_golden.PAGES` va dans `appkit`, et `test_glossary.PAGES` va dans `glossarykit`.

Correctif hors série, à placer n'importe où : `scripts/accessibility.py:41`, liste des pages (retirer `activity`, ajouter `forensics`). C'est un correctif d'outil, pas un déplacement.

## 6. Questions ouvertes pour le mainteneur

1. **Budget de 400 lignes pour un déplacement pur.**
   - La PR 12 (`READINGS`, une seule affectation de 410 lignes, environ 840 lignes de diff) ne peut pas être coupée.
   - Les PR 5, 6, 9, 13 et 14 sont à la limite ou au-dessus.
   - Peut-on accepter jusqu'à environ 850 lignes de diff quand `same_code.py` prouve qu'il n'y a que des déplacements ? Sinon, `READINGS` reste dans `explain.py` et `readings.py` ne reçoit que le reste.
2. **Ré-exports dans `xer/model.py`.** La proposition met à jour les importeurs (environ 40 fichiers de src et de tests sur l'ensemble des PR 2 à 6) et n'en garde aucun, à cause des monkeypatchs et de F401. Préférez-vous que les importeurs non patchés passent plutôt par la façade `xerscope.xer` ?
3. **P11a.** `docs/refactor-front-plan.md` envoie `diagnostic` vers `analysis/`, mais `analysis` n'a pas le droit d'importer `config` (`DEFAULT_SETTINGS`). Trois choix :
   - (A) `app/debug/`, en gardant l'arête `cli -> app.debug` (proposé) ;
   - (B) une nouvelle couche de premier niveau `diagnostic/` qui importe `{xer, analysis, config}`, après avoir déplacé `as_dates` dans `xer` (2 à 3 PR) ;
   - (C) une ADR qui autorise `analysis -> config`.
   Le plan P11a est à amender dans tous les cas.
4. **Découpage du CLI.** Faut-il s'arrêter à `common` et `ask` (proposé, `cli/__init__` passe au rang A), ou aller jusqu'à un module par groupe de sous-commandes (4 PR de plus, gain faible) ?
5. **`crosscheck.py`.** Le garder, ou le replier dans `verify/__init__.py` (environ 60 lignes ; vérifier d'abord que `verify` ne démarre pas jpype à l'import) ? `LAYERS['cli']` contient déjà `verify`.
6. **`xer/pmxml/`** (`__init__.py` et `scan.py`), qui préserverait tous les chemins `xerscope.xer.pmxml` : le faire ou non ? Le gain est faible.
7. **`rules.py`.** Faut-il séparer les aides partagées (L727-850) dans leur propre module, ce qui retirerait l'import `rules -> cpm` ? L'ordre d'enregistrement des règles ne changerait pas.
8. **`app/widgets/` et `app/sidebar/`, découpages de `ui.py`** (colonnes et formatage pur sans Streamlit) : à faire après les PR 15 et 16, ou à abandonner ? Ils coûtent au moins 4 PR, et `runtime_table` doit d'abord sortir de `ui`.
9. **Sous-dossiers de `tests/` par thème** (`cpm/`, `app/`, `rules/`, `ev/`, `query/`, mais pas `ask/`, qui est un dossier de données ; aucun nom de dossier ne doit masquer un import de premier niveau).
   - Une fois les kits en place (PR 17 à 22), c'est faisable.
   - Coût : 88 chemins cités dans 52 fichiers, les sélections `mutmut`, les per-file-ignores de 4 tests, une dizaine de fichiers qui doivent rester au sommet, et `pythonpath = ["tests"]` ou `importlib` à ce moment-là.
   - Proposition : ne pas le faire maintenant.
10. **Noms dans les sous-paquets** : garder `app/baseline/baseline_file.py` (proposé, la recherche par grep ne change pas) ou retirer le préfixe redondant (`app/baseline/file.py`) ? `same_code` le permet, mais toutes les citations et les clés de `test_lexicon` changent.
11. **`analysis/critical_path.py` (PR 14)** : à faire ? `cpm.py` reste au rang C quoi qu'il arrive. Le seul gain est de sortir du fichier du moteur un bloc autonome d'environ 230 lignes.
12. **`cli/__main__.py` (PR 7)** : l'ajouter pour garder `python -m xerscope.cli` (proposé, aucun usage trouvé dans le dépôt, mais c'est le comportement actuel), ou accepter la perte et l'annoncer ?

## Corrections de la relecture

Toutes les corrections ont été revérifiées à `dd6c71b`, et aucune n'a été rejetée. Les points 13 et 14 sont acceptés avec une nuance chacun.

1. **PR 7 et les imports relatifs.**
   - Les 43 imports paresseux relatifs de `cli.py` (L59, 403, 435, 459, 514, 533, 570, 594…) passent en imports absolus dans la PR 7. Son diff passe d'environ 20 à environ 100 lignes.
   - Ajout du contrôle par grep (`from \.[a-z]` interdit hors `.common` et `.ask`) et d'un lancement de `xerscope crosscheck` avec Java.
   - La limite de `same_code` sur ces imports est expliquée.
   - Ajout d'un `cli/__main__.py` et retrait du bloc mort de L1036, annoncés dans la PR (nouvelle question 12).
2. **Dette docstring.**
   - Les « per-file-ignores minimales » sont supprimées : un nouveau fichier n'a pas d'entrée.
   - Ajout de PR de docstrings 2a, 3a, 5a, 6a, 9a et 11a avant chaque découpage concerné, avec les règles relevées par `ruff --select D`.
3. **Cycle `projects <-> model`.** `_task_table` et `_project_table` (L314-339) partent dans `projects.py` avec `read_header`. `model` importe `projects`, jamais l'inverse.
4. **Tranches de `model.py`.**
   - Les listes de colonnes (L41-105, dont `LABOR_COLS` utilisé par `store.py:18`) vont dans `snapshot.py`.
   - `codes` couvre L106-196, `ScheduleOption` et `constraints_label` compris ; `values` couvre L202-313.
   - `_check_snapshot_columns` reste dans `model.py`, ce qui évite un import `TYPE_CHECKING` et une erreur mypy.
5. **`readings`.**
   - Le tail commence à L314 et couvre 667 lignes, soit environ 1330 lignes de diff.
   - `READINGS` (L505-914) devient une PR à lui seul, hors budget (Q1).
   - Les PR suivent l'ordre de bas en haut pour éviter un cycle transitoire `explain <-> readings`.
   - Le point 11 du §4 est tranché : `critical_definition` reste, et `ui.py:229` reste vrai.
6. **PR 0f.** `charts.LABEL_DECIMALS` est retiré, car il n'existe pas. Les 15 citations `fichier:ligne` sont listées, et la PR cite des noms existants ou retire les numéros, sans ajouter de constante.
7. **PR 1.**
   - `Fmt` part aussi dans `csv_safe`, et `export` réimporte `Fmt` et `_bytes`.
   - `test_downloads.py:148-160` est mis à jour.
   - `LAYERS` gagne `csv_safe` pour `app` et pour `cli` ; `app` garde `export`.
8. **Phase 5.**
   - Les 7 modules de test restants sont couverts (PR 19 élargie, nouvelles PR 21 et 22, kits `codekit`, `glossarykit`, `pvkit`, `referencekit`).
   - Les trois `PAGES` restent distincts.
   - Les aides de `conftest` sont aux lignes 101-220.
9. **`tests/test_lexicon.py`** (clés `P6_NAMES`) est ajouté aux PR 15 et 16.
10. **DAG de la PR 0b.**
    - Le DAG ne porte plus que sur les sous-paquets frères, sans la racine.
    - La justification par `BASELINE_DOMAIN` est nuancée, car `baseline_warnings` reste à la racine.
11. **`INPUT_ERROR`.**
    - L'exception de `cli/__init__` est retirée pour `INPUT_ERROR`, qui aurait été un import inutilisé, donc un shim.
    - `test_cli.py:17-20` passe à `cli.common.INPUT_ERROR`.
12. **Fitness.**
    - Justification exigée pour chaque mesure non nulle d'une clé déplacée.
    - Le baseline est régénéré dans les PR 7 à 9 (`cli/__init__` au rang C).
    - PR 0a : environ 36 lignes de justification et les valeurs périmées (`model` 7.4 -> 4.4, `baselines` C -> A, `explain` 38.7 -> 25.05).
13. **Sources pytest et phauer.**
    - pytest recommande `importlib`. On garde `prepend` à cause des lignes `from conftest import` : 41 comptées ici, 42 selon la relecture.
    - `pythonpath = ["tests"]` est retiré de la PR 0c et renvoyé à Q9.
    - La citation phauer.com est signalée comme non revérifiée.
14. **Pickle.** Le raisonnement est corrigé : `reading.py` n'importe que `store` et `xer`, et aucun pickle ni cache n'est indexé sur un chemin de module. La règle « `__init__` vides » est gardée par principe seulement.
15. **Petits points.**
    - La phrase « `cli` dépend de `verify` si `crosscheck` est retiré » est supprimée, car `verify` est déjà dans `LAYERS['cli']`.
    - PR 14 : plus de mise à jour de `LONG`, la plage commence à L2268, et ses environ 460 lignes dépassent le budget.
    - `test_docker.py:113` est mis à jour dans la PR 7, et la docstring de `csv_safe` (`cli._write_csv`) dans la PR 10.
