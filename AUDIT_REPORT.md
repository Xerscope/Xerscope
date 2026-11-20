# Audit xerscope — tests, code, maintenabilité, ops

Date : 2026-11-20. Commit audité : `44ef2de` (main).
Portée : constats seulement, aucun correctif appliqué.

## 1. Méthode

- 7 agents « finders » (3 sur les tests, 3 sur le code source, 1 ops), briefés sur CONTRIBUTING.md, chaque constat avec fichier:ligne et commande.
- 3 agents « validateurs » adverses ont rejugé chaque constat (CONFIRMÉ / NUANCÉ / REJETÉ) et cherché ce qui avait été manqué.
- Bilan : 96 constats bruts, 45 confirmés, 46 nuancés (vrais mais surestimés ou dette déjà documentée), 2 rejetés, quelques invérifiables (MPXJ sans jpype ici).
- Mesures prises dans la session :

| Mesure | Résultat |
|---|---|
| `uv run pytest -rs -n 4` | 4109 passés, 44 skips (MPXJ : jpype absent), 9 min 19 s |
| ruff check / format, bandit `-ll` | propres |
| `scripts/fitness.py --check` | ratchet tenu, 3 valeurs améliorées |
| Tests collectés avec marqueur `oracle` | 1777 / 4153 (43 %) ; 62 fichiers de test sur 114 n'en ont aucun |
| Corpus P6 held-out, part de valeurs identiques (re-mesure) | 54 492 / 54 726 = 99,57 % ; 18 jeux sur 30 à 100 % |
| mypy (dette ratchetée) | 90 erreurs, 3 dans `analysis/cpm.py` |
| Mutation (baseline) | progress 86,6 %, calendar 74,9 %, standards 63,4 % tués ; 3 modules sur 79 |

Ce qui est solide et ne mérite pas de travail : actions CI épinglées par SHA (43/43), image distroless non-root digest-pinnée avec SBOM et provenance SLSA, CSV safe sur l'unique `to_csv`, aucun `unsafe_allow_html`, code mort quasi nul (2 fonctions), identité `task_code` respectée partout, goldens regénérés avec justification `ID: old -> new — source` dans les commits lus.

## 2. Tests : qualité, utilité, impartialité

### 2.1 Impartialité (le test dit-il la vérité sur sa source ?)

1. **Étiquette `oracle("p6")` sur 13 des 17 fichiers `test_cpm_<règle>.py`** alors que leur en-tête dit « hand calculations from that rule, not P6 readings » (ex. `tests/test_cpm_free_float_zero.py:38`). La taxonomie (`tests/conftest.py:31`) n'a pas de genre « hand » ; le rapport oracle surcompte donc l'évidence P6. Confirmé-nuancé.
2. **Le corpus « held-out » a servi de source aux règles.** `docs/cpm.md:44` le dit honnêtement (« PINNED names the corpus activity each rule of the engine was taken from »). Le mot « held-out » vient du projet amont (gelé avant P6), pas de xerscope. Conséquence : aucun jeu P6 que le moteur n'a jamais vu n'existe dans le dépôt. Le score 99,57 % est un score de régression, pas de généralisation. Nuancé (documenté), mais à nommer clairement.
3. **Source dangling** : `tests/test_cpm_milestone_expected_finish.py:3` cite `docs/deep-dive/engine-gaps.md`, absent de main (existe seulement sur une branche non fusionnée). 17 tests invérifiables depuis main. Le même fichier (l.123) fixe une frontière « no source says P6 keeps a one-minute finish » : valeur d'implémentation écrite comme attendue.
4. **`tests/test_custom_standard_equals_p6.py` (885 lignes) compare code à code** : paramètres « read off the code », attendu = sortie du check P6. Utile comme test de refactoring, pas comme preuve de justesse ; marqué `property`. Faire apparaître « differential » dans le nom ou la docstring.
5. **`tests/test_app_parity.py` et `tests/test_weekly.py:1252`** dérivent l'attendu en rappelant l'API ou en refiltrant les mêmes colonnes modèle. Plomberie, pas oracle. La parité le dit dans sa docstring ; `test_weekly` non.
6. **Jeu Ask « heldout » à 100 %** (`tests/test_ask_bench.py:21`, 20 phrases, jamais retouché depuis le 1er commit, floor 1.00) : il n'est plus held-out, c'est de la régression.
7. **`tests/test_docker.py:73-128`** lit `tests.yml` par regex et compare à `tests.yml` lui-même (liste des jobs) : tautologique en partie. Le reste du fichier (50 tests, 92 `read_text`) épingle du texte de config, choix documenté (docstring, CONTRIBUTING:141) et doublé par les jobs CI `container`/`deploy` qui exécutent vraiment l'image. Coût d'entretien élevé pour une valeur de détection faible.

### 2.2 Utilité (le test tombe-t-il sur un vrai défaut ?)

8. **DECM 06A209a n'a aucun test à la main** (`grep` vide) et son golden vaut toujours 0/pass. **16 des 56 métriques du golden** ne sont figées qu'à une valeur triviale (numérateur 0, `flagged` vide) : DCMA-09/12/13, 06A208a/209a/401a/504a/505a/506c, INT-03/04/08, P6-02/05/10a/16 ; 350 entrées « n/a ». Pour ces 16, le golden ne détecte qu'un passage à non-nul que la démo ne produit jamais.
9. **Mutation : 3 modules, hebdo, hors PR** (`pyproject.toml:75`, `mutation.yml`), et les 60 fonctions `@rule` sont hors de portée de mutmut. Le ratchet accepte 36 % de mutants vivants dans `standards.py` (131 survivants non triés).
10. **FLOORS (`tests/test_p6_heldout.py:25`) = dernier taux mesuré à 3 décimales.** 234 valeurs divergentes ne sont listées nulle part ; 1 à 5 régressions par jeu passent (H10 : floor 0,982, mesuré 0,9829). `NOT_P6` dans `test_cpm.py:55` montre le bon motif : nommer les exceptions. Idem `tests/test_p6_heldout.py:136` : 0,966 sans source, `FT_Start` sans plancher.
11. **MPXJ cross-check** (`tests/test_crosscheck_mpxj.py:143`) : floors à 0,85-0,95 et `unexplained()` excuse tout un réseau dès qu'un motif UNRESOLVED est présent. Non re-mesuré ici (pas de jpype). Tourne en CI uniquement dans le job Windows.
12. **Hypothesis** : le profil `ci` à 1000 exemples est documenté (`tests/test_fuzz_parser.py:17`) mais aucun workflow ne pose `HYPOTHESIS_PROFILE=ci` ; la frontière de confiance est fuzzée à 20 % de la profondeur annoncée. Confirmé.
13. **`tests/test_p6_witness.py`** (la comparaison aux rapports P6 Professional réels, l'oracle le plus fort) ne tourne jamais en CI (`witness` dans aucun `XERSCOPE_REQUIRE`) ; le rapport P6 derrière `test_p6_checksched.py` n'est pas stocké.
14. **Tests d'implémentation** : `tests/test_cpm.py:777-801` monkeypatch `cpm._comparison` et compare la sortie à elle-même ; `tests/test_app.py:1140` patche `Path.read_bytes`, `hashlib.file_digest` et un logger privé Streamlit (`:2393`) ; environ 128 lectures de `session_state["…"]` et 90 lookups par clé de widget dans les tests app. Cassent au refactor sans changement visible.
15. **`tests/test_viz.py:346`** : seul test de `gantt.js` (421 lignes) = absence de 11 sous-chaînes. Node est disponible, aucun test comportemental.
16. Assertions faibles ou disjonctives : `tests/test_load_contract.py:190` (`is None or year < 2200`), `:222` (`!= inf` passe sur NaN), `tests/test_parser.py:47` (`raises` sans `match`), `tests/test_app.py:132` (`test_every_page_renders` : seul test des pages Activity et Debug, vérifie `not at.exception` et un titre), `tests/test_cli.py:142` (`len > 0`). Tests sur horloge murale : `tests/test_ask_limits.py:17`, `tests/test_app_background.py:124` (deadline 300 s).

### 2.3 Qualité et organisation

17. **Marqueur `oracle` absent sur 57 % des tests**, concentré : `test_cpm.py` 0/61, `test_model.py` 0/48, `test_time_semantics.py` 0/36, `test_query.py` 0/39, `test_cli.py` 0/32, `test_viz.py` 0/27, `test_app.py` 6/153… Le job `oracle-report` est `continue-on-error: true` (`tests.yml:53`) : la règle n'est jamais appliquée. Docstrings : `test_cpm.py` 21/61, `test_parser.py` 0/6.
18. **Fichiers monolithes** : `test_app.py` 3098 l./153 tests (109 asserts composés `and`/`or`, tests de 70 lignes), `test_rules.py` 2171 l. (mélange P6/DCMA/DECM/INT), `test_weekly.py` 1413 l. (6 features, section « pinned from the page output » = caractérisation non marquée).
19. **Duplication d'échafaudage** : `APP = ` dans 10 fichiers, `PAGES` dans 4 avec contenus différents (`test_cache_invariant.py:19` oublie `activity` et `forensics` : pages non couvertes par l'invariant de cache), `_ok` ×3, `_read/_population` ×3 (`rulekit.py` existe), `OPTION_ON/OFF` ×7 et `resource()` ×2 dans les `test_cpm_*`, `random_network` importé depuis `test_cpm_properties` par 5 modules de test, builders XER/calendrier à la main à côté de `xerkit` (`test_model.py:162`, `test_cpm_resource_start_float.py:28`).
20. **Les 17 `test_cpm_<règle>.py`** sont des familles de règles (94 tests), bien sourcées, mais la liste de fichiers est le seul index. Consolidables en 4 fichiers (contraintes, expected finish, ressources, float).

## 3. Code source : standards CONTRIBUTING

### 3.1 Structure (où ça va)

21. **`app/state.py` 2101 l., 127 fonctions, ~7 responsabilités** : cache de parsing, lexique Ask, threads de chargement, UI sidebar/fenêtre fichiers, ~790 lignes de résolution + picker de baseline, chrome de page, téléchargements anonymisés. Coutures visibles dans le fichier.
22. **`analysis/cpm.py` 2497 l.** : `_Run` 444-2084 (91 méthodes, ~40 dicts d'état) + deux consommateurs dans le même fichier : comparaison aux dates stockées (2161-2262) et test de chemin critique DCMA (2265-2497), qui n'appellent que `schedule()`. Couture propre pour un split.
23. **`app/diagnostic.py:1`** : docstring « Nothing here computes a date or a count » ; contient groupby/pivot, un parseur numérique P6 et `p6_export_frame`. Importe `ui.as_dates` donc Streamlit (chargé seulement pour `pv-compare`, import paresseux `cli.py:434`).
24. **`cli.py`** : 13 sous-commandes, docstring en liste 9 ; ~280 lignes d'outillage ask-bench/lexicon ; `_cmd_check:199` a sa propre précédence de baseline alors que l'app passe par `analysis/baseline_resolution.py` ; `_expect_differs:262` parse le CSV Check Schedule comme `views/health.py`. Deux politiques, deux parseurs.
25. **Vues en script module-level** : `views/debug.py` 433 lignes top-level, `gantt.py` 233 ; testables uniquement par AppTest (`docs/backlog.md:209` le reconnaît).
26. **`sample.py` (834 l.) embarque un second moteur CPM jour** (`_early_dates:214`) puis relit et réécrit chaque fichier avec `analysis.cpm.schedule` (`_store_p6_dates:457`). Deux modèles d'ordonnancement, double écriture.
27. **`viz/charts.py:147` `build_scurve`** calcule l'échelle % BAC lui-même ; `views/earned_value.py:276-366` tient 90 lignes de formules EV hors `analysis/explain.py` (règle « explication d'une métrique → explain.py »).
28. **`analysis/ask/`** : 2995 lignes, 14 fichiers tous en dérogation docstring, `lexer.py:242 _code_items` complexité F(44), 70 des 82 noms à une lettre de la couche analyse. Déterministe, utilisé (state.py, cli, query.py).

### 3.2 Lisibilité, noms, duplication

29. Fonctions > 60 l. : `evm.pv_p6_comparison` 150 (diagnostic, pas KPI, dans le module KPI), `earned_value.show_calculation` 128, `model._task_frame` 112, `model.build_snapshot` 110, `wbs.rollup` 81, `charts.build_mta` 81, `build_scurve` 80, `state.sidebar_loader` 77. Imbrication 4 : `cpm.forward_constraints:1144`, `late_constraints:1524`, `_file_links:561`, `resource_placement.common_late_finish:380`, `parser._Reader.line:252`. Complexité : `state._folder_boxes` 18, `overview.score_section` 17.
30. **Noms interdits par CONTRIBUTING Names 1-2, 6** : `TimeAxis.cal` (`xer/calendar.py:375`, attribut public, l'exemple même de la règle), `preds` (`cpm.py:525`), `df` (`store.py:230`, `export.py:49-81` ×8), `s` pour snapshot (`state.py:959…`), boucles `c`/`a, b`/`d`/`e` (`calendar.py:66,181,211,217`). 104 helpers privés appelés une fois dans app/viz/cli (ex. `_parse_cached`, `data_locked()` → `_data_locked()`).
31. **Conversions d'unités à la main** : 22 lignes `* 60`/`/ 60` dans `cpm.py` (`:567, :1397 ×4…`), pas de `MINUTES_PER_HOUR` ; jours→heures d'un délai écrit 3 fois (`cpm.py:2296, 2437, 2486`) avec un `or` qui change de calendrier silencieusement (`:2408`). Le dépôt a déjà rencontré `8.2*60 = 491.99999999999994` (`verify/mpxj_cpm.py:173`).
32. **Populations à la main** : `progress.py:139, 207, 268, 366` réécrivent `~is_milestone & ~is_loe` alors que `populations.without(...)` existe (règle 5 : « défaut même si les nombres sont justes »). `progress.py` n'a aucun Funnel : les populations PPC ne peuvent pas être montrées.
33. **Clones de checks** (`scripts/duplication.py` 0,92-0,99) : `dcma_02/03` (seul `lt` vs `gt`), `p6_08/09`, `dcma_06/p6_06`, `dcma_07/p6_14`, `decm_06a505a/b`, `_without_float_note` vs `_no_float_note`. Une correction de note = 2 à 6 éditions.
34. Motifs bannis (Readable 5) : ternaires chaînés `ask/clauses.py:59`, `ask/parser.py:160` ; condition évaluée deux fois `integrity.py:293` ; 18 compréhensions imbriquées (14 dans ask/, `audit.py:172`).
35. Dette typage : `resource_placement.py:28` annote `duration_minutes: float` avec le commentaire « None = the activity's » ; c'est la racine des 3 erreurs mypy de `cpm.py:689/735/740`. Pas de bug runtime (filtré par `driving()`), annotation fausse.

### 3.3 Sources et documentation (règle 1 et 2)

36. **`docs/standards.md:23`** dit DCMA « Long durations : original > 44 wd » ; le code (`fourteen_point.py:247`), `dcma.toml:85`, `formulas.md:265` et… la même page à la ligne 253 disent « baseline duration ». Une cellule.
37. **`docs/cpm.md:34-39`** affiche 89,0 % de valeurs identiques (81 % ressources) alors que FLOORS ≥ 0,982 et la re-mesure donne 99,57 %. Doc 10 points en retard sur le moteur.
38. **Fonction supprimée toujours documentée** : `query.llm_backend` / `XERSCOPE_QUERY_URL` / service `llm` (`architecture.md:157, :417`, `backlog.md:150-152`) retiré par `100f201` (#172) le 2026-11-09. Un lecteur sécurité croit à un chemin réseau sortant qui n'existe pas.
39. **`docs/backlog.md:202-211`** (Structure) : hotspots cités (`parse_text` 17, `build_gantt` 16) n'existent plus ; compte `set_index("task_code")` faux (17 vs 13).
40. Sources manquantes : `integrity.toml:28` INT-03 sans `source` (seul métrique calibrée sur P6 sans source) ; 11 docstrings DECM sans référence 06Axxx (`decm/schedule_metrics.py:57, 118, 183, 292, 330…`) alors que P6 et DCMA citent toutes. `csv_safe.py:3` liste des appelants qui ne l'importent pas (ils passent par `export.csv_bytes`).
41. Dérogations ruff D : 45 instances sur 12 fichiers du moteur (cpm.py 8), 14 fichiers ask/ ; `tests/test_docstrings.py` porte une seconde baseline à la main (`LONG`, MAX_DEBT 267) hors du format fitness.

### 3.4 Sécurité au bord (CWE-79 côté Markdown)

42. **Texte issu du fichier rendu en Markdown sans `ui.md_text`** : `views/overview.py:90` (aucune mitigation), `views/forensics.py:184` (`without_addresses` ôte les URL, pas `*`, `[ ]`, `$`), `views/earned_value.py:186` (`st.caption` avec `schedule.note`). `ScheduleError` embarque des Activity ID (`cpm.py:409, 554`). 12 autres sites appliquent `md_text`. Effet : cosmétique dans un bandeau d'erreur ; non exploité en session. `views/audit.py:239` est de l'input utilisateur, pas fichier.

## 4. Maintenabilité : plan de nettoyage proposé (ordre conseillé)

Chaque étape est un refactor « zéro changement de valeur » : golden + FLOORS + `scripts/same_code.py` + fitness comme filet, PR ≤ 400 lignes.

1. **Docs d'abord** (coût nul, risque nul) : §36-39, 40, 41 ; renommer « held-out » en « corpus de régression P6 » dans `docs/cpm.md:28` et dire explicitement qu'aucun jeu P6 non vu n'existe.
2. **Taxonomie des oracles** : ajouter un genre `hand` (calcul à la main sourcé) et `differential` (code vs code) dans `conftest.ORACLE_KINDS` ; remarquer les 17 `test_cpm_*`, `test_custom_standard_equals_p6`, `test_app_parity`, section 1226 de `test_weekly`. Rendre `oracle-report` bloquant avec une baseline ratchetée du nombre de tests sans marqueur (2376 aujourd'hui, ne monte jamais).
3. **Tests : échafaudage commun** : `APP`, `PAGES` (dérivé du registre des pages), `ok(at)`, `random_network`, `_read/_population`, `OPTION_ON/OFF`, `resource()` dans `conftest.py`/`xerkit.py`/`rulekit.py`. Puis scinder `test_app.py` par page, `test_rules.py` par standard, `test_weekly.py` par feature, fusionner les 17 `test_cpm_*` en 4.
4. **Evidence engine** : remplacer les FLOORS par un ensemble nommé de (jeu, cas, activité, champ) connus différents (motif `NOT_P6`) ; restaurer ou remplacer la source `engine-gaps.md` ; `HYPOTHESIS_PROFILE=ci` dans le job test ; `witness` dans un job manuel documenté ou rapport P6 anonymisé commité.
5. **Goldens utiles** : faire produire par `sample.py` au moins un flag par métrique (les 16 triviales) ; test à la main pour 06A209a.
6. **Mutation** : trier les 131 survivants de `standards.py` ; rendre les `@rule` mutables (muter le corps non décoré) ; ajouter `cpm.py` et `evm.py` ; sous-ensemble « modules touchés » sur PR.
7. **Code, par couture** : (a) `cpm.py` → `cpm_compare.py` + `cpt.py` ; (b) `state.py` → `baseline_picker.py` (résolution pure séparée des widgets), `downloads.py`, `jobs.py`, `session_cache.py` ; (c) `diagnostic.py` : `as_dates` et les parseurs P6 vers `analysis/` ; (d) CLI : un seul lecteur de CSV Check Schedule, une seule précédence de baseline ; ask-bench/lexicon vers `scripts/` ; (e) formules EV vers `explain.py`, `ev_pct` dans `evm_series` ; (f) `sample.py` : un seul moteur.
8. **Lisibilité au fil des touches** (pas de renommage de masse) : `cal`→`calendar`, `preds`, `df`, `s` ; `hours_to_minutes()` dans `calendar.py` ; `without()` dans `progress.py` ; helpers `lag_check`/`float_check` partagés ; `_code_items` scindé ; sortir ask/ de la liste de dérogations fichier par fichier.
9. **Bord Markdown** : `ui.md_text` sur les 3 sites + un AppTest avec un Activity ID contenant `[x](…)`.

## 5. Ops : RTO/RPO, maintenance, déploiement interne, enterprise-ready

### 5.1 État des lieux (faits)

- **Données** : l'app ne persiste rien d'elle-même ; exports montés `:ro` (`compose.yaml:15`, `deploy/compose.yaml:142`), caches en `session_state` uniquement. Seul état inscriptible : lexique Ask `suggested/` (append) et `generated/` (régénérable), volume `tailscale-state`, fichier `.env`.
- **Image** : ghcr.io, tags `latest` / `sha-<short>` / semver sur tag `v*` (`image.yml:79-82`) ; **0 tag git**, 440 commits en 22 jours, CHANGELOG « 0.1.0 unreleased ». Les exemples de pin `xerscope:0.1.0@sha256` (`docs/deploy.md:171, 223`) nomment une image qui ne peut pas être tirée aujourd'hui (la procédure de digest existe `deploy.md:242-247`).
- **Durcissement** : distroless non-root, `read_only`, `cap_drop ALL`, `no-new-privileges`, HEALTHCHECK, limites mem/pids dans `deploy/compose.yaml` (absentes du `compose.yaml` racine), pas de `logging:` par choix.
- **Auth** : un seul couple basic-auth Caddy (`deploy/Caddyfile:57`) + préfixe secret + rate-limit ; TLS par Tailscale ; secrets en variables d'env `.env` (`docs/deploy.md:210` l'admet : visibles par `docker inspect`) ; pas de `secrets:` compose.
- **Observabilité** : healthcheck seul ; `/_stcore/metrics` bloqué 404 ; pas de log structuré applicatif, pas d'identité utilisateur dans le log d'accès.
- **Supply chain** : Dependabot (uv, actions, 3 docker, compose) avec cooldown 7 j ; Trivy quotidien ; exceptions bornées : `deploy/tailscale.trivyignore.yaml` expire **2026-12-09**, `.github/trivy/self.trivyignore.yaml` ×3 **2026-12-16** ; floors de dépendances datés 2026-10-28 à bumper à la main ; CONTRIBUTING `uvx ruff` non épinglé vs CI `ruff@0.17.4`.
- **Déploiement** : Docker Compose uniquement (+ notes Synology). Pas de Helm, manifeste k8s, unit systemd ; `linux/amd64` seul (`docs/deploy.md:58`).
- **Licence** : `LicenseRef-Proprietary`, LICENSE « No licence is granted » ; `docs/deploy.md:331` parle de « source déjà publique ». Un déploiement interne tiers n'a pas de droit d'usage écrit.

### 5.2 RTO / RPO de fait, et ce qui manque

| | Aujourd'hui | Manque |
|---|---|---|
| RPO | Exports = source de vérité hors app → 0 pour les analyses. Lexique `suggested/`+`curated/`, `.env`, `tailscale-state` : **non sauvegardés, perte totale possible** | une section « quoi sauvegarder / comment restaurer » (3 chemins, une commande), test de restauration |
| RTO | Re-pull de 2 images + `.env` + Build ; si `tailscale-state` perdu : nouvelle clé + suppression de la machine. Temps **jamais mesuré ni écrit** | un objectif chiffré (ex. < 30 min), le temps mesuré de pull/build, une procédure de bascule testée |
| Rollback | « digest précédent » (`deploy.md:223`) | une release taguée pour qu'un digest ait un nom |

### 5.3 Plan de maintenance : points à cadrer

- **Releases** : couper `v0.1.0` (ou rc), cadence écrite, CHANGELOG fermé par version ; sinon « pin 0.1.0 » reste de la documentation d'intention.
- **Calendrier** : bump Tailscale avant le 2026-12-09, exceptions Trivy avant le 2026-12-16 ; bump des floors `pyproject` à chaque mise à jour du lock (règle écrite mais manuelle) ; rafraîchissement des pins de corpus (dernier 2026-11-02) et de la baseline mutation (2 commits) sans propriétaire ni cadence.
- **Baselines à ratchet** : fitness (ok, 35 commits, descend), mutation (3 modules), `LONG` docstrings, dérogations ruff D par fichier, oracle (pas de ratchet). Un seul format et un seul job qui les vérifie tous.
- **Bus factor** : un mainteneur, CODEOWNERS, auteur unique dans les commits. À nommer dans le plan.

### 5.4 Déploiement infra interne et enterprise-ready : écarts

1. **Identité** : pas de SSO/OIDC, pas d'autorisation, un mot de passe partagé, aucune attribution par personne dans les logs. Option à chiffrer : oauth2-proxy ou identité Tailscale devant Caddy, puis en-tête d'identité consommé par l'app pour le log.
2. **Secrets** : `secrets:` compose / `TS_AUTHKEY_FILE`, hash Caddy par fichier ; rotation documentée.
3. **Packaging infra** : un chart Helm ou un manifeste k8s minimal + unit systemd pour compose ; `arm64` si NAS/Apple ; `compose.yaml` racine aligné sur `deploy/` (limites).
4. **Observabilité** : exposer `/_stcore/health` et un `/metrics` filtré en interne, logs JSON applicatifs (fichier lu, projet choisi, durée, erreur), sans nom de fichier réel (règle vie privée du projet).
5. **Multi-tenant** : aujourd'hui un dossier = tout le monde voit tout. À décider : une instance par équipe (simple, cohérent avec le modèle) ou un modèle de dossiers par identité.
6. **Contrat** : licence d'usage interne écrite, SLA/RTO/RPO écrits, politique de support (`SECURITY.md` : main + dernière image).

## 6. Dix points à traiter en premier (synthèse)

1. Oracle : genres `hand`/`differential`, remarquage des 17 `test_cpm_*` et des tests code-vs-code, `oracle-report` bloquant avec ratchet.
2. Source dangling `engine-gaps.md` (17 tests) et doc `cpm.md` 89 % vs 99,6 % mesuré ; renommer « held-out ».
3. FLOORS → liste nommée des valeurs connues différentes ; `HYPOTHESIS_PROFILE=ci` en CI.
4. 06A209a sans test ; 16 métriques au golden trivial ; démo à enrichir.
5. Mutation : `@rule` mutables, `cpm.py`/`evm.py`, survivants triés.
6. `state.py` et `cpm.py` scindés sur leurs coutures ; `diagnostic.py` et `cli.py` dédoublonnés.
7. `progress.py` sur `populations.without`, clones de checks factorisés, `hours_to_minutes`.
8. Docs fausses : `standards.md:23`, `llm_backend` ×3, `backlog.md` Structure, INT-03 sans source.
9. `md_text` sur overview/forensics/earned_value.
10. Ops : tag `v0.1.0`, section sauvegarde/restauration avec RTO/RPO chiffrés, échéances Trivy 09 et 16 décembre, secrets compose, décision SSO.

Détail brut (96 constats, verdicts et commandes) : `/tmp/claude-0/-home-user/dd32ff8e-9391-5523-bd48-9c69cc3b9488/scratchpad/findings/` (7 fichiers finders, 3 fichiers `V_*.md` validateurs).
