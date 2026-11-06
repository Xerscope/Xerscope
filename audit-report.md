# Audit logiciel xerscope — 2026-11-06

Périmètre : le logiciel (robustesse, sécurité, maintenabilité, chaîne d'approvisionnement), pas la justesse
métier P6 (couverte par `docs/standards.md`, `docs/cpm.md` et les corpus de référence). Référentiels : ISO/IEC
25010:2023, OWASP ASVS 5.0, CWE Top 25, NIST SSDF, SLSA v1.0, OpenSSF Scorecard, CIS Docker Benchmark,
ISO/IEC/IEEE 29119-4, Google Engineering Practices. Branche auditée : `claude/wizardly-ptolemy-b4zjg4` (= `main`
au moment de l'audit). Aucun fichier de `src/` n'a été modifié ; seuls des tests et ce rapport ont été ajoutés.

Preuves : chaque constat est reproduit par un test `xfail(strict=True)` dans `tests/test_audit_edges_*.py`
(il passe au vert dès que le défaut est corrigé) ; les comportements corrects sont des tests ordinaires.

## 0. Statut au 2026-11-06 (après mise en conformité, branche `claude/wizardly-ptolemy-b4zjg4`)

Les blocs A, B, C, D, E et F du plan ont été appliqués (`conformity-plan.md` §2, feu vert de l'auteur) ; le bloc G
(découpage structurel) est reporté après la refonte visuelle et la revue d'architecture.

| Zone | Constats | Fermés | Ouverts | Preuve |
|---|---|---|---|---|
| xer (parser, modèle, calendrier) | 16 | 16 | 0 | `tests/test_audit_edges_xer.py` : 0 `xfail` |
| CPM | 9 | 9 | 0 | `tests/test_audit_edges_cpm.py` : 0 `xfail` |
| app (standards, CLI, export, anonymisation, store) | 12 | 12 | 0 | `tests/test_audit_edges_app.py` : 0 `xfail` |
| déploiement / supply chain | 4 | 3 (DEP-01, 02, 04) | DEP-03 : consigne documentée, pas de secret monté | `tests/test_docker.py` |

Changements notables par rapport au §2 : parser réécrit en flux (pic mémoire mesuré **12,55 × → 3,21 ×** sur 10 MB,
3,0 s → 1,5 s) ; `TimeAxis` borné à la plage pandas avec `ValueError` immédiat ; nouveau `xer/validate.py` (unicité,
fuseaux, bornes, durées négatives ou non finies, types de lien inconnus → une ligne de `warnings` chacun) ;
`ScheduleError(ValueError)` typée dans le moteur, `CycleError` en est une sous-classe, `Schedule` et `Snapshot`
gelés, résultat renvoyé en copie (coût mesuré 0,008 % sur le plus gros fichier de référence) ; `csv_safe` appelé par
tout écrivain CSV via `csv_bytes` ; pseudonymes 12/8 hex ; TOML et CLI validés (exit 2 usage, 1 `--fail-on`) ;
images avec provenance, SBOM et attestation GitHub, CodeQL, Scorecard, fuzzing Hypothesis du parser (7 crashs
trouvés puis corrigés, dont un hors audit : TASKRSRC sans colonne `task_id`), `CHANGELOG.md`.

Aucune valeur calculée des fichiers de référence n'a bougé ; `FLOORS` du corpus P6 inchangés. Deux comportements
ont changé par décision du plan, pas par correction : `project_task_counts` est indexé par `proj_id` (était : code
projet) et une durée restante négative ou non finie est lue 0 avec warning (était : propagée). Les 12 questions
métier du §7 restent ouvertes.

## 1. Résumé exécutif

État général : **sain**. La suite complète passe (1 363 tests, 40 skips expliqués), ruff/format propres, bandit
sans Medium/High, pip-audit sans vulnérabilité, actions CI épinglées par SHA, images racine par digest, conteneur
non-root en lecture seule sans port publié, aucun cycle d'import, couches respectées et testées
(`tests/test_architecture.py`). Le moteur CPM est linéaire O(N+E) et déterministe bit à bit.

Trois risques majeurs :
1. **Frontière de confiance perméable** : six chemins où un `.xer` ou un TOML malformé sort en exception brute
   (`OverflowError`, `ValueError`, `KeyError`, `RecursionError`) au lieu de `XerError`/`ValueError` typée, et un cas
   de relabellisation silencieuse de colonnes (AUDIT-XER-01). CONTRIBUTING.md promet « a crafted .xer must fail to load ».
2. **Injection CSV (CWE-1236)** : les trois écrivains CSV (export Power BI, CLI `--out/--flagged`, extrait anonymisé)
   recopient le texte XER tel quel ; une cellule `=cmd|...` d'un fichier piégé s'exécute dans Excel (AUDIT-APP-07).
3. **Consommation mémoire du parser** : pic ≈ 12,4 × la taille du fichier (608 MB pour 49 MB) ; un export de 300 MB
   dépasse la limite `mem_limit: 2g` du déploiement (AUDIT-XER-05).

Trois forces : (a) discipline de preuve (corpus P6 held-out avec planchers, propriétés aléatoires, crosscheck MPXJ) ;
(b) règles paramétrées en TOML validées au chargement, une fonction par règle ; (c) chaîne d'approvisionnement déjà
au-dessus de la moyenne OSS (SHA pinning, digests, Dependabot groupé, trivy, pip-audit, bandit, lock vérifié).

## 2. Constats

Sévérité : Critique = exploitation ou perte de donnée ; Majeur = plantage ou résultat faux sur entrée plausible ;
Mineur = robustesse/qualité ; Info = à documenter. Effort : S < ½ j, M 1–2 j, L > 2 j.

| ID | Sév. | Fichier:ligne | Référentiel | Constat | Preuve | Correction proposée | Eff. |
|---|---|---|---|---|---|---|---|
| AUDIT-APP-07 | Majeur | `export.py:38`, `cli.py:46`, `anonymize.py:160` | CWE-1236 ; ASVS V5 ; ISO 25010 Security/Integrity | Tout CSV exporté recopie le texte XER/TOML sans neutralisation ; `=1+1`, `@SUM(1)`, `-2+3` atterrissent dans un CSV avec BOM destiné à Excel. | `test_csv_export_neutralises_formula_cells` : ligne `0,2026-03-02 08:00,A1,=1+1,...` | Une fonction `csv_safe(frame)` appelée par les trois écrivains : préfixe `'` (ou tabulation + guillemets, OWASP) sur toute cellule texte commençant par `= + - @ \t \r`. | S |
| AUDIT-XER-01 | Majeur | `parser.py:101` | CWE-20 ; ISO 25010 Functional correctness | Une seconde ligne `%F` (ou une table reprise avec d'autres colonnes) ré-étiquette silencieusement les lignes déjà lues. | `test_second_field_line_in_a_table_is_reported` : `{'p':'1','q':'2','r':''}`, `warnings == []` | Si `names != cols[current]` : ignorer la suite avec warning nommant la table, ou `XerError`. | S |
| AUDIT-XER-05 | Majeur | `parser.py:74-135` | CWE-400 ; ISO 25010 Resource utilization | Pic mémoire 12,4 × la taille du fichier (coexistence bytes + str + liste de lignes + listes de listes + copie `fixed` + DataFrame object). 14 s pour 49 MB. | `probe_perf.py` : `peak 608 MB (12.4x)` ; `test_peak_memory_of_parse_bytes_is_a_small_multiple_of_the_file_size` | Itérer sur les lignes sans matérialiser, supprimer la copie `fixed`, construire chaque table dès le `%T` suivant ; décoder par ligne depuis les bytes. | M |
| AUDIT-XER-14 | Majeur | `calendar.py:110-111, 139, 153` | CWE-248 ; ISO 25010 Fault tolerance | `parse_clndr_data` ne protège que `_parse_tree` : période `ab:cd` → `ValueError` brut ; série d'exception hors plage → `OverflowError` brut, tout le fichier rejeté alors qu'un repli existe. | `test_malformed_period_time_in_blob_is_a_xer_error_or_ignored`, `test_out_of_range_exception_serial_is_a_xer_error_or_ignored` | Étendre le `try/except (ValueError, IndexError, OverflowError, RecursionError)` à toute la construction ; borner les séries ; journaliser dans `warnings`. | S |
| AUDIT-CPM-01 | Majeur | `cpm.py:1448, 461` → `calendar.py:302, 337` | CWE-755, CWE-190 ; ISO 25010 Fault tolerance | Durée restante ou lag `inf` ou > plage pandas (1e9 h) sort en `OverflowError` brut ; `integrity.py` et `critical_path_test` n'attrapent que `CycleError` : pages et règles INT plantent. | `test_infinite_remaining_duration_is_a_typed_error`, `test_huge_remaining_duration_is_a_typed_error`, `test_infinite_lag_is_a_typed_error` | Valider dans `_Run._network` (fini et borné, ex. < 1e6 h) et lever une erreur typée listant les activités, ou retraduire `OverflowError` dans `schedule()`. | S |
| AUDIT-CPM-02 | Majeur | `cpm.py:481-489` | CWE-20 ; ISO 25010 Functional correctness | Durée restante négative acceptée : EF avant ES et avant la data date, TF 0, aucun warning ; le `finish` projet peut reculer avant la data date. | `test_negative_remaining_duration_is_clamped_or_reported` : `ef 2026-02-25 17:00 < es 2026-03-02` | `max(0, remaining)` + warning « N activités à durée restante négative, lue 0 ». | S |
| AUDIT-CPM-03 | Majeur | `cpm.py:1400` | CWE-754 ; ISO 25010 Fault tolerance | Snapshot sans activité ordonnançable (lignes WBS summary seules) → `KeyError 'task_code'` au lieu d'un `Schedule` vide. | `test_only_wbs_summary_rows_gives_an_empty_schedule_not_a_key_error` | `pd.DataFrame(rows, columns=[...])` avec colonnes explicites, comme `assignment_dates`. | S |
| AUDIT-XER-02 | Mineur | `parser.py:53-56` | CWE-172 ; ISO 25010 Appropriateness recognizability | Fichier UTF-16 décodé « avec succès » en cp1252 → message trompeur « not an XER file ». | `test_utf16_file_is_rejected_with_a_message_naming_the_encoding` | Détecter les BOM UTF-16/32 et décoder, ou `XerError` nommant l'encodage. | S |
| AUDIT-XER-03 | Mineur | `parser.py:86, 90` | CWE-248 | `%T` à nom vide puis `%R` → `KeyError('')` brut. | `test_empty_table_name_followed_by_rows_is_a_xer_error` | `current = parts[1].strip() or None`. | S |
| AUDIT-XER-04 | Mineur | `parser.py:135` → `model.py:1022` | CWE-248 | Colonnes `%F` homonymes → DataFrame à colonnes dupliquées → `AttributeError` dans le modèle. | `test_duplicate_column_name_is_refused_by_parser_or_model_with_xer_error` | Dédoublonner/suffixer au parse avec warning, ou `XerError`. | S |
| AUDIT-XER-06 | Mineur | `model.py:1040` | CWE-248 | `task_id` dupliqué → `InvalidIndexError` pandas brut. | `test_duplicate_task_id_is_a_xer_error` | `XerError` ou `drop_duplicates` + warning dans `_task_table`. | S |
| AUDIT-XER-07 | Mineur | `model.py:665` | CWE-248 | `wbs_id` dupliqué → « truth value of a Series is ambiguous ». | `test_duplicate_wbs_id_is_a_xer_error_or_first_row_wins` | `drop_duplicates("wbs_id")` + warning. | S |
| AUDIT-XER-08 | Mineur | `model.py:395` | CWE-20 | Ligne PROJECT dupliquée → repr pandas dans `FileBaseline.note/proj_id` affiché à l'utilisateur. | `test_duplicate_project_row_keeps_file_baseline_readable` | Dédoublonner PROJECT dans `build_snapshot` avec warning. | S |
| AUDIT-XER-09 | Mineur | `model.py:838` | CWE-20 | `project_task_counts`/`projects_in_file` indexés par code : deux projets de même code (copie baseline) fusionnent. | `test_two_projects_with_the_same_code_are_both_counted` | Indexer par `proj_id`, ou documenter `file_projects` comme source fiable. | S |
| AUDIT-XER-10 | Mineur | `model.py:1059` | CWE-20 | `[ext]<task_id>` vit dans l'espace de noms des Activity ID : une activité locale nommée `[ext]100` est indiscernable. | `test_local_activity_named_like_an_external_placeholder_stays_distinguishable` | Détecter la collision et avertir, ou préfixer par un caractère impossible dans un ID P6. | S |
| AUDIT-XER-11 | Mineur | `model.py:149` | CWE-248 | Une cellule date avec fuseau parmi des naïves → `ValueError: Mixed timezones` malgré `errors="coerce"` ; fichier rejeté. | `test_a_timezone_suffixed_date_cell_does_not_crash_the_build` | Pré-filtre regex ISO 8601 naïf, ou `utc=True` puis `tz_localize(None)`. | S |
| AUDIT-XER-12 | Mineur | `calendar.py:160, 177, 277` | CWE-682 | `day_hr_cnt` ∈ (0, 1 min) sans blob → période de longueur nulle, calendrier sans temps de travail, `remaining_d` = 8e10, `ValueError` brut. | `test_tiny_day_hr_cnt_without_blob_gives_a_usable_calendar_or_a_xer_error` | Exiger `hpd >= 1/60` (sinon défaut + warning) ; `end > start` dans `_default_day`. | S |
| AUDIT-XER-13 | Mineur | `model.py:671` | CWE-190 | `seq_num` > int64 → `astype(int)` déborde en silence vers −2⁶³ ; `wbs_sort` faux. | `test_wbs_seq_num_beyond_int64_keeps_the_order` | `clip(0, 10**6 - 1)` avant `astype(int)`. | S |
| AUDIT-XER-15 | Mineur | `calendar.py:68` | CWE-674 | Parseur de blob récursif sans borne : ~1 000 niveaux → `RecursionError` non attrapée. | `test_deeply_nested_blob_is_rejected_not_a_recursion_error` | Attraper `RecursionError` ou limiter la profondeur (> 16 → `ValueError`). | S |
| AUDIT-XER-16 | Mineur | `calendar.py:273, 297, 335-343` | CWE-400 ; ISO 25010 Time behaviour | `TimeAxis.at` étend l'axe par doublement sans borne : 1e8 min → 6,6 s / 67 MB puis `OutOfBoundsDatetime` ; 1e9 min → 28 s / 278 MB. | `test_a_duration_beyond_the_timestamp_range_fails_fast` | Borner à `Timestamp.min/max`, lever `ValueError` immédiat ; vectoriser `_periods`. | M |
| AUDIT-CPM-04 | Mineur | `cpm.py:206, 256-278` | CWE-375 ; ISO 25010 Modifiability | `schedule()` renvoie l'objet caché lui-même (`frame`, `warnings` partagés) ; une écriture d'un appelant corrompt INT-01/INT-03/CPT/tendance. Asymétrie avec `compare_with_stored` qui copie. | `test_mutating_the_returned_frame_does_not_change_the_cached_result` | `Schedule(frozen=True)` + renvoi en copie, ou documenter « read-only ». | S |
| AUDIT-CPM-05 | Mineur | `cpm.py:271-275`, `model.py:416, 524` | CWE-664 ; ISO 25010 Maturity | Cache sans invalidation, `Snapshot` non gelé : modifier `snapshot.tasks` après un run renvoie les anciennes dates. | `test_editing_the_tasks_after_a_run_is_seen_by_the_next_run` | Geler `Snapshot`, ou clé de cache = empreinte des tables ; documenter dans `docs/cpm.md`. | M |
| AUDIT-CPM-06 | Mineur | `cpm.py:573-577, 964-971, 1296-1299` | CWE-478 ; ISO 25010 Functional correctness | Type de relation inconnu (`PR_XX`) lu comme SF en passe avant, ignoré en passe arrière, sans warning. | `test_unknown_relationship_type_is_rejected_or_reported` | Filtrer `type ∉ {FS,SS,FF,SF}` dans `_network` + warning ; `else: raise` défensif. | S |
| AUDIT-CPM-07 | Mineur | `cpm.py:716` | ISO 25010 Fault tolerance | `TK_Active` sans `act_start_date` → `es = NaT` sans warning (le cas symétrique « complete » en a un). | `test_started_without_actual_start_is_warned_or_dated` | Replier `es` sur `remaining_start` + warning. | S |
| AUDIT-APP-08 | Mineur | `anonymize.py:150-152, 289-292` | ISO 25010 Availability ; commentaire faux | Pseudonymes 32 bits (activités) / 24 bits (WBS, ressources) : 50 k IDs → P(collision) ≈ 25 % (le commentaire dit 0,03 %), 100 k → 69 % ; `CodeClash` refuse l'extrait. | `test_hundred_thousand_codes_get_distinct_pseudonyms` ; 4 clés sur 5 en collision à 100 k | Élargir à 10–12 hex (A) et 8 (W/R/P), ou retirer avec suffixe au lieu de refuser ; corriger le commentaire. | S |
| AUDIT-APP-02 | Mineur | `standards.py:109, 146-150` | CWE-20 ; ISO 25010 Fault tolerance | TOML de mauvaise forme (`params=[1,2]` → `TypeError` ; `metric="x"` → `AttributeError`) échappe aux handlers qui n'attrapent que `ValueError` : page Schedule health plantée. | `test_params_of_wrong_shape_raise_value_error`, `test_metric_table_of_wrong_type_raises_value_error` | `isinstance` sur `metric` (liste), chaque entrée (dict), `params` (dict) → `ValueError`. | S |
| AUDIT-APP-03 | Mineur | `standards.py:176, 208` | CWE-674 | 2 000 tables inline imbriquées (12 KB) → `RecursionError` hors de `discover_standards` : un fichier déposé bloque toutes les pages. | `test_deeply_nested_toml_is_refused_as_a_load_error` | Attraper `RecursionError` → `ValueError("TOML too deeply nested")`. | S |
| AUDIT-APP-04 | Mineur | `standards.py:85-86` | ISO 25010 Functional correctness | `target="pass"` accepté sur une métrique `%` → devient `== 1 %` en silence. | `test_pass_target_requires_pass_fail_unit` | Refuser `pass` hors unité `pass/fail` et réciproquement. | S |
| AUDIT-APP-05 | Mineur | `rules.py:138-141` | CWE-20 | `nan`/`inf` acceptés comme paramètre numérique ; toute comparaison False → pass silencieux. | `test_nan_parameter_is_refused` | `math.isfinite` dans `_check_value`. | S |
| AUDIT-APP-01 | Mineur | `standards.py:97-103` | CWE-20 | `id`/`name` non vérifiés `str` (`id = 5` accepté) : clés mémo et colonnes CSV de types mixtes. | `test_metric_id_and_name_must_be_strings` | `isinstance(..., str)` sur les clés texte. | S |
| AUDIT-APP-12 | Mineur | `cli.py:187` | CWE-22, CWE-20 | Id de métrique injecté dans un nom de fichier `--flagged` sans assainissement ; `/` → `OSError` non géré (`../` ne peut pas sortir grâce au préfixe `{stem}_`). | `test_flagged_file_name_survives_a_metric_id_with_a_slash` | Valider les ids au chargement (`^[A-Za-z0-9._-]+$`). | S |
| AUDIT-APP-10 | Mineur | `cli.py:128, 170` | ISO 25010 Error protection | `--standard` invalide ou `--baseline` absent → traceback brut au lieu de `xerscope: ...`. | `test_invalid_standard_file_is_a_clean_cli_error`, `test_missing_baseline_file_is_a_clean_cli_error` | `try/except (ValueError, OSError) → SystemExit(f"xerscope: {exc}")`. | S |
| AUDIT-APP-11 | Mineur | `cli.py:213-218`, `checks.py:189` | ISO 25010 Reliability | `--expect` CSV malformé → `ParserError` ; compte non numérique → `ArrowInvalid` ; tracebacks. | `test_expect_with_malformed_csv_is_a_clean_cli_error`, `test_expect_with_non_numeric_count_is_a_clean_cli_error` | Attraper et sortir proprement avec le nom du fichier. | S |
| AUDIT-APP-09 | Mineur | `cli.py:20-31` | ISO 25010 Maintainability (doc ≠ code) | Docstring « exit 2 », code réel 1 (`SystemExit("msg")`) ; indiscernable de `--fail-on`. | `test_check_on_missing_path_exits_two` | Message sur stderr + `SystemExit(2)`, ou corriger la docstring. | S |
| AUDIT-DEP-01 | Mineur | `deploy/compose.yaml:63, 89` | SLSA v1.0 (immutable refs) ; CIS Docker 4.x ; OpenSSF Scorecard Pinned-Dependencies | Images applicatives tirées par tag mutable `:latest` (`xerscope`, `xerscope-caddy`) alors que le `Dockerfile` racine épingle ses bases par digest. Un push compromis sur GHCR est déployé au prochain `pull`. | Lecture ; `grep latest deploy/compose.yaml` | Tags de version immuables produits par `image.yml` (`metadata-action` type=semver/sha) + digest ; documenter la montée de version dans `docs/deploy.md`. | S |
| AUDIT-DEP-02 | Mineur | `.github/workflows/image.yml:69-77` | SLSA v1.0 Build L2/L3 ; NIST SSDF PS.3 ; Scorecard Signed-Releases | `build-push-action` sans `provenance: true`, `sbom: true` ni signature cosign/attestation GitHub : l'image publiée n'a pas de provenance vérifiable. | `grep -n 'provenance\|sbom\|attest' .github/workflows/*.yml` → vide | `provenance: mode=max`, `sbom: true`, puis `actions/attest-build-provenance` (permissions `id-token: write`, `attestations: write`). | S |
| AUDIT-DEP-03 | Info | `deploy/compose.yaml:40` | CWE-526 ; CIS Docker 5.x | `TS_AUTHKEY` passé en variable d'environnement (visible par `docker inspect`). Déjà documenté « first start only, then delete » ; `TS_AUTH_ONCE` limite l'exposition. | Lecture `docs/deploy.md:150` | Alternative : Docker secret / fichier monté `TS_AUTHKEY_FILE` si supporté par l'image tailscale ; sinon garder la consigne. | S |
| AUDIT-DEP-04 | Info | dépôt | Scorecard SAST/Fuzzing ; SSDF PW.8 | Pas de CodeQL ni de fuzzing du parser ; bandit seul (4 Low bénins). Pas de tag de version, pas de `CHANGELOG`. | `git tag` vide ; `grep -il codeql\|fuzz` vide | Activer CodeQL (gratuit sur dépôt public) ; fuzz ciblé `parse_bytes` (Hypothesis ou Atheris) ; SemVer + Keep a Changelog quand l'API se stabilise. | M |
| AUDIT-APP-06 | Info | `store.py:77-97, 189-215` | ISO 25010 Reliability | `SnapshotStore([])` accepté (API seule) ; `summary` a une ligne fantôme, `.first` lève `IndexError`. | `test_empty_store_is_refused_or_consistent` | `if not snaps: raise ValueError`. | S |
| AUDIT-CPM-08 | Info | `calendar.py:337` | ISO 25010 Functional accuracy | Minutes fractionnaires arrondies half-to-even par placement ; TF exact en minutes entières. Comportement P6 inconnu. | `test_sub_minute_lags_round_to_the_minute` | Documenter la granularité minute dans `docs/cpm.md`. | S |
| AUDIT-CPM-09 | Info | `cpm.py:712-721` | ISO 25010 Functional appropriateness | Projet entièrement terminé : `finish` = data date, `tf_hr` dtype `object` (`None`). | `test_all_activities_finished_empty_forward_pass` | Typer `tf_hr`/`ff_hr` en float NaN ; décision métier sur `finish`. | S |

Bilan : 0 Critique, 7 Majeurs, 28 Mineurs, 6 Info. Tous Majeurs sauf AUDIT-XER-05 sont des corrections S
(validation d'entrée ou gestion d'exception).

## 3. Tests ajoutés

| Fichier | Tests | Verts | xfail (défauts) | Durée |
|---|---|---|---|---|
| `tests/test_audit_edges_xer.py` | 94 | 76 | 18 | ~15 s |
| `tests/test_audit_edges_cpm.py` | 56 | 47 | 9 | ~40 s |
| `tests/test_audit_edges_app.py` | 38 | 23 | 15 | ~8 s |

```bash
uv run pytest tests/test_audit_edges_xer.py tests/test_audit_edges_cpm.py tests/test_audit_edges_app.py -q
```

Résultat observé : `146 passed, 42 xfailed`. Chaque `xfail` est `strict=True` et porte l'ID du constat dans sa
`reason` : corriger le défaut fait échouer le test tant que le marqueur n'est pas retiré, ce qui force la mise à
jour de ce rapport. Les tests n'utilisent que `tests/xerkit.py` (aucun fichier réel). Les suspects de boucle infinie
sont gardés par `signal.alarm`.

## 4. Métriques mesurées

### Gate (CONTRIBUTING.md et le skill xerscope (« Verification gate »))

| Commande | Résultat |
|---|---|
| `uv run pytest -rs` | 1 363 passed, 40 skipped, 686 s (skips : MPXJ sans Java 37, witness absent 1, divers 2) |
| `uvx ruff check src tests` / `format --check` | All checks passed / 127 files already formatted |
| `uvx bandit -r src -ll` | 0 Medium, 0 High (4 Low : assert d'invariant module `diagnostic.py:563`, `subprocess` en liste sans shell `cli.py:75`, `random` non crypto dans `sample.py:746`) |
| `uvx pip-audit` (45 paquets, OSV + PyPI) | No known vulnerabilities found |

### Complexité (radon, cyclomatique ≥ 20 ; seuil Sonar 15)

| Fonction | CC |
|---|---|
| `xer/parser.py:parse_text` | 42 |
| `analysis/cpm.py:_Run.forward` | 42 |
| `analysis/cpm.py:_Run.successor_limits` | 41 |
| `analysis/cpm.py:_Run.level_of_effort` | 33 |
| `anonymize.py:Anonymizer.table`, `.frame` | 24, 24 |
| `cpm.py:_Run._assignments`, `_network`, `pred_bounds`, `backward` | 24, 23, 22, 22 |
| `sample.py:_cpm`, `_progress`, `_task_row` | 22, 21, 20 |
| `cpm.py:_Run.longest_path` | 20 |

Indice de maintenabilité radon < 40 : `cli.py` 17, `sample.py` 16, `anonymize.py` 21, `diagnostic.py` 30 (B/A ;
aucun C). Modules > 1 000 lignes : `cpm.py` 1 664, `model.py` 1 317, `app/state.py` 1 238.

### Performance CPM (chaîne de N activités + N/4 liens aléatoires, `schedule` seul)

| N | schedule (s) | µs/activité | RSS (MB) |
|---|---|---|---|
| 1 000 | 0,17 | 167 | 122 |
| 4 000 | 0,67 | 169 | 140 |
| 16 000 | 2,67 | 167 | 203 |
| 64 000 | 13,19 | 206 | 440 |

Exposant 0,99–1,15 : linéaire O(N+E), aucune récursion (passe avec `recursionlimit(1500)`).

### Mémoire parser (fichier généré en code, 49 MB, 231 k lignes TASK)

| Opération | Temps | Pic | Ratio |
|---|---|---|---|
| `parse_bytes` complet | 14,2 s | 608 MB | 12,4 × |
| `parse_bytes(keep=HEADER_TABLES)` | 7,8 s | 153 MB | 3,1 × |
| Ligne unique 50 MB | 0,06 s | 150 MB | 3,0 × |

### Couverture de branches (`pytest --cov=xerscope --cov-branch`, suite complète hors tests d'audit)

| Total | Instructions | Branches |
|---|---|---|
| 90,7 % | 7 320 (562 manquées) | 1 856 / 2 178 |

Modules les moins couverts : `app/streamlit_app.py` 0 % (point d'entrée, 13 lignes), `verify/mpxj_reader.py` 16 % et
`verify/mpxj_cpm.py` 21 % (MPXJ skippé sans Java), `cli.py` 73 % (80/126 branches : les chemins d'erreur, cf.
AUDIT-APP-09/10/11), `analysis/explain.py` 80 %, `analysis/rules.py` 83 %, `analysis/standards.py` 86 %,
`xer/calendar.py` 90 % (55/70 branches), `xer/parser.py` 90 % (35/42). Le cœur (`cpm.py`, `model.py`, `store.py`)
est au-dessus de 94 %. Les tests d'audit ajoutés couvrent précisément les branches manquantes de `parser`,
`calendar`, `standards` et `cli`.

### Chaîne d'approvisionnement (lecture type Scorecard)

| Contrôle | État |
|---|---|
| Actions épinglées par SHA + commentaire de version | oui, toutes |
| `permissions:` minimal par workflow | oui (`contents: read`, `packages: write` sur image) |
| `pull_request_target` | absent |
| Bases d'image par digest | oui (`Dockerfile`), non (`deploy/caddy/Dockerfile` : tag `caddy:2.11.8`) |
| Images déployées | tag mutable `:latest` (AUDIT-DEP-01) |
| Dependabot | uv, actions, docker ×2, compose |
| Lock vérifié en CI | `uv sync --locked` |
| Scan vulnérabilités | pip-audit (OSV+PyPI), trivy image, bandit |
| SBOM / provenance / signature | non (AUDIT-DEP-02) |
| SAST sémantique (CodeQL) / fuzzing | non (AUDIT-DEP-04) |
| SECURITY.md, LICENSE, CONTRIBUTING | oui |
| Releases/tags signés, CHANGELOG | non |
| Protection de branche, CODEOWNERS | non vérifié (API GitHub non interrogée) / absent |

### Conteneur (CIS Docker)

`USER nonroot`, distroless, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit`, `pids_limit`,
tmpfs bornés, healthcheck, réseau `internal: true` sans passerelle, aucun port publié dans `deploy/`, loopback seul
dans `compose.yaml`. Pinné par `tests/test_docker.py`. Conforme.

## 5. Dette et architecture

- **Couches** : `tests/test_architecture.py` vérifie les imports contre `docs/architecture.md` ; 0 cycle d'import sur
  59 modules (script ad hoc, Tarjan). Trois vues importent directement `xer`/`cpm` (`debug.py` → `CycleError`,
  `export.py` → `parse_bytes`, `gantt.py` → `STATUS`) : admis par l'allowlist, mais `export.py` qui parse un fichier
  dans une page est l'écart le plus net au tableau « Where things go » (une page ne calcule pas).
- **Gros modules** : `cpm.py` (classe `_Run` monolithique, 9 méthodes à CC ≥ 20) ; `model.py` (`build_snapshot`
  orchestre 15 tables) ; `app/state.py` (cache, sélection de projet, baseline, anonymiseur, notices dans un seul
  module). Candidats à scinder sans changer la sortie (cf. `docs/backlog.md` § Structure).
- **Frontière de types** : le contrat « strings dans le parser, types dans le modèle » est juste, mais la validation
  des *valeurs* (fini, borné, positif, unique) n'a pas de lieu unique : elle manque au modèle (durées négatives,
  `inf`, `task_id` dupliqués) et au moteur (types de lien inconnus). Un module `xer/validate.py` appelé par
  `build_snapshot` fermerait 8 constats d'un coup (XER-06/07/08/11/13, CPM-01/02/06).
- **Exceptions** : deux types métier (`XerError`, `CycleError`) mais les appelants n'attrapent que ceux-là ; les
  exceptions pandas/datetime brutes remontent. Règle à écrire : tout ce qui sort de `xer/` et `analysis/` est
  `XerError`, `CycleError` ou `ValueError`.
- **Mutabilité** : `Snapshot` et `Schedule` sont des dataclasses non gelées avec caches attachés par
  `object.__setattr__`. Fonctionne car aucun appelant n'écrit ; non garanti.
- **CLI** : gestion d'erreur inégale (`DuplicateDataDate` propre, le reste en traceback) ; code de sortie 1 pour
  usage et pour échec de check.

## 6. Non vérifié

- **MPXJ crosscheck** : 37 tests skippés, pas de JDK dans le conteneur (`uv sync --extra crosscheck` requiert Java
  21/25). Le différentiel moteur vs MPXJ n'a pas été rejoué.
- **Witness P6** : 1 test skippé, dossier `tests/reference/data/witness` absent (données locales).
- **Protection de branche GitHub, revue obligatoire, secrets du dépôt** : non interrogés.
- **Comportement navigateur des téléchargements** (`Content-Disposition` avec un code projet contenant `../` ou des
  caractères de contrôle, `views/export.py:36`) : lecture seule, non exercé.
- **Concurrence** du cache `_xs_schedule` entre threads Streamlit : non reproduit.
- **Mutation testing** (`mutmut`) : non exécuté dans cette phase (prévu en phase 4, deep dive tests).

## 7. Questions au métier (non tranchées, hors audit logiciel)

1. `24:00` lu comme `NaT` : P6 l'écrit-il pour minuit ?
2. Blob calendrier sans jour ouvré remplacé en silence par une semaine inférée : à signaler ?
3. Poste de nuit `22:00 → 02:00` tronqué à minuit (2 h au lieu de 4) : P6 exporte-t-il ces périodes ?
4. Durée restante négative : borner à 0 ou rejeter le fichier ?
5. `task_code` vide accepté comme identité : à signaler comme les doublons ?
6. Boucle composée uniquement d'activités terminées : bloquer tout, ou planifier le reste et signaler ?
7. Boucle passant par un LOE : invisible pour le moteur et INT-04 ; P6 la signale-t-elle ?
8. Projet entièrement terminé : `finish` = data date ou dernière fin réelle ?
9. Métrique `count` sur population vide → `pass`, la même en `%` → `n/a` : voulu ?
10. Clé HMAC d'anonymisation vivante en session seulement : une série hebdo anonymisée en deux sessions a deux jeux
    d'IDs. Contrat voulu, ou clé conservée par projet ?
11. Cibles hors plage (`<= -5%`, `>= 500%`) acceptées : refuser, avertir, ou « toujours rapporter » ?
12. Neutralisation CSV (`'` devant `=`) acceptable pour les consommateurs Power BI, ou limiter aux téléchargements
    destinés à Excel ?

## Annexes

- Détail par zone (tableaux complets, « Verified OK », scripts de sonde) : `scratchpad/audit/findings_xer.md`,
  `findings_cpm.md`, `findings_app.md`, `cpm_scaling.py` (hors dépôt).
- Plan de mise en conformité par écart, soumis à validation : `conformity-plan.md`.
