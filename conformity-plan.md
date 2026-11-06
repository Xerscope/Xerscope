# Plan de mise en conformité — xerscope

Statut au 2026-11-06 : **blocs A, B, C, D, E, F appliqués** (feu vert de l'auteur, branche `claude/wizardly-ptolemy-b4zjg4`,
voir `audit-report.md` §0) ; **bloc G reporté** après la refonte visuelle et la revue d'architecture. Le texte ci-dessous
est le plan tel que validé ; la colonne Veto porte le résultat. Les lignes futures suivront la même règle : seules les
lignes validées sont implémentées (une PR par bloc, gate complète avant commit, aucun changement de valeur calculée sans
test « échoue avant / passe après »). Les `xfail` de `tests/test_audit_edges_*.py` deviennent verts au fil des
corrections : ce sont les critères de sortie.

## 1. Standard retenu et pourquoi

xerscope est un outil d'analyse open source, un seul développeur, données sensibles traitées localement, image
publiée sur GHCR. Le standard « adapté » n'est pas une certification mais un panier minimal et vérifiable :

| Référentiel | Niveau visé | Pourquoi ce niveau |
|---|---|---|
| **OpenSSF Scorecard** | ≥ 8/10 sur les checks automatisables | Référence de fait pour un dépôt OSS ; mesurable gratuitement en CI. |
| **SLSA v1.0** | Build L2 (provenance signée générée par GitHub Actions) | L3 demande un builder isolé dédié ; L2 suffit pour un déploiement NAS/PC et s'obtient en 10 lignes de YAML. |
| **NIST SSDF SP 800-218** | PW.4, PW.8, PS.3, RV.1 (pratiques, pas d'attestation formelle) | Cadre générique ; on retient les 4 pratiques qui manquent, pas un dossier. |
| **ISO/IEC 25010** | Modèle de qualité pour nommer les constats, cibles mesurables dans `docs/architecture/10-quality-requirements.md` | Vocabulaire commun ; pas de certification visée. |
| **OWASP ASVS 5.0** | V5 (validation/encodage) niveau 1 | L'app n'a ni authentification propre ni base ; V5 est le seul chapitre qui touche le code. |
| **CIS Docker Benchmark 1.7** | section 4 (images) et 5 (runtime) | Déjà quasi conforme ; reste le pinning des images déployées. |
| **ISO/IEC/IEEE 29119-4** | techniques boundary value + equivalence partitioning sur la frontière de confiance | Donne un critère pour dire quand un parser est « assez » testé. |
| **arc42 + C4** | documentation (`docs/architecture/`) | Standard de documentation d'architecture le plus répandu, léger pour un dev solo. |

Écartés : ISO 27001 / SOC 2 (organisationnels, hors sujet), SLSA L3+, ASVS L2-3, certification 25010 formelle.

## 2. Écarts et actions (par bloc, ordre de priorité proposé)

Légende effort : S < ½ j, M 1–2 j, L > 2 j. Veto : ✔ faire, ✘ ne pas faire, ? discuter.

### Bloc A — Frontière de confiance (ASVS V5, CWE-20/248, ISO 25010 Fault tolerance) — ferme 7 Majeurs

| # | Écart | Action | Constats fermés | Eff. | Veto |
|---|---|---|---|---|---|
| A1 | Exceptions brutes hors de `xer/` | Règle : tout ce qui sort de `parse_bytes`/`build_snapshot` est `XerError`. Dans `parse_clndr_data` étendre le `try` à toute la construction (+ `OverflowError`, `RecursionError`) ; dans `parser` : `%T` vide, `%F` dupliqué/changeant → warning ou `XerError`. | XER-01, 03, 04, 14, 15 | S | ✔ fait |
| A2 | Validation des valeurs sans lieu unique | Nouveau `xer/validate.py` appelé en fin de `build_snapshot` : unicité `task_id`/`wbs_id`/`proj_id` (drop + warning), dates à fuseau pré-filtrées, `seq_num` clippé, `day_hr_cnt ≥ 1/60`, durées/lags finis et bornés (< 1e6 h), durée restante négative → 0 + warning, types de lien ∉ {FS,SS,FF,SF} → ignorés + warning. Chaque règle = 1 ligne de `warnings`. | XER-06, 07, 08, 11, 12, 13 ; CPM-01, 02, 06 | M | ✔ fait |
| A3 | `schedule()` plante sur snapshot vide / `es` NaT | Colonnes explicites dans `result` ; repli `es` sur `remaining_start` + warning. | CPM-03, 07 | S | ✔ fait |
| A4 | UTF-16 | Détection BOM UTF-16/32 → décoder ou `XerError` nommant l'encodage. | XER-02 | S | ✔ fait |
| A5 | `[ext]` dans l'espace de noms des Activity ID | Détecter la collision et avertir (pas de changement de nommage : `[ext]` est documenté et testé). | XER-10 | S | ✔ fait |
| A6 | `project_task_counts` par code | Indexer par `proj_id` ; `file_projects` reste la source. | XER-09 | S | ✔ fait |

### Bloc B — Sorties (CWE-1236, ASVS V5.3) — ferme 1 Majeur

| # | Écart | Action | Constats | Eff. | Veto |
|---|---|---|---|---|---|
| B1 | Injection CSV | `export.csv_safe(frame)` : préfixe `'` sur toute cellule texte commençant par `= + - @ \t \r` ; appelée par `export._bytes`, `cli._write_csv`, `anonymize.csv_bytes`. Parquet non concerné. Test sur les trois écrivains. Question ouverte : appliquer aussi aux CSV Power BI (Q12 du rapport). | APP-07 | S | ✔ fait |
| B2 | Pseudonymes trop courts | 12 hex pour les activités, 8 pour WBS/ressources/projets ; corriger le commentaire de probabilité ; test à 100 k codes. Change les pseudonymes émis (pas une valeur calculée). | APP-08 | S | ✔ fait |

### Bloc C — Standards TOML et CLI (ISO 25010 Error protection ; promesse de `docs/standards.md`)

| # | Écart | Action | Constats | Eff. | Veto |
|---|---|---|---|---|---|
| C1 | Forme du TOML non vérifiée | `isinstance` sur `metric` (liste), entrées (dict), `params` (dict), `id`/`name` (str) ; `RecursionError` → `ValueError` ; `target="pass"` ↔ unité `pass/fail` ; `math.isfinite` sur les paramètres ; `id` ∈ `^[A-Za-z0-9._-]+$`. | APP-01, 02, 03, 04, 05, 12 | S | ✔ fait |
| C2 | CLI : tracebacks et codes de sortie | Un `try/except (ValueError, OSError, ParserError, ArrowInvalid)` dans `main` → `xerscope: <msg>` sur stderr, exit 2 pour usage, 1 pour `--fail-on` ; aligner la docstring. | APP-09, 10, 11 | S | ✔ fait |
| C3 | `SnapshotStore([])` | `ValueError("no snapshot")`. | APP-06 | S | ✔ fait |

### Bloc D — Immutabilité et cache (CWE-375/664, ISO 25010 Modifiability)

| # | Écart | Action | Constats | Eff. | Veto |
|---|---|---|---|---|---|
| D1 | `Schedule` mutable partagé | `@dataclass(frozen=True)` ; `frame`/`assignments` renvoyés tels quels mais documentés read-only, ou `.copy()` (coût : une copie par appel, mesurer sur Hotel). | CPM-04 | S | ✔ fait |
| D2 | `Snapshot` mutable avec cache attaché | Option a : `frozen=True` (les `object.__setattr__` existants restent) ; option b : documenter seulement. Recommandation : a. | CPM-05 | M | ✔ fait |

### Bloc E — Parser : mémoire et temps (CWE-400, ISO 25010 Resource utilization)

| # | Écart | Action | Constats | Eff. | Veto |
|---|---|---|---|---|---|
| E1 | Pic 12,4 × | Réécrire `parse_text` en flux : itération sur les lignes sans liste, padding à l'append (plus de copie `fixed`), DataFrame par table dès le `%T` suivant ; cible ≤ 4 × mesurée par le test existant. Sortie identique : `tests/test_parser.py`, `test_reference.py` et le corpus doivent être strictement inchangés. | XER-05 | M | ✔ fait |
| E2 | `TimeAxis` sans borne | Lever `ValueError` dès que `w` dépasse la borne `Timestamp` ; vectoriser `_periods`. | XER-16 | M | ✔ fait |

### Bloc F — Chaîne d'approvisionnement (SLSA L2, Scorecard, CIS 4.x)

| # | Écart | Action | Constats | Eff. | Veto |
|---|---|---|---|---|---|
| F1 | Pas de provenance/SBOM | `image.yml` : `provenance: mode=max`, `sbom: true` ; job `actions/attest-build-provenance` (permissions `id-token: write`, `attestations: write`). | DEP-02 | S | ✔ fait |
| F2 | `:latest` en déploiement (les tags sha/semver et le déclencheur `v*` existaient déjà dans `image.yml` ; le défaut `:latest` de `deploy/compose.yaml` reste pour le premier démarrage, la doc recommande tag + digest) | `metadata-action` : tags `type=sha` + `type=semver` ; `deploy/compose.yaml` par défaut sur un tag immuable + `docs/deploy.md` « monter de version » ; `deploy/caddy/Dockerfile` : digest sur `caddy:2.11.8`. | DEP-01 | S | ✔ fait |
| F3 | Pas de CodeQL | Workflow `codeql.yml` (python, hebdo + PR). | DEP-04 | S | ✔ fait |
| F4 | Pas de fuzzing du parser | Test Hypothesis `parse_bytes(st.binary())` : jamais autre chose que `RawXer` ou `XerError` (critère 29119-4 « equivalence partitioning » de la frontière). | DEP-04 | S | ✔ fait |
| F5 | Scorecard non mesuré | Workflow `ossf/scorecard-action` (lecture seule, badge). | — | S | ✔ fait |
| F6 | Versionnage | Tag `v0.1.0`, `CHANGELOG.md` (Keep a Changelog), bump SemVer par release ; `image.yml` déclenché sur tag. | DEP-04 | S | ✔ fait |
| F7 | `TS_AUTHKEY` en env (consigne conservée, vérification `docker inspect` ajoutée) | Garder la consigne actuelle (first start only) ; ajouter dans `docs/deploy.md` la vérification `docker inspect` après suppression. | DEP-03 | S | ✔ fait |

### Bloc G — Structure (ISO 25010 Modifiability) — à constant output, après A–F

| # | Écart | Action | Eff. | Veto |
|---|---|---|---|---|
| G1 | `_Run.forward` / `successor_limits` CC > 40 | Extraire les branches par type de lien (FS/SS/FF/SF) en fonctions pures testées une par une ; sortie strictement identique (corpus P6 + MPXJ). | L | reporté |
| G2 | `parse_text` CC 42 | Découle de E1 (machine à états par tag `%T/%F/%R/%E`). | — | ✔ fait avec E1 |
| G3 | `app/state.py` 1 238 lignes | Scinder : `state/cache.py`, `state/selection.py`, `state/baseline.py`, `state/notices.py`. | M | reporté |
| G4 | Page `export.py` parse un fichier | Déplacer `parse_bytes` derrière une fonction de `state.py`. | S | reporté |

## 3. Ordre proposé et jalons

1. **A + B + C** (≈ 2 j) : ferme les 7 Majeurs et 20 Mineurs ; `test_audit_edges_*` passent de 42 xfail à ~8.
2. **F** (≈ 1 j) : Scorecard ≥ 8, SLSA L2, CodeQL, fuzz, tag v0.1.0.
3. **D + E** (≈ 3 j) : immutabilité, parser en flux (mesure avant/après), bornes `TimeAxis`.
4. **G** (après la refonte visuelle et la phase 3 architecture, pour ne pas croiser les chantiers).

Critères de sortie globaux : gate CONTRIBUTING.md verte ; `FLOORS` du corpus held-out inchangés ou relevés ; aucun fichier
de référence modifié à la minute ; `tests/test_audit_edges_*` sans `xfail` restant hors ceux marqués « décision
métier » (Q1–Q12 du rapport).

## 4. Hors plan (décisions métier à prendre d'abord)

Les 12 questions du §7 du rapport d'audit. Tant qu'elles ne sont pas tranchées, les tests correspondants restent
`xfail` avec la raison « décision métier en attente ».
