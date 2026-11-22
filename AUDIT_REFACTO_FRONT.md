# Audit de la session « refactor front » (44ef2de → origin/main c43194a)

Date : 2026-11-22. Objet : branches `claude/intelligent-dijkstra-0r0ydb` et `claude/modest-bell-mrx7pv`, PR #334, #339, #340, #341, #342 ; 62 commits, 99 fichiers, +15 285 / −3 501. Plan : `docs/refactor-front-plan.md` (P1…P17).
Constats seulement, aucun correctif appliqué. Méthode identique au premier audit : 6 finders (organisation, preuve, tests, docs, lisibilité, process) puis 3 validateurs adverses ; 64 constats bruts, 2 rejetés, la plupart nuancés à la baisse. Les corrections des validateurs sont intégrées ci-dessous.

## 1. Verdict en cinq lignes

1. **Le découpage de `state.py` est réussi sur le fond** : 2101 → 311 lignes, 13 modules, aucun cycle d'import, `analysis/` n'importe jamais `app/`, `standards.json` intact, fitness en amélioration partout (mypy 91 → 85), duplication inchangée, aucune valeur métrique du golden déplacée par les commits de refactor, chaque test modifié a sa raison dans un message de commit.
2. **Mais l'organisation reste à moitié faite** : `ui.py` a grossi (796 → 985), `diagnostic.py` / `debug.py` / `earned_value.py` sont inchangés ou plus gros, 46 imports de noms `_privés` entre modules, les clés `session_state` restent des littéraux dispersés, et le garde d'architecture ne voit pas la forme d'import la plus courante.
3. **Un changement de comportement a été livré sous le titre « refactor »** (P17 : quelle baseline chaque page lit). Pour une série multi-baselines, EV/PV/SPI et les checks changent pour le même fichier et le même choix utilisateur. Déclaré dans le corps du commit et le plan, testé (7 tests), mais invisible au golden (démo mono-baseline) et faux dans le titre.
4. **Le process a cédé sur la taille** : #334 = 49 fichiers, +10 509 lignes, 34 commits, 4 merges de main dedans, un fix sécurité et deux comportements inclus. La règle des 400 lignes et la séparation refactor / comportement ne sont pas tenues.
5. **~7 160 lignes d'artefacts de session sont commitées dans `docs/`** (votes, JSON du critique, brief d'exécuteur, scripts dont un ne démarre pas), contre la règle écrite `CONTRIBUTING.md:227-229`.

## 2. Ce qui est vérifié et tient

- Suite complète sur c43194a : voir §7. Goldens : `standards.json` inchangé ; `pages.json` régénéré 4 fois par le refactor (e51f2dd, 5a1a5b5, 53fe98b, 1b7568f), chaque message nomme ce qui bouge (UF-03, DP-13, VB-02, VB-16…), aucune ligne de valeur métrique ne change (lu hors popovers).
- `scripts/same_code.py 44ef2de` : 436 définitions sur 2220 diffèrent (250 modifiées, 164 ajoutées, 21 supprimées, 1 renommée) ; `duplication.py` à 0,9 : 42 lignes avant et après, aucune paire nouvelle.
- Fitness : seulement des lignes « better » ; un module sans entrée est tenu au rang A / 0 fonction > 15 par `fitness.py:168-175` (contrairement à ce qu'un finder avançait).
- Ordre du plan respecté (P6-0, P6-1, P6a, puis P6c après fusion de #334, puis P6d). Auteur Mishima sur 62/62 commits, aucun trailer outil dans les PR, aucun workflow modifié, une seule dérogation ruff retirée (state.py), aucune ajoutée.
- Suppression de `views/activity.py` : propre, aucune référence pendante, contenu dans `task_panel.py`.
- Tests existants modifiés : aucune suppression, une renommée, chaque valeur attendue changée a sa source dans le message (ex. e51f2dd : « -4 d » → « -4 cal. d » = VB-02).
- Garde symlink du root des dossiers : `realpath` résout bien un lien sortant (testé en scratchpad). `gantt.js` : noms entiers, pas d'`innerHTML`.

## 3. Organisation du code (le sujet de l'enquête)

| # | Constat | Preuve | Gravité |
|---|---|---|---|
| O1 | **`test_architecture.py` ne voit pas `from xerscope.app import ui`** : `app_imports` garde seulement `module.startswith("xerscope.app.")` (l.94). `session.py:12`, `baselines.py:31`, `baseline_window.py:14`, `baseline_warnings.py:27`, `files_window.py:13`, `loading.py:19`, `state.py:13`, `xml_baselines.py:29`, `explanation_panel.py:6` importent `ui` ainsi ; `APP_EDGES["session"] = set()` et le test passe. Le garde cité comme preuve du layering ne peut pas échouer sur l'arête la plus fréquente. | code lu, AST exécuté | **haute** |
| O2 | **`ui.py` a grossi de 24 %** (796 → 985). `theme.py` (62) et `table_filters.py` (119) extraits, mais `runtime_table()` (~400 lignes de données Debug, l.59-464) reste dans le module « look ». P12a livré à moitié. | `wc`, lecture | moyenne |
| O3 | **`session.py` est un fourre-tout nommé « leaf »** : drafts de fenêtre, `_period`, `counted`, `_section_title` (dessine), cache de parse `_parse/_pmxml_index`, `debug_page`, `folder_root`. Le plan P6a sanctionne ce contenu ; mais `_parse` devait aller dans `cache.py` (spec P6c) et une feuille qui importe `ui` (24 importeurs) n'est pas une feuille. | plan l.478-482, l.585-590 | moyenne |
| O4 | **46 imports de noms `_privés` entre modules** (0 avant : un seul fichier) : 18 depuis `session.py` (`_digest`, `_parse`, `_open_window`, `_period`…), `baseline_warnings` ← `_baseline_options`, `_baseline_short`, `_fallback_options` de `baseline_window`, ré-importé par `files_window`. Le souligné ne dit plus « privé au fichier ». Hors périmètre du move byte-identique, donc dette de suite, pas défaut du move. | AST | moyenne |
| O5 | **Clés `session_state` toujours littérales** : `session.py` définit 12 constantes, mais 67 subscripts (59 avant) et ~165 `key="…"` distincts restent en dur sur 21 fichiers (`guid_link` ×12, `ev_basis` ×7, `bl_fallback` ×7). Abréviations `bl_`, `snap_` contraires à Names 2. | grep, comptes dépendants de la méthode | moyenne |
| O6 | **`loading.py` (452 l.) : trois responsabilités** : chargement (`LoadJob`, `load_series`), lexique Ask (`lexicon`, `refusals`, `teach`, l.85-150), dessin sidebar (`draw_sidebar`, `sidebar_loader`, l.383-440). | lecture | basse |
| O7 | **`baselines.py` dessine** (`sidebar.caption/error` l.71-81, `_fallback_picker`) alors que `docs/architecture.md:279-284` dit « Draws nothing ». Le plan P6c y met ces fonctions : c'est la doc qui est fausse, pas le code. | code + doc | basse |
| O8 | **Les gros fichiers visés ne bougent pas** : `diagnostic.py` 985 → 981, `views/debug.py` 537 → 627, `views/earned_value.py` 572 → 623 (merges module-level l.609-610 toujours là), `show_calculation` 128 → 126 l., `build_mta` 81 → 70, `overview.score_section` cognitive 21 et a grossi. P5 a enlevé des doublons, pas de la taille. | `git diff --stat`, radon | moyenne |
| O9 | **`state.py` importe des noms soulignés** de `loading` (`_files_count`) et `session` (`_open_window`) ; la fonction `state.baseline_warnings` porte le nom du module `baseline_warnings.py`. | `state.py:19-35`, `:144` | basse |
| O10 | **Dérive doc / code / plan** : `architecture.md` §7 sans entrée pour `files_window`, `loading`, `explanation_panel`, `table_filters` ; son entrée `state.py` décrit encore la sidebar et `LoadJob` ; `APP_EDGES` a `cache → baselines` là où le plan dit `baselines → cache` ; `docs/backlog.md` « Structure » non touché, liste encore du travail fini. | grep | moyenne |

**Lecture d'ensemble** : la coupe a suivi le plan (fichiers par domaine baseline / fenêtre / cache / chargement), mais trois choses manquent pour qu'elle soit « organisée » : une API publique nommée entre modules (O4), un propriétaire des clés d'état (O5), et un garde qui voit vraiment les arêtes (O1). Sans O1, O4 et O5 peuvent redériver sans qu'aucun test ne bouge.

## 4. Preuve « aucune valeur ne bouge »

| # | Constat | Gravité |
|---|---|---|
| P1 | **P17 (`1b7568f`) change des nombres calculés** : Health, Audit, Gantt lisent la baseline du fichier ; Earned value lit l'origine de la série par défaut, l'ancien comportement derrière un toggle `ev_p6_view`. `tests/test_pmxml.py` (existant) a été modifié pour activer le toggle avant d'atteindre son attendu 80 h : le test est plié au nouveau défaut. `test_baseline_per_page.py` : 100,0 % (origine) vs 33,3 % (baseline de l'update) pour la même entrée. Le plan l.1159 étiquette bien P17 « behaviour », la décision du mainteneur du 2026-11-20 y est notée, le corps du commit liste ancien/nouveau par page ; seul le titre `refactor(front):` est faux, et le golden ne peut rien voir (démo mono-baseline). | **haute** |
| P2 | **Le périmètre « refactor » contient du comportement venu de main** : 238fba4 (BEI/relink, `BASELINE_READERS` gagne `dcma_13_cpli`), f74f6fe (une update indécise ne prend plus le fallback : attendu inversé dans `test_file_baseline.py`), #332, #336, fix root dossier 9e824e7. Les affirmations « analysis diff empty » par commit tiennent (vérifié sur e51f2dd, 1b7568f) mais sur 44ef2de..main la couche analysis change de +620/−31. | moyenne |
| P3 | **P11b, P9b, P7b, P12b non livrés** ; `export._data_date` lit toujours `last_recalc_date` seul. Le plan l.2132 dit « nine choices wait », alors que P6a/P6c/P7/P9a/P13/P17 sont fusionnés : le plan ment dans les deux sens. | basse |
| P4 | **P13 affaiblit le golden en le déclarant** : les 79 lignes `popover: How to read` ne portent pas le corps ; le texte des lectures n'est gardé que par `test_readings.py` (caractérisation, un seul défaut planté, sur la clé). | basse |
| P5 | **`fitness_baseline.json` pas re-ratcheté** depuis 330647d : 25 gains non verrouillés (files_window cognitive 25 → 15, mypy 91 → 85), entrée `app/views/activity.py` (l.523) toujours là pour un fichier supprimé. Le plan dit que le mainteneur régénère après fusion : à faire. | basse |

## 5. Tests ajoutés (7 fichiers, 76 cas, tous verts, marqueur oracle présent partout)

| # | Constat | Gravité |
|---|---|---|
| T1 | **`test_folder_root.py` (3 tests) sans classes aux limites** pour un garde CodeQL : pas de symlink sortant (le code le gère, rien ne le pin), pas de slash final, `~`, lecteur Windows, casse, root `/`. Reproduit : `XERSCOPE_FOLDER_ROOT=/` refuse tout sous-dossier (`startswith(root + os.sep)` = `//`). Root `/` n'est documenté nulle part comme supporté : défaut fail-closed, mais non spécifié et non testé. Mutation `realpath → abspath` survit. | moyenne |
| T2 | **`test_lookahead.py` ne teste jamais les horizons 4 et 8** (série de 4 updates ; sa docstring le dit) alors que la page les annonce. Réduire `LOOKAHEAD_HORIZONS` à (1, 2) survit. Marqueur `standard` surévalué : les chiffres de Hamzeh fig. 5 sont cités, jamais reproduits ; les attendus sont des comptes à la main dérivés en docstring (bien) sur une convention du projet. | moyenne |
| T3 | **Scans de présence déguisés en tests de comportement** : `test_widget_help.py` accepte tout `help` non vide (« x » passe) ; `test_readings.py` vérifie que `source` contient un nom d'une liste que le test écrit lui-même, puis que cette liste existe dans le dépôt (circulaire). Rien ne compare READINGS à l'annexe E du plan malgré « copied word for word ». | moyenne |
| T4 | **`test_table_contract.py`** : assert sur la config de colonnes rendue (bien), mais `expected_labels` accepte toujours le nom brut du champ et prend les libellés dans `ui.COLUMNS`, le code sous test ; `LISTED_LABELS` est une liste blanche qui grandit. | moyenne |
| T5 | **Aucune preuve par mutation** pour `test_lookahead`, `test_baseline_per_page`, `test_folder_root`, `test_table_contract` (règle : un test nouveau ou réécrit est prouvé par mutation) ; seul `test_readings` plante un défaut, sur la clé. | moyenne |
| T6 | `test_baseline_per_page.py` : bonnes valeurs à la main (40 × 5/15 = 13,3 h), mais Health/Audit/Gantt ne sont vérifiés que par le texte du bandeau, pas par un chiffre ; importe `_series_and_export` d'un autre module de test. `test_loading.py` : chemin heureux seulement, lit `_load_job` / `_parsed`. | basse |
| T7 | Kinds par fichier : 5 caractérisation, 2 standard ; aucun ne nomme sa technique ISO 29119-4 ; `test_loading` marque par test, les autres par module (incohérent). | basse |

## 6. Documentation et artefacts commités

| # | Constat | Gravité |
|---|---|---|
| D1 | **~7 160 lignes d'artefacts de session dans `docs/`** : `refactor-front/findings.json` (3481 l., votes), `review.json` (sortie du critique), `executor-brief.md`, `widgets-without-help.txt`, `security-and-uncovered.md`, `redesign-and-readings.md`, plus 841 lignes d'annexes et de journal dans le plan (« Second pass (19 November) », « four independent skeptic votes », « consensus rule 3/4 », table « Safety net, run once… »). Règle écrite `CONTRIBUTING.md:227-229` : « project context only… No session logs ». | **haute** |
| D2 | **`docs/refactor-front/time_pages.py` ne démarre pas** : `NameError: name 'Path' is not defined` (utilisé l.5, importé l.6). Le plan l.2165 et `review.json:42` affirment « RUNS: Health rerun 0.22 s ». Il référence aussi `state._parse` (déplacé) et la page `activity` (supprimée). | moyenne |
| D3 | **`no_exceptions.sh` : `cd /home/user/Xerscope`** (chemin machine, X majuscule ; avec `set -u` sans `set -e` il continue dans le mauvais dossier). Deux scripts exécutables sous `docs/`, référencés par aucun workflow ni test ; `scripts/` existe. | moyenne |
| D4 | **Textes en double** : annexes E/F du plan (426 l.) dupliquent ~220 lignes de `explain.READINGS` et des `help=` ; la source de vérité est le code, le plan dérive déjà (7 phrases sur 8 échantillonnées introuvables telles quelles). | moyenne |
| D5 | **Numéros de ligne source dans les popovers utilisateur** : 12 des 45 READINGS portent `charts.py:70-83`, `p6.toml:164`… rendus par `ui.py:532-534`. Faux à la prochaine édition, inutile à l'utilisateur. | moyenne |
| D6 | **Sources des lectures** : sur 8 échantillonnées, 2 citent un document externe ; les autres pointent le code de xerscope ou `formulas.md` (règle 2 : une explication de métrique cite sa source). | moyenne |
| D7 | **CHANGELOG** : rien sur les popovers « How to read », les tooltips sur chaque widget, la suppression de la page Activity, la baseline par page ; deux entrées se contredisent sur les ré-exports de `state.py`. | moyenne |
| D8 | Plan stale (P3 ci-dessus), prénom du mainteneur et dates de décision dans un doc versionné (« with Quentin » ×8, « Decided with the maintainer (2026-11-20) »), étiquettes de rôle d'agent (« mechanical executor », « senior ») : narration de session, pas contexte projet. L'email dans `executor-brief.md:42` est celui du `pyproject`, pas une fuite. | basse |

## 7. Process (PR, commits, CI)

| # | Constat | Gravité |
|---|---|---|
| PR1 | **Tailles** : #334 +10 509/−2 400, 49 fichiers, 34 commits (le corps dit « above the 400-line rule by design ») ; #339 +1 970 ; #340 +1 991 ; #341 +814 ; #342 +507. Seules les deux dernières approchent la cible. Revue remplacée par un « independent reviewer agent » et des digests. | **haute** |
| PR2 | **Comportement caché dans des titres de refactor** : e51f2dd supprime une page sous « one unit, one message rule… » ; #334 embarque B12 et le fix root ; #339 deux commits comportement ; 1b7568f (P17) titré refactor. La règle « un refactor ne change aucune valeur » n'est pas vérifiable sur un diff mixte. | **haute** |
| PR3 | **Corps de PR** : aucun « lire d'abord » (Readable 7), aucune section « réutilisé » (règle 5) ; valeurs du golden déplacées jamais au format `ID: old -> new — source` ; sorties de vérification résumées, pas collées. #339 : dernier head vérifié sur un sous-ensemble de 16 fichiers, la suite complète déléguée à CI. Les 245 → 44 skips entre #340 et #341 sont expliqués dans le corps (corpus non téléchargé) : pas un défaut. | moyenne |
| PR4 | **12 merges sur 62 commits**, dont 7 merges de main / du remote dans la branche (4 dans #334) ; 0244518 fusionne la même branche depuis le remote : deux sessions ou mainteneur + agent sur une branche. Le diff de PR mélange #332, #333, #336. | moyenne |
| PR5 | **Messages de commit** : 29 des 58 non-merge ont Problème + Vérification ; 17 n'ont ni l'un ni l'autre ; préfixes incohérents (`P6c:`, `refactor(front):`, aucun). | moyenne |
| PR6 | `no_exceptions.sh` rejoué sur 44ef2de..main : fichiers protégés touchés (pyproject, fitness, pages.json, test_architecture, test_page_golden) et 30+ tests existants modifiés ; les 2 `# fmt: skip` signalés viennent de main (#332, #336), le refactor en a retiré 3 : faux positif. Check `attribution` rouge une fois sur #342 puis vert (cause non lue). | basse |
| PR7 | 45 branches distantes, 4 fusionnées ; une « WIP… (not verified) », une `wip/`. La branche refacto porte un P18 au-delà de ce qui est fusionné. | basse |

## 8. Suite complète

`uv run pytest -rs -n 4` sur c43194a : 4213 passés, 44 skips (MPXJ, jpype absent), 8 min 57 s. Vérifs ciblées faites : `test_characterization`, `test_page_golden`, `test_architecture` (19 passés), les 7 nouveaux fichiers (76 passés), `fitness.py --check` (propre), ruff D sur `src` (propre).

## 9. Ce que j'en conclus pour la suite (ordre proposé, points seulement)

1. **Retitrer / documenter P17 comme comportement** et ajouter un golden sur une série à deux baselines ; supprimer le toggle du test `test_pmxml` au profit d'un attendu re-dérivé par choix.
2. **Fermer le garde d'architecture** : lire aussi `ImportFrom(module="xerscope.app")`, compléter `APP_EDGES` avec `ui`, étendre à `views/`, prouver par un import planté.
3. **Finir la coupe** : noms publics pour les 46 `_imports` croisés ; une constante par clé d'état dans `session.py` ; `_parse/_pmxml_index` vers `cache.py` ; `runtime_table` hors de `ui.py` ; `loading.py` → `lexicon.py` + `sidebar.py` ; puis seulement `diagnostic.py`, `debug.py`, `earned_value.py`.
4. **Nettoyer `docs/`** : supprimer `docs/refactor-front/` et les annexes E/F/G, la table « Safety net » et le journal du plan ; garder dans `architecture.md` les règles qui restent vraies (carte des modules, arêtes, baseline par page) ; corriger « Draws nothing », l'entrée `state.py`, les 4 modules absents ; mettre à jour `backlog.md` et le CHANGELOG ; porter ou jeter `time_pages.py` et `no_exceptions.sh`.
5. **Durcir les tests ajoutés** : table de décision pour `folder_root` (symlink, `..`, slash final, root `/`, casse) ; série de 10 updates pour les horizons 4 et 8 ; `help` non trivial ; retirer `{str(name)}` de `expected_labels` ; un chiffre par page dans `test_baseline_per_page` ; preuve par mutation consignée (mutmut sur `session.py`, `progress.py`).
6. **Process** : une PR par package, comportement séparé du move, corps avec « lire d'abord » / « réutilisé » / `ID: old -> new — source` / sorties collées ; un seul merge de main en fin de branche ; une session par branche ; re-ratcheter `fitness_baseline.json` ; supprimer les branches fusionnées.

Détail brut (64 constats, verdicts, commandes) : `/tmp/claude-0/-home-user/dd32ff8e-9391-5523-bd48-9c69cc3b9488/scratchpad/refacto/findings/` (6 fichiers finders, 3 `V_*.md`).
