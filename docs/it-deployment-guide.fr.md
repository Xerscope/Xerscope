# Guide de déploiement pour la DSI

English: [IT deployment guide](it-deployment-guide.md)

Ce guide décrit comment xerscope est livré, ce qu'il attend d'un hôte et ce qu'il laisse à
l'organisme qui l'héberge. Il s'adresse à la direction des systèmes d'information (DSI) et au
responsable de la sécurité des systèmes d'information (RSSI) d'un organisme qui traite des
informations sensibles et prévoit d'héberger xerscope pour une équipe de planificateurs.

## Objet, public et statut

xerscope lit les exports hebdomadaires de plannings Primavera P6 (`.xer`) et en tire des rapports.
Il est livré sous la forme d'un paquet Python, d'une image de conteneur de son application web,
d'une image du serveur mandataire inverse (reverse proxy) Caddy et de deux fichiers Compose.

Vous décidez de la sensibilité des données, de la zone, de l'homologation et du durcissement de
l'hôte. Le guide vous donne des faits que vous pouvez vérifier dans le dépôt. Il ne revendique ni
conformité, ni certification, ni homologation. Lorsqu'il cite un document de référence français, il
indique la position des fichiers livrés par rapport à ce document et s'en tient là.

Trois mentions de statut ont un sens fixe. *Non fourni* : le dépôt ne contient rien sur ce point.
*Non établi* : les fichiers ne permettent pas de trancher. *À la charge de l'exploitant* : la
décision ou le réglage vous revient.

### Options de déploiement et état de leurs tests

Le tableau 1 liste les quatre façons d'exécuter l'application web et ce que le projet teste pour
chacune.

**Tableau 1.** Options de déploiement et état de leurs tests

| Option | Description | Livrée | Testée par le projet |
|---|---|---|---|
| A | Le poste de travail d'un planificateur, `uv run xerscope app`, interface de bouclage uniquement | Oui : l'arborescence des sources et [`uv.lock`](../uv.lock) | La suite de tests s'exécute en intégration continue (CI) sur Python 3.11 et 3.14 à chaque poussée (push) sur `main` et à chaque demande de fusion (pull request). Le réglage `address = "localhost"` du paquet maintient l'application sur l'interface de bouclage |
| B | L'image locale avec [`compose.yaml`](../compose.yaml), publiée sur l'interface de bouclage de l'hôte, sans authentification | Oui | [`tests/test_docker.py`](../tests/test_docker.py) fige la publication sur l'interface de bouclage, l'utilisateur non root, la construction à partir du fichier de verrouillage et le contexte de construction. La tâche (job) de CI `container` construit l'image, la démarre, lit `/_stcore/health` sur le port 8501 et lit un dossier monté |
| C | La pile distante [`deploy/compose.yaml`](../deploy/compose.yaml) : Tailscale Funnel, Caddy, l'application | Oui | `tests/test_docker.py` fige l'agencement. La tâche de CI `deploy` valide le fichier Compose, démarre `tailscale` et `caddy` et vérifie les réponses de Caddy, « without the app and without a tailnet login » (sans l'application et sans connexion à un tailnet) ([`tests.yml`](../.github/workflows/tests.yml)). Aucun test n'exerce Funnel, la politique du tailnet ou le certificat |
| D | Un serveur interne derrière votre propre mandataire inverse et votre propre authentification, sans Tailscale | Non | Non |

Les procédures Docker de ce guide combinent les fichiers livrés avec des commandes Docker et Compose
standard. Le projet teste les propriétés nommées dans le tableau 1, non chaque procédure de bout en
bout.

### Versions

Le guide décrit le dépôt au commit `4a8eab2`. La version du paquet est `0.1.0`
([`pyproject.toml`](../pyproject.toml)), et [`CHANGELOG.md`](../CHANGELOG.md) (en anglais) porte le
titre `## [0.1.0] - unreleased` : aucune version publiée n'existe. La ligne de commande n'a pas
d'option `--version` et l'application n'affiche sa version sur aucune page.

Le logiciel est propriétaire : [`LICENSE`](../LICENSE) (en anglais) indique qu'aucune licence n'est
accordée. Les deux polices embarquées sont sous licence SIL Open Font License 1.1
([`NOTICE`](../NOTICE), en anglais).

## Présentation du système

xerscope est un outil de lecture. Il analyse les exports que les planificateurs produisent chaque
semaine, recalcule le planning, exécute des contrôles de qualité et dessine des pages (Gantt, valeur
acquise, journal des modifications, tendance des jalons). Il n'écrit jamais dans un export et ne se
connecte jamais à une base de données P6.

### Composants, utilisateurs et données

L'application web est une application Streamlit démarrée par la commande `xerscope app`. Le même
paquet fournit une ligne de commande (`check`, `export`, `sample`, `lexicon` et huit autres
commandes). L'image Caddy et l'image Tailscale ne concernent que l'option C.

Deux catégories de personnes utilisent un déploiement. Les planificateurs ouvrent les pages dans un
navigateur. Un administrateur de l'hôte installe les fichiers, dépose les exports dans un dossier et
détient les secrets. Tout s'exécute sur votre hôte : les fichiers livrés ne donnent au fournisseur
aucun accès à un déploiement, et les statistiques d'utilisation sont désactivées dans les réglages
Streamlit du paquet (`gatherUsageStats = false`).

L'application lit des fichiers `.xer`, ainsi que des exports P6 XML lorsqu'ils contiennent une
Baseline (planning de référence). Elle lit aussi des standards écrits sous forme de fichiers `.toml`
et, sur deux pages, de petits rapports `.csv` exportés de P6. Un planning contient des noms
d'activité, des noms de WBS, des Activity Codes (codes d'activité), des valeurs de User Defined
Fields (champs définis par l'utilisateur), des ressources, des dates, des durées, des unités, des
coûts et de la logique.

Vous décidez du niveau de sensibilité de ces fichiers, et les informations classifiées sont hors du
périmètre de ce guide. Le dépôt ne contient aucun planning réel : la série de démonstration écrite
par `xerscope sample` est synthétique (huit fichiers, de `PRJ-ALPHA_2026-08-31.xer` à
`PRJ-ALPHA_2026-10-19.xer`).

### Ce qui est stocké, et où

La conception garde les données de planning en mémoire : un export qui n'est jamais copié ne peut
pas être oublié quelque part. Le tableau 2 donne le détail et les exceptions.

**Tableau 2.** Où les données sont stockées, et pour combien de temps

| Emplacement | Contenu | Durée de vie |
|---|---|---|
| Mémoire de session de l'application | Octets téléversés, fichiers analysés, résultats calculés (au plus 128 résultats en cache par session), tables de correspondance de l'outil d'anonymisation (au plus quatre jeux) | La session. xerscope ne fixe pas la durée pendant laquelle Streamlit conserve une session après le départ du navigateur |
| Mémoire du processus de l'application | Le lexique du champ **Ask the schedule** (Interroger le planning), lu une fois par processus. Il ne contient aucune donnée de session | Le processus |
| Répertoire temporaire | Un fichier téléversé de plus de 1 Mo passe par un fichier temporaire pendant son arrivée, sans nom sous Linux et supprimé une fois lu (gestionnaire de téléversement de Streamlit, d'après son code source). Dans les deux fichiers Compose, `/tmp` est un tmpfs, c'est-à-dire de la mémoire | Le téléversement |
| Dossier du lexique (option C) | `suggested/suggestions.toml`, écrit par l'application : une entrée par correction sur laquelle un visiteur clique (mot, libellé, colonne, facette, valeur, heure UTC), jamais la phrase saisie. `generated/variants.toml` et `generated/report.txt`, écrits par `lexicon-init` | Suggestions : purgées après 90 jours. Fichier plafonné à 256 Ko |
| Volume `tailscale-state` (option C) | L'identité du nœud Tailscale | Jusqu'à la suppression du volume |
| Journaux des conteneurs | Voir [Journalisation](#journalisation) de ce guide | Fixée par le service Docker |
| Dossier des exports | Vos fichiers, montés en lecture seule (`:ro`) dans les deux fichiers Compose | Celle que vous décidez |

Les téléchargements sont construits en mémoire. xerscope n'utilise aucun cache de données de
Streamlit (`st.cache_data`, `st.cache_resource`). Un visiteur ne voit donc jamais, par le code de
l'application, les fichiers qu'un autre visiteur a chargés.

### Données personnelles dans un export

Un export peut identifier des personnes, ce qui compte pour votre registre des activités de
traitement. La CNIL définit la donnée personnelle comme « toute information se rapportant à une
personne physique identifiée ou identifiable. » Le tableau 3 liste ce que le code lit.

**Tableau 3.** Données personnelles dans un export

| Donnée du fichier | Affichée par l'application | Écrite dans un téléchargement non anonymisé |
|---|---|---|
| Ligne d'en-tête (`ERMHDR`) : identifiant de connexion et nom complet de l'utilisateur qui exporte, nom de la base de données | Non : seulement la version et le produit | Non |
| Ressources : `rsrc_name`, `rsrc_short_name` (une ressource peut être une personne nommée) | Oui : panneau d'activité, journal des modifications, libellés du champ **Ask the schedule** | Oui : `fact_assignment` contient `rsrc_id`, `rsrc_short_name`, `rsrc_name` |
| Noms d'activité, noms de WBS, valeurs d'Activity Codes, valeurs de User Defined Fields | Oui | Oui |
| Colonnes d'audit de P6 (`create_user`, `update_user`) | Non : aucun code ne les lit | Non |

Les pages affichent toujours les données des fichiers eux-mêmes. Le bouton bascule
**Anonymous exports** (Exports anonymes) de la barre latérale est activé par défaut et ne modifie
que les téléchargements. Lorsqu'il est activé, les Task ID (identifiants d'activité) et les codes de
WBS, de projet, de ressource, de rôle et d'OBS deviennent des codes `X<kind><hex>` dérivés par
HMAC-SHA256 avec une clé tirée pour la session. Les noms sont reconstruits à partir des nouveaux
codes, les coûts sont mis à 0, les autres textes sont vidés et les champs utilisateur de l'en-tête
deviennent `ANON`. Un fichier qui contient encore une valeur d'origine est refusé au lieu d'être
remis. Les dates, les durées, les unités et la logique restent inchangées.

N'importe quel visiteur peut désactiver le bouton bascule pour une session, et aucun réglage ne
l'impose. Lorsqu'il est désactivé, l'export des tables se nomme
`<project code>_xerscope_<format>.zip`. Deux endroits gardent des traces des visiteurs : le journal
de Caddy conserve leur adresse IP, et le fichier des suggestions conserve les mots sur lesquels ils
ont cliqué.

Pour votre registre, deux points découlent des fichiers livrés. La finalité du traitement est
à la charge de l'exploitant : le logiciel lit les exports et dessine les rapports nommés dans la
présentation du système, et rien d'autre. Quant aux personnes qui peuvent voir les données
personnelles, toute personne qui peut ouvrir l'application voit les mêmes pages, car l'application
n'a pas de rôle. L'administrateur de l'hôte peut lire le dossier des exports, le dossier du lexique
et les journaux. Les fichiers livrés ne donnent aucun accès au fournisseur.

## Cadre réglementaire et éléments pour l'homologation

Le régime applicable à votre déploiement dépend de qui vous êtes et de ce que contiennent les
plannings. Le fournisseur n'affirme rien à ce sujet. Cette section consigne ce que disent les
documents de référence français, afin que vous puissiez situer xerscope dans votre propre analyse.
Pour les références complètes, consultez [Références](#références) de ce guide.

### Régimes laissés à votre appréciation

Le tableau 4 liste chaque régime avec ce qu'énoncent les documents cités.

**Tableau 4.** Régimes et ce qu'énoncent les documents cités

| Régime | Ce que disent les documents cités | Source |
|---|---|---|
| RGS | Le guide de l'homologation le cite parmi les réglementations qui rendent l'homologation obligatoire, pour les systèmes « traitant d'informations entre administrations ou entre administrations et administrés ». Le RGS n'est cité qu'à travers ce guide de l'homologation | Guide de l'homologation de l'ANSSI et de la DINUM, Version 2.2 – Mars 2026 |
| Décret sur le système d'information de l'État | Désigné comme « décret n°2022-513 du 8 avril 2022 relatif à la sécurité numérique du système d'information et de communication de l'Etat ». Cité uniquement à travers ce guide de l'homologation | Même guide, §2.4 |
| II 901 | « Tout SI sensible doit être homologué. Toutes les interconnexions de ce SI doivent également être homologuées. » Pour les informations Diffusion Restreinte, « l'application de l'II 901 est obligatoire. » ; pour les informations ordinaires, « ni l'IGI 1300 ni l'II 901 ne s'appliquent. » L'instruction n'est citée qu'à travers le guide ANSSI-PG-075 | ANSSI-PG-075, Version 1.2, 24/09/2021 |
| IGI 1300 | « La mention Diffusion Restreinte n'est pas un timbre de classification mais une mention de protection. » « La transmission d'informations Diffusion Restreinte est interdite sur le réseau Internet ou sur tout autre système d'information non homologué Diffusion Restreinte, sauf à faire l'objet de mesures de protection particulières ». La formulation de ces deux citations n'est pas établie : comparez-la à l'instruction avant de vous y fier | SGDSN, IGI 1300, fichier `igi-1300-20210809.pdf` |
| LPM, opérateurs d'importance vitale | « Ces obligations s'appliquent aux systèmes d'information d'importance vitale (SIIV) désignés par les OIV et comprennent la déclaration d'incidents, la mise en œuvre d'un socle de règles de sécurité ». Une plaquette de 2016 : elle ne prouve pas l'état actuel du code de la défense | Plaquette du SGDSN « La sécurité des activités d'importance vitale – Objectifs et enjeux » |
| NIS 2 | « La transposition de la directive NIS 2 en France est en cours. » Le référentiel ReCyF est un document de travail (« VERSION DE TRAVAIL ») | Page NIS 2 de l'ANSSI, telle que publiée le 26 novembre 2026. ReCyF, Version 2.5 du 17/03/2026 |
| SecNumCloud | « Ce document constitue le référentiel d'exigences applicables à un prestataire de services d'informatique en nuage (SecNumCloud), ci-après dénommé le « prestataire ». » Le fait qu'il concerne ou non un serveur situé dans vos locaux n'est pas établi | Référentiel SecNumCloud, Version 3.2 du 8 mars 2022 |
| RGPD | La sécurité « s'impose à tout responsable de traitement et sous-traitant à travers l'article 32 du Règlement général sur la protection des données (RGPD). » « Le registre est prévu par l'article 30 du RGPD. » | CNIL, guide de la sécurité (fiches datées du 14 mars 2024 ; la phrase sur l'article 32 figure sur <https://www.cnil.fr/fr/securite-avant-propos>) et page sur le registre (13 avril 2018) |

Ces pages ne disent pas si le fournisseur est un « sous-traitant » au sens du RGPD. La réponse
dépend du fait que le fournisseur traite ou non des données pour votre compte, et rien dans les
fichiers livrés ne donne au fournisseur un accès à vos données.

Les fichiers livrés visent un poste de travail (options A et B) et, pour l'option C, selon les
termes de l'en-tête de `deploy/compose.yaml`, « a PC and for a NAS » (un PC et un NAS). Si vous
choisissez plutôt une offre cloud, les questions que SecNumCloud soulève pour les systèmes sensibles
vous reviennent. Le guide de l'ANSSI sur l'hébergement dans le cloud note que la qualification « ne
préjuge en revanche pas du niveau de sécurité des services numériques des clients qui seront portés
par ces offres cloud. »

### Homologation

Le guide de l'homologation définit la décision d'homologation comme « un préalable à toute
utilisation d'un système d'information. » Il décrit trois niveaux (simplifié, intermédiaire,
renforcé), choisis d'après la criticité et l'exposition du système. Ces deux cotations, ainsi que le
niveau, relèvent de votre décision. L'échelle d'exposition compte lorsque vous comparez les
options : « faible : Le système d'information est ouvert uniquement sur des réseaux maîtrisés (par
exemple sur un intranet). » et « total : Le système d'information est directement ouvert sur
Internet ». L'option C publie une URL sur Internet.

Le guide ne nomme aucun dossier qu'un fournisseur d'application doit remettre. Le tableau 5 fait
correspondre les pièces du dossier d'homologation, avec les intitulés de ligne que le guide imprime,
aux sections de ce guide. La pièce exigée à chaque niveau n'est pas établie.

**Tableau 5.** Pièces du dossier d'homologation et sections de ce guide

| Pièce du dossier | Sections de ce guide | Non fourni |
|---|---|---|
| « Document d'accompagnement » | Présentation du système ; Matrice de flux ; Écarts connus et risques résiduels | Les volumes de vos propres données |
| « Dossier d'architecture technique » | Architecture ; Matrice de flux ; Comptes, authentification, sessions et secrets ; Durcissement des conteneurs | Voir le tableau 6 |
| « Matrice de conformité » | Durcissement des conteneurs au regard d'ANSSI-FT-082 | Tout autre socle de mesures, tel que les 42 mesures du guide d'hygiène |
| « Analyse de risque » | Écarts connus et risques résiduels, comme élément d'entrée | L'analyse elle-même |
| « Procédures d'exploitation » | Procédures | La gestion des utilisateurs et le traitement des incidents |
| « Plan de maintien en condition opérationnelle » | Procédures (contrôle de santé, sauvegarde) ; politiques de redémarrage dans Durcissement des conteneurs | Le plan lui-même |
| « Plan de maintien en condition de sécurité » | Origine et intégrité des images et des dépendances ; procédures de mise à jour et de retour arrière | Les délais de correction et un canal de notification de la part du fournisseur |
| « Plan d'action » | Dernière colonne du tableau des écarts, comme élément d'entrée | Le plan lui-même |
| « Plan de résilience » | Procédure de sauvegarde et de restauration | Le plan lui-même. Le temps de reconstruction n'est pas établi |
| « Audits » | Tests et analyses nommés dans ce guide | Le dépôt ne contient aucun rapport d'audit ni de test d'intrusion |
| « « Historique » du système d'information » | `CHANGELOG.md` | Un historique des versions publiées : aucune version publiée n'existe |

La fiche de l'ANSSI « Les Essentiels – Architecture sécurisée de SI » liste les thèmes « à
développer dans un dossier d'architecture technique ». Le tableau 6 indique où ce guide traite
chaque thème.

**Tableau 6.** Thèmes du dossier d'architecture technique et endroits où ce guide les traite

| Thème, tel qu'imprimé | Où |
|---|---|
| « Contextes métier et réglementaire, nature et sensibilité des données et traitements » | Présentation du système ; cette section. Sensibilité : à la charge de l'exploitant |
| « Identification, authentification et gestion des droits d'accès » | Comptes, authentification, sessions et secrets |
| « Cloisonnement réseau, système et stockage » | Architecture ; Durcissement des conteneurs |
| « Chiffrement des données en transit et au repos » | En transit : Architecture (TLS). Au repos : non fourni, les fichiers livrés ne chiffrent rien |
| « Filtrage des flux » | Matrice de flux. Le filtrage lui-même : à la charge de l'exploitant |
| « Accès à distance (nomadisme numérique, tiers) » | Architecture, option C. Accès du fournisseur : aucun livré |
| « Administration (dont la gestion des comptes à privilèges et DevSecOps) » | Comptes ; Origine et intégrité |
| « Maintien en condition de sécurité (MCS) » | Origine et intégrité ; Procédures |
| « Interconnexions (dont celle à Internet) » | Matrice de flux |
| « Protection contre les codes malveillants » | Non fourni |
| « Sécurité physique, contrôle d'accès et vidéoprotection » | À la charge de l'exploitant |
| « Continuité et reprise d'activité (dont les sauvegardes) » | Procédures (sauvegarde et restauration) |
| « Supervision de sécurité (journalisation, détection, traitement des incidents) » | Journalisation. Détection et traitement des incidents : non fourni |

## Architecture

L'architecture découle d'un fait : l'application détient les plannings et n'a pas d'authentification
propre. Chaque option se définit donc par ce qui se trouve entre un navigateur et le port 8501.

### Composants et images

Le tableau 7 est l'inventaire des composants. Les condensés (digests) n'y sont pas recopiés, car
Dependabot les fait évoluer : les lignes `FROM` de [`Dockerfile`](../Dockerfile) et de
[`deploy/caddy/Dockerfile`](../deploy/caddy/Dockerfile) font référence.

**Tableau 7.** Composants et images

| Composant | Construit à partir de | Versions | S'exécute en tant que | Contenu |
|---|---|---|---|---|
| Image de l'application `ghcr.io/xerscope/xerscope` (étiquette locale `xerscope:latest`) | `Dockerfile` : étapes de construction sur `ghcr.io/astral-sh/uv:0.13.8-trixie-slim`, exécution sur `gcr.io/distroless/cc-debian13:nonroot`, chacune épinglée par condensé | CPython 3.14 (version mineure seulement). Streamlit 1.67.0, pandas 3.1.1, plotly 7.1.0 et pyarrow 26.0.1, tels que verrouillés dans `uv.lock` | `USER nonroot`, uid et gid 65532 (les valeurs de l'image de base, d'après le `Dockerfile`) | L'interpréteur, `/app/.venv`, un `/data` vide, un correctif Debian (`zlib1g`). Ni shell, ni gestionnaire de paquets, ni pip (d'après le `Dockerfile`) |
| Image Caddy `ghcr.io/xerscope/xerscope-caddy` | `deploy/caddy/Dockerfile` : `caddy:2.11.9-builder` et `caddy:2.11.9`, chacune épinglée par condensé | Caddy 2.11.9, `github.com/mholt/caddy-ratelimit` au commit `5625512f24f6`, `golang.org/x/net` remplacé par v0.63.0, Go 1.27.4 | L'utilisateur par défaut de l'image. Root dans l'image d'origine : non établi | Caddy et le module `rate_limit`. Le `Caddyfile` et les secrets arrivent à l'exécution |
| Image Tailscale | Non construite par le projet | `tailscale/tailscale:v1.104.7`, épinglée par étiquette (tag), non par condensé | L'utilisateur par défaut de l'image, root d'après le commentaire du fichier Compose : non établi | Celui de Tailscale |
| Polices | `src/xerscope/app/static/` | Onest et JetBrains Mono, sous-ensembles latins | Servies par l'application | Deux fichiers `.woff2` et les textes de leurs licences |

Les images publiées sont construites pour une seule architecture : le workflow n'a ni clé
`platforms:` ni étape d'émulation, l'architecture est donc celle de l'exécuteur (runner)
`ubuntu-latest` (`linux/amd64`).

L'état de maintenance des composants tiers n'est pas fourni. Les fichiers donnent les versions de
Streamlit, pandas, plotly, pyarrow, Caddy et Tailscale, non leur période de support ni leur date de
fin de vie.

Le contenu côté navigateur est limité par construction. Les polices viennent de l'application, le
JavaScript et la feuille de style du Gantt sont des fichiers du paquet, et le dépôt n'ajoute à la
page ni script externe ni lien externe. Ce que le JavaScript propre à Streamlit demande à un
navigateur de récupérer n'est pas établi.

### Réseaux et volumes

Dans l'option B, `compose.yaml` n'a pas de clé `networks:` : Compose crée un réseau de projet pour
l'unique service, et la seule publication est `"127.0.0.1:8501:8501"`.

Dans l'option C, `deploy/compose.yaml` n'a pas de clé `ports:` et déclare deux réseaux. Le réseau
`egress` est un réseau bridge ordinaire auquel seul `tailscale` est rattaché. `caddy`, qui partage
l'espace de noms réseau (namespace) de `tailscale`, dispose de la même sortie. Le réseau `internal`
est déclaré `internal: true`, ce qui le prive de passerelle, et `xerscope` n'est rattaché qu'à lui,
avec l'alias `app`. Le service `caddy` n'a pas de réseau propre : `network_mode: service:tailscale`
le place dans l'espace de noms réseau de `tailscale`, où il écoute sur `127.0.0.1:8080`. Comme
`tailscale` est rattaché aux deux réseaux, ce conteneur dispose lui-même d'un chemin vers
`app:8501`. Le service `lexicon-init` a `network_mode: none`.

Le fichier Compose ne fixe aucun nom de projet. Démarré depuis un dossier nommé `deploy`, le projet
s'appelle `deploy`, les réseaux `deploy_egress` et `deploy_internal`, et le volume
`deploy_tailscale-state`. Le tableau 8 liste tous les montages des deux fichiers Compose.

**Tableau 8.** Montages des deux fichiers Compose

| Fichier | Service | Montage | Mode |
|---|---|---|---|
| `compose.yaml` | `xerscope` | `./exports:/data` | Lecture seule |
| `deploy/compose.yaml` | `tailscale` | `tailscale-state:/var/lib/tailscale` (volume nommé) | Lecture et écriture |
| `deploy/compose.yaml` | `tailscale` | `./tailscale-serve.json:/config/serve.json` | Lecture seule |
| `deploy/compose.yaml` | `caddy` | `./Caddyfile:/etc/caddy/Caddyfile` | Lecture seule |
| `deploy/compose.yaml` | `xerscope`, `lexicon-init` | `${XERSCOPE_EXPORTS:-../exports}:/data` | Lecture seule |
| `deploy/compose.yaml` | `xerscope`, `lexicon-init` | `${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}:/lexicon` | Lecture seule |
| `deploy/compose.yaml` | `xerscope`, `lexicon-init` | `${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}/suggested:/lexicon/suggested` | Lecture et écriture |
| `deploy/compose.yaml` | `lexicon-init` | `${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}/generated:/lexicon/generated` | Lecture et écriture |

### Option A : un poste de travail avec uv

Le planificateur exécute le paquet depuis une copie de travail du dépôt. Avec son hôte par défaut,
`xerscope app` se lie à `localhost` et n'émet aucune requête sortante au démarrage. Une négociation
WebSocket (handshake) dont l'`Origin` n'est ni l'hôte de la requête ni localhost amène Streamlit
1.67.0 à interroger `checkip.amazonaws.com` (port 80, puis 443) pour comparer l'origine aux adresses
de la machine. La requête ne transporte aucune donnée de planning, et la négociation est refusée.
Rien ne sépare l'application des autres processus du poste de travail. Le champ de dossier de la
fenêtre **Files and baseline** (Fichiers et Baseline) lit n'importe quel dossier situé sous une
racine : `XERSCOPE_FOLDER_ROOT`, sinon le dossier que désigne `XERSCOPE_DATA`, sinon le
répertoire personnel. Cette option convient à un planificateur sur une machine et ne vous donne
aucune maîtrise centralisée.

### Option B : l'image locale sur l'interface de bouclage de l'hôte

La même application s'exécute dans un conteneur doté d'un système de fichiers racine en lecture
seule, sans aucune capability et avec un dossier des exports en lecture seule. Le port est publié
sur l'interface de bouclage de l'hôte : l'application est donc joignable depuis l'hôte lui-même et
de nulle part ailleurs. Il n'y a ni authentification, ni limite de mémoire ou de processus, et les
données ne sont pas verrouillées : le champ de téléversement, le champ de dossier (limité à `/data`)
et la page Debug (Débogage) sont disponibles. Un commentaire de `compose.yaml` énonce le choix de
conception : « Exposing it (e.g. "8501:8501") is a deliberate choice; put authentication in front. »
(l'exposer, par exemple avec « 8501:8501 », est un choix délibéré. Placez une authentification
devant).

### Option C : la pile distante livrée

L'option C est un point d'entrée public sur Internet, relayé par un service tiers et protégé par un
seul identifiant partagé. Une requête vers `https://xerscope.<tailnet>.ts.net/<XERSCOPE_PATH>/`
atteint Tailscale Funnel, qui la relaie au conteneur `tailscale`. Dans cette adresse, `<tailnet>`
désigne le nom de votre tailnet et `<XERSCOPE_PATH>` la valeur de cette variable. TLS se termine
dans tailscaled ([`deploy/tailscale-serve.json`](../deploy/tailscale-serve.json)). La requête va
ensuite à Caddy par l'interface de bouclage, puis à l'application par `internal`, dans les deux cas
en HTTP en clair.

[`deploy/Caddyfile`](../deploy/Caddyfile) répond 404 à tout chemin hors du préfixe, avant toute
authentification. À l'intérieur du préfixe, il applique une limitation de débit, puis `basic_auth`,
puis répond 404 sur `/_stcore/metrics` et `/_stcore/agent/*`, puis relaie vers `app:8501`. Le
préfixe existe parce que, comme le dit le commentaire du fichier, les outils de balayage trouvent
chaque nom `*.ts.net` dans les journaux publics de certificats. Le service de l'application est
verrouillé (`XERSCOPE_DATA_LOCKED: "true"`) : pas de champ de dossier, pas de téléversement de
`.xer`, pas de page Debug sauf si vous la demandez. Pour le pas-à-pas sur un NAS Synology, consultez
le [guide de déploiement sur Synology](deploy.md) (en anglais).

Un organisme sensible doit peser cette option au regard de ses propres règles. Aucun texte de
l'ANSSI ou de la CNIL cité dans ce guide ne traite nommément des services tiers de tunnel ou de
relais. Le tableau 9 associe donc chaque propriété de la pile livrée à la recommandation la plus
proche parmi les documents cités.

**Tableau 9.** Propriétés de l'option C et recommandations les plus proches

| Propriété de la pile livrée | Recommandation la plus proche | Formulation |
|---|---|---|
| L'application est joignable depuis Internet | ANSSI-PA-054, R40 « Ne pas exposer d'applications métiers directement sur Internet » | « Celles-ci ne doivent être accessibles qu'une fois le poste nomade connecté au VPN de l'entité. » |
| Les équipements des visiteurs ne sont pas authentifiés : pas de certificat client | ANSSI-PA-054, R40- « Dégradé À défaut - Authentifier les postes nomades avec une fonction dédiée en cas d'exposition d'applications métiers sur Internet » | « avec un serveur intermédiaire reverse-proxy et une configuration stricte reposant sur mTLS (mutual TLS). » La formulation provient du paragraphe qui introduit R40- |
| Les requêtes entrantes arrivent par des connexions que le conteneur `tailscale` ouvre vers l'extérieur, puisqu'aucun port n'est publié | ANSSI-PA-066, R4 « Rendre incontournable la passerelle Internet sécurisée » | « Tout système d'information nécessitant une interconnexion avec Internet doit être protégé par une passerelle Internet sécurisée » |
| Le relais est exploité par un tiers. Ce qu'il peut observer relève de la conception de Tailscale : non établi | ANSSI-PA-066, R15- « Évaluer rigoureusement les risques d'une offre non qualifiée par l'ANSSI pour les fonctions relais externalisées » | « l'analyse de risque doit être menée avec d'autant plus de rigueur et d'exhaustivité. » |
| Un seul identifiant et une seule empreinte de mot de passe servent à tous les lecteurs : aucun n'est distingué dans un journal, aucun ne peut être révoqué seul | Guide d'hygiène informatique, mesure 8 ; guide de la sécurité de la CNIL, fiche 4 « Authentifier les utilisateurs » | « les comptes d'accès doivent être nominatifs. » ; « interdire les comptes partagés entre plusieurs utilisateurs. » |
| Pas d'authentification multifacteur, pas d'expiration de session, pas de blocage après échecs. Les tentatives ne sont bornées que par la limitation de débit de 300 requêtes par minute et par adresse | ANSSI-PG-078, R1 « Privilégier l'authentification multifacteur » ; R10 « Limiter dans le temps le nombre de tentatives d'authentification » ; R12 « Limiter la durée de validité d'une session authentifiée » | « Les secrets temporaires de sessions (comme des cookies par exemple) doivent avoir une durée de vie limitée. » |
| Le canal est chiffré jusqu'à tailscaled, sur votre hôte | ReCyF (document de travail), 8.1-EI/EE | « (par exemple : VPN TLS ou IPSec, protocoles applicatifs chiffrés comme TLS, SSH, etc.). » |

Deux autres propriétés n'ont pas d'équivalent dans le tableau 9. Les hôtes et les ports dont le
conteneur `tailscale` a besoin ne sont pas établis par les fichiers, et aucune variable de serveur
mandataire (proxy) n'est définie. Un visiteur qui détient l'identifiant peut désactiver **Anonymous
exports** et télécharger des tables non anonymisées.

### Option D : un serveur interne derrière votre propre mandataire inverse

L'option D n'est pas livrée et n'est pas testée. C'est votre propre intégration, et c'est vous qui
la testez. Le dépôt ne contient aucun fichier Compose pour elle, et `tests/test_docker.py` fige
l'agencement Funnel de `deploy/compose.yaml`.

Trois éléments livrés peuvent être réutilisés tels quels. L'image de l'application écoute sur
`0.0.0.0:8501` dans son conteneur, et ce qui l'atteint dépend du réseau qu'elle rejoint. Les
définitions des services `xerscope` et `lexicon-init` de `deploy/compose.yaml` portent le
verrouillage, les limites de téléversement, les limites de mémoire et de processus et le réseau
`internal`. L'image `xerscope-caddy` ne contient que Caddy et le module de limitation de débit :
elle peut donc exécuter un autre `Caddyfile`.

Trois fichiers devraient être adaptés, chacun pour une raison que le fichier lui-même montre :

- `deploy/compose.yaml` : le service `tailscale`, son volume et le réseau `egress` ne s'appliquent
  plus. Sur `caddy`, `network_mode: service:tailscale` et `depends_on: [tailscale]` renvoient à ce
  service. Caddy a donc besoin d'un réseau partagé avec `xerscope` et d'un point d'entrée.
- `deploy/Caddyfile` : `default_bind 127.0.0.1` rend Caddy joignable depuis son propre espace de
  noms réseau uniquement. `auto_https off` et l'adresse de site `:8080` signifient HTTP en clair.
  `trusted_proxies static 127.0.0.1/32` désigne tailscaled : tant qu'il ne désigne pas votre
  mandataire, la limitation de débit et le journal voient une seule adresse pour tout le monde.
  L'en-tête `Strict-Transport-Security` et le `; Secure` ajouté aux cookies supposent que les
  visiteurs arrivent en HTTPS.
- `deploy/tailscale-serve.json` : n'est plus utilisé.

Quel que soit le mandataire inverse placé devant, l'application attend de lui cinq choses :

- WebSocket : la bascule en WebSocket (upgrade) sur `/_stcore/stream` passe.
- En-tête `Host` : il parvient inchangé à l'application. Streamlit 1.67.0 accepte le WebSocket
  lorsque l'hôte de l'en-tête `Origin` est égal au `Host` de la requête. Sinon, il n'accepte que
  localhost, l'adresse du serveur, ses propres adresses IP ou `server.corsAllowedOrigins`, que rien
  ne définit.
- Préfixe : l'application sert `/`. `STREAMLIT_SERVER_BASE_URL_PATH` n'est pas défini et un test
  l'interdit. Un mandataire qui publie l'application sous un préfixe retire donc ce préfixe et
  conserve la barre oblique finale.
- TLS : l'application n'en a pas. Streamlit ne marque son cookie XSRF `Secure` que lorsqu'il détient
  lui-même le certificat. C'est pourquoi le `Caddyfile` livré ajoute `; Secure`.
- Authentification : l'application n'en a pas. Sur une instance sans Caddy, `/_stcore/metrics` et
  `/_stcore/agent/openapi.json` répondent 200 à quiconque atteint le port.

## Matrice de flux

Tous les flux de chaque option sont listés ici, à l'exécution et lors de l'installation ou de la
mise à jour. Les ports sont des ports TCP. Un flux qu'aucun tableau ne liste n'est pas nécessaire
aux fichiers livrés. Deux types de flux sont implicites et ne sont pas listés : la résolution de
noms qui précède chaque destination nommée, et les hôtes vers lesquels un registre ou un index de
paquets redirige un téléchargement.

### Flux de l'option A

Le tableau 10 liste les flux d'une exécution sur un poste de travail.

**Tableau 10.** Flux de l'option A

| Quand | Source | Destination | Port, protocole | Ouvert par | Objet |
|---|---|---|---|---|---|
| Exécution | Navigateur sur le poste de travail | `127.0.0.1` | 8501 (`--port`), HTTP et WebSocket | Le planificateur | Pages, téléversements, téléchargements |
| Exécution | Application | `checkip.amazonaws.com` | 80 HTTP, puis 443 HTTPS | Streamlit | Uniquement lors d'une négociation WebSocket depuis une origine étrangère. Aucune donnée de planning |
| Installation, mise à jour | Poste de travail | Le dépôt des sources sur `github.com` | 443, HTTPS (git) | Administrateur | Arborescence des sources. Le fonctionnement d'un clonage anonyme n'est pas établi |
| Installation, mise à jour | Poste de travail | `pypi.org`, `files.pythonhosted.org` | 443, HTTPS | `uv sync --locked` | Les paquets verrouillés, vérifiés par rapport aux empreintes sha256 de `uv.lock` |
| Installation | Poste de travail | La source de téléchargement de uv pour un Python géré | Non établi | uv | Uniquement lorsqu'aucun Python adéquat n'est présent : comportement de uv |

### Flux de l'option B

Le tableau 11 liste les flux de l'image locale.

**Tableau 11.** Flux de l'option B

| Quand | Source | Destination | Port, protocole | Ouvert par | Objet |
|---|---|---|---|---|---|
| Exécution | Navigateur sur l'hôte | `127.0.0.1` de l'hôte, puis le conteneur | 8501, HTTP et WebSocket | Le planificateur | Pages, téléversements, téléchargements |
| Exécution | Contrôle de santé dans le conteneur | `127.0.0.1` du conteneur | 8501, HTTP | Docker, toutes les 30 s | `GET /_stcore/health` |
| Exécution, à chaque démarrage | Conteneur de l'application | `checkip.amazonaws.com` | 80 HTTP, puis 443 HTTPS | Streamlit | Streamlit recherche l'adresse publique pour afficher sa ligne `External URL`. Aucune donnée de planning. Un échec ne change rien |
| Construction | Hôte Docker | `ghcr.io`, `gcr.io` | 443, HTTPS | `docker compose up -d --build` | Les deux images de base |
| Construction | Conteneur de construction | L'archive Debian, sur les miroirs que configure l'image de base uv | Non établi | `apt-get download` | Les paquets de `OS_FIXES` |
| Construction | Conteneur de construction | La source de téléchargement de uv pour le CPython géré | Non établi | `uv python install` | CPython 3.14 |
| Construction | Conteneur de construction | `pypi.org`, `files.pythonhosted.org` | 443, HTTPS | `uv sync --locked` | Les paquets verrouillés |
| Construction | Hôte Docker | Docker Hub | 443, HTTPS | BuildKit | La ligne `# syntax=docker/dockerfile:1.7` désigne une image frontale (frontend). Comportement de BuildKit : non établi |

### Flux de l'option C

Le tableau 12 liste les flux de la pile distante.

**Tableau 12.** Flux de l'option C

| Quand | Source | Destination | Port, protocole | Ouvert par | Objet |
|---|---|---|---|---|---|
| Exécution | N'importe quel navigateur sur Internet | Le point de terminaison public de Tailscale pour `xerscope.<tailnet>.ts.net` | 443, HTTPS | Le visiteur | L'URL publiée |
| Exécution | Conteneur `tailscale` | Les services de Tailscale | Non établi par les fichiers | tailscaled, par `egress` | Plan de contrôle et relais. Le commentaire du fichier indique que « the only outbound traffic is Tailscale's own » (le seul trafic sortant est celui de Tailscale) |
| Exécution | tailscaled | Caddy, `127.0.0.1:8080` de l'espace de noms partagé | 8080, HTTP | tailscaled | Requêtes relayées par Funnel |
| Exécution | Caddy | `app:8501` sur `internal` | 8501, HTTP et WebSocket | Caddy | Requêtes authentifiées |
| Exécution | Contrôle de santé dans le conteneur de l'application | `127.0.0.1` du conteneur | 8501, HTTP | Docker, toutes les 30 s | `GET /_stcore/health` |
| Exécution, à chaque démarrage | Conteneur de l'application | `checkip.amazonaws.com` | 80, puis 443 | Streamlit | Tentée, et sans route : `internal` n'a pas de passerelle |
| À la demande | `lexicon-init` | Aucune | Aucun | Aucun | `network_mode: none` |
| Installation, mise à jour | Hôte Docker | `ghcr.io` | 443, HTTPS | `docker compose pull` | Les images de l'application et de Caddy. Une authentification est nécessaire tant que les paquets sont privés |
| Installation, mise à jour | Hôte Docker | Docker Hub | 443, HTTPS | `docker compose pull`, `docker run` | `tailscale/tailscale:v1.104.7`, et l'image d'origine `caddy:2.11.9` lorsque vous calculez l'empreinte d'un mot de passe avec la commande documentée |
| Installation | Navigateur de l'administrateur | La console d'administration de Tailscale | 443, HTTPS | Administrateur | Politique du tailnet et clé d'authentification. Service tiers, non décrit par les fichiers |

Rien n'écoute sur l'hôte dans l'option C : le fichier n'a ni clé `ports:` ni réseau d'hôte. Le
certificat du nom public est obtenu par Tailscale. Le guide de déploiement sur Synology indique que
Tailscale le demande à Let's Encrypt à la première requête : non établi.

### Flux de l'option D

L'option D n'a pas de matrice de flux livrée. Le côté de l'application est fixe : un flux entrant
vers le port 8501 (HTTP et WebSocket) depuis votre mandataire inverse, le contrôle de santé sur
l'interface de bouclage du conteneur, et la requête de démarrage vers `checkip.amazonaws.com`.

### Flux pouvant être bloqués et fonctionnement sans accès à Internet

À l'exécution, chaque flux sortant de l'application peut être bloqué, quelle que soit l'option. Une
requête vers `checkip.amazonaws.com` échoue sans conséquence : Streamlit ignore l'erreur. Dans
l'option C, les flux sortants du conteneur `tailscale` sont les seuls dont la pile a besoin, et les
fichiers ne les listent pas.

L'application fonctionne sans accès à Internet une fois son image présente. La construction de
l'image nécessite Internet (tableau 11) : l'option B fonctionne donc hors ligne dès que
`xerscope:latest` existe sur l'hôte. L'option C telle que livrée ne fonctionne pas hors ligne : sa
seule entrée est Tailscale Funnel.

## Comptes, authentification, sessions et secrets

Cette section liste chaque compte, utilisateur système, secret et réglage des fichiers livrés.

### Comptes et utilisateurs système

Le tableau 13 liste les comptes. L'application n'expose aucune interface d'administration et le
`Caddyfile` fixe `admin off` : l'administration consiste à accéder à l'hôte, c'est-à-dire au
service Docker, aux fichiers du déploiement et au dossier des exports.

**Tableau 13.** Comptes et utilisateurs système

| Compte | Où | Droits | Remarques |
|---|---|---|---|
| Comptes applicatifs | Aucun | Aucun | L'application n'a ni procédure de connexion, ni rôle, ni liste d'utilisateurs |
| Identifiant partagé de l'option C | `XERSCOPE_USER` et `XERSCOPE_PASSWORD_HASH`, lus par le `basic_auth` de Caddy | Toutes les pages de l'application | Un seul identifiant pour tous les lecteurs |
| Utilisateur du conteneur de l'application | `USER nonroot` (65532) dans l'image ; `user: "${XERSCOPE_UID:-65532}:${XERSCOPE_GID:-65532}"` dans l'option C | Lit le dossier des exports ; écrit dans `suggested/` ; `lexicon-init` écrit aussi dans `generated/` | Le dossier des exports doit être lisible par cet uid |
| Utilisateur du conteneur `caddy` | Pas de clé `user:` | L'utilisateur par défaut de l'image, avec `NET_BIND_SERVICE` pour seule capability | Root dans l'image d'origine : non établi |
| Utilisateur du conteneur `tailscale` | Pas de clé `user:` | L'utilisateur par défaut de l'image, sans aucune capability | Root d'après le commentaire du fichier : non établi |
| Compte de l'hôte qui exécute Docker | Votre hôte | Ceux de Docker | À la charge de l'exploitant |
| Administrateur du tailnet | Console d'administration de Tailscale | Politique, clés, nœuds | Compte tiers, option C uniquement |
| Compte du fournisseur | Aucun | Aucun | Le fournisseur n'a besoin d'aucun accès distant et les fichiers livrés n'en ouvrent aucun |

### Authentification et sessions

Les options A et B n'ont pas d'authentification. Dans l'option C, le navigateur envoie l'identifiant
et le mot de passe avec chaque requête (authentification HTTP de base), et le `basic_auth` de Caddy
vérifie le mot de passe par rapport à une empreinte bcrypt. La configuration de Caddy contient
l'empreinte, non le mot de passe. Une requête sans mot de passe reçoit 401 : la tâche de CI `deploy`
le vérifie. Ce que reçoit un mot de passe erroné et le fait que l'empreinte stockée soit salée ou
non relèvent du comportement de Caddy : non établi. La commande documentée de calcul de l'empreinte
utilise `--algorithm bcrypt --bcrypt-cost 10`. Rien dans les fichiers n'impose une longueur ou une
composition de mot de passe. ANSSI-PG-078 distingue les fonctions de dérivation memory-hard (R29)
des fonctions itératives (R29-). Le texte nomme scrypt et Argon2 pour les premières et PBKDF2 pour
les secondes. Il ne nomme pas bcrypt.

La limitation de débit est de 300 requêtes par minute et par adresse cliente (`events 300`,
`window 1m`, `ipv6_prefix 64`). Elle s'applique avant la vérification du mot de passe, à l'intérieur
du préfixe uniquement. Les réponses 404 hors du préfixe ne sont pas limitées. Un client qui dépasse
la limite reçoit 429 avec `Retry-After`. Il n'y a ni blocage après échecs ni délai après des mots de
passe erronés. Les fichiers livrés ne fournissent ni authentification multifacteur ni connexion à un
fournisseur d'identité.

L'application n'a ni expiration de session, ni expiration sur inactivité, ni déconnexion, ni piste
d'audit, et l'authentification HTTP de base n'a pas non plus de déconnexion. L'effet d'un changement
de mot de passe sur les sessions déjà ouvertes n'est pas établi. Le tableau 14 liste les protections
côté navigateur et l'endroit où chacune est définie.

**Tableau 14.** Protections côté navigateur

| Protection | Valeur | Définie par |
|---|---|---|
| Protection XSRF | `enableXsrfProtection = true`, `enableCORS = true` | Réglages Streamlit du paquet, toutes les options |
| Cookie XSRF `_streamlit_xsrf` | `Path=/`, `SameSite=Lax`, pas de `HttpOnly` (le script de la page le lit) ; `Secure` ajouté par `header >Set-Cookie (.*) "$1; Secure"` | Streamlit 1.67.0 ; `deploy/Caddyfile`, option C |
| Intégration dans un cadre et contenu | `Content-Security-Policy "frame-ancestors 'self'; object-src 'none'; base-uri 'none'"` | `deploy/Caddyfile` |
| HSTS | `Strict-Transport-Security "max-age=31536000; includeSubDomains"` | `deploy/Caddyfile` |
| Autres en-têtes | `Referrer-Policy no-referrer`, `X-Content-Type-Options nosniff`, `Permissions-Policy "camera=(), microphone=(), geolocation=()"`, `header -Server`, `Connection close` sauf lors d'une négociation WebSocket | `deploy/Caddyfile` |
| Mise en cache | `Cache-Control no-store` sur `/`, `/index.html` et `/media/*` | `deploy/Caddyfile` |
| Export des tableaux | `disableDataExport = true`, `toolbarMode = "viewer"` | Réglages Streamlit du paquet |
| Détails des erreurs | `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS: none` | `deploy/compose.yaml` |

Aucun en-tête `X-Frame-Options` n'est défini. Les en-têtes de `deploy/Caddyfile` n'existent pas dans
les options A et B, où l'application répond directement et se nomme dans un en-tête
`server: uvicorn`.

### Secrets

Aucun authentifiant par défaut n'est livré. [`deploy/.env.example`](../deploy/.env.example) ne
contient que des espaces réservés, et Compose s'arrête lorsqu'une des trois valeurs obligatoires
manque. Le tableau 15 liste les secrets.

**Tableau 15.** Secrets

| Secret | Espace réservé dans `.env.example` | Emplacement | Remarques |
|---|---|---|---|
| `TS_AUTHKEY` | `tskey-auth-...` | `deploy/.env` ; environnement de `tailscale` | Lue au premier démarrage uniquement (`TS_AUTH_ONCE: "true"`). Vide par défaut |
| `XERSCOPE_USER` | `<login>` | `deploy/.env` ; environnement de `caddy` | Obligatoire |
| `XERSCOPE_PASSWORD_HASH` | `'$2a$10$...'` | `deploy/.env` ; environnement de `caddy` | Obligatoire. Sans les guillemets simples, Compose lit les signes `$` comme des variables et ne garde que `$2a$10` |
| `XERSCOPE_PATH` | `<random>` | `deploy/.env` ; environnement de `caddy` | Obligatoire. Le préfixe secret de l'URL, sans barre oblique. `openssl rand -hex 12` affiche 24 caractères. Rien ne valide la valeur, et elle sert aussi d'expression régulière dans les filtres du journal |
| Identité du nœud | Aucune | Volume `tailscale-state` | L'emplacement du certificat TLS et de sa clé n'est pas établi |
| Clé d'anonymisation | Aucune | Mémoire de session, `secrets.token_bytes(32)` | Une par session |

Le fichier `deploy/.env` contient ces valeurs en clair, et `.gitignore` le tient hors de git. Sa
protection repose sur les permissions du dossier : à la charge de l'exploitant. Caddy lit ses trois
valeurs à la création de son conteneur. Le contexte de construction de l'image de l'application se
limite à `pyproject.toml`, `uv.lock`, `README.md` et `src/` : l'image ne contient donc ni export ni
secret.

### Réglages lus par l'application

Le tableau 16 liste les variables d'environnement que lit le code de l'application.

**Tableau 16.** Variables d'environnement lues par l'application

| Variable | Valeur par défaut | Effet |
|---|---|---|
| `XERSCOPE_DATA` | Non définie ; `/data` dans l'image | Dossier des fichiers `.xer`. Définie par `xerscope app --data` |
| `XERSCOPE_BASELINE` | Non définie | Un fichier de Baseline séparé. Définie par `--baseline`. Une ligne commentée dans les deux fichiers Compose |
| `XERSCOPE_STANDARDS` | Non définie ; `/data` dans l'option C | Dossier de vos propres standards (`*.toml`), lu à chaque affichage de page. Définie par `--standards` |
| `XERSCOPE_FOLDER_ROOT` | Non définie | Racine sous laquelle un dossier saisi est lu ; sinon `XERSCOPE_DATA`, sinon le répertoire personnel |
| `XERSCOPE_DATA_LOCKED` | Non définie ; `"true"` dans l'option C | Avec `1`, `true` ou `yes` (quelle que soit la casse) : pas de champ de dossier, pas de téléversement de `.xer` ni de Baseline, pas de page Debug |
| `XERSCOPE_DEBUG_PAGE` | Non définie | Avec `1`, `true` ou `yes` : la page Debug sur une instance verrouillée, « to whoever holds the URL » (pour quiconque détient l'URL). Son bloc sur l'environnement d'exécution reste masqué |
| `XERSCOPE_LOAD_WORKERS` | Un processus par cœur, au plus 2 ; `1` dans l'option C | Nombre de processus de lecture. Une valeur supérieure à 2 est lue comme 2 |
| `XERSCOPE_LEXICON` | Non définie ; `/lexicon` dans l'option C | Dossier du lexique du champ **Ask the schedule**. Non définie : l'application n'écrit aucun fichier |
| `XERSCOPE_SYNC_LOAD`, `XERSCOPE_STRICT_READINGS` | Non définies | Utilisées par les tests uniquement |

La commande `xerscope app` accepte aussi `--host` (par défaut `localhost` ; son aide indique que
`0.0.0.0` « exposes your schedules to the network », c'est-à-dire expose vos plannings au réseau) et
`--port` (par défaut 8501). Les réglages Streamlit du paquet ajoutent `maxUploadSize = 200` (Mo par
fichier), que l'option C abaisse avec `STREAMLIT_SERVER_MAX_UPLOAD_SIZE: "1"` et
`STREAMLIT_SERVER_MAX_WIDGET_STATE_SIZE: "1"`. Une autre variable, `XERSCOPE_MPXJ_CPM_JAR`, ne sert
qu'à la commande `crosscheck`, qui ne peut pas s'exécuter dans l'image.

### Réglages de l'option C

Le tableau 17 liste les 13 variables que `deploy/compose.yaml` lit dans `deploy/.env`.

**Tableau 17.** Variables que `deploy/compose.yaml` lit dans `deploy/.env`

| Variable | Valeur par défaut | Effet |
|---|---|---|
| `TS_AUTHKEY`, `XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH`, `XERSCOPE_PATH` | Voir le tableau 15 | Secrets |
| `XERSCOPE_EXPORTS` | `../exports` | Dossier de l'hôte monté en lecture seule sur `/data` |
| `XERSCOPE_UID`, `XERSCOPE_GID` | `65532` | Compte des conteneurs `xerscope` et `lexicon-init`, et propriétaire des tmpfs de l'application |
| `XERSCOPE_IMAGE` | `ghcr.io/xerscope/xerscope:latest` | Image de `xerscope` et de `lexicon-init` |
| `XERSCOPE_CADDY_IMAGE` | `ghcr.io/xerscope/xerscope-caddy:latest` | Image de `caddy` |
| `XERSCOPE_MEM_LIMIT` | `2g` | Limite de mémoire de `xerscope` et de `lexicon-init` |
| `XERSCOPE_LOAD_WORKERS` | `1` | Voir le tableau 16 |
| `XERSCOPE_LEXICON_DIR` | `/docker/xerscope/lexicon` | Dossier de l'hôte monté sur `/lexicon`. Les montages sont inconditionnels, bien que `.env.example` qualifie la ligne de facultative |
| `XERSCOPE_DEBUG_PAGE` | Vide | Voir le tableau 16 |

Trois réglages ne sont pas accessibles depuis `.env` : un fichier de Baseline désigné par
`XERSCOPE_BASELINE` (une ligne commentée de `deploy/compose.yaml`), le `hostname: xerscope` du nœud
et la limitation de débit (`events` dans `deploy/Caddyfile`). Le fichier fixe aussi
`HOME: /home/nonroot` pour l'application. Pour `tailscale`, il définit `TS_USERSPACE: "true"`,
`TS_STATE_DIR: /var/lib/tailscale`, `TS_SERVE_CONFIG: /config/serve.json`,
`TS_EXTRA_ARGS: --advertise-tags=tag:xerscope` et `TS_NO_LOGS_NO_SUPPORT: "true"`, et aucune
variable de serveur mandataire.

## Durcissement des conteneurs au regard d'ANSSI-FT-082

Cette section compare les deux fichiers Compose aux « Recommandations de sécurité relatives aux
déploiements de conteneur Docker » (ANSSI-FT-082, Version 1.0, 23/09/2020), recommandation par
recommandation. Le document indique que « ces recommandations n'ont pas de caractère normatif ». Il
a été rédigé pour Docker « 18.09.3 » et ne mentionne pas Docker Compose : les clés Compose nommées
ici sont les équivalents des options de `docker run` qu'il imprime.

### Recommandation par recommandation

Le tableau 18 donne la position de chaque fichier. Les titres sont ceux du document.

**Tableau 18.** Position des deux fichiers Compose au regard d'ANSSI-FT-082

| Recommandation | `compose.yaml` (option B) | `deploy/compose.yaml` (option C) |
|---|---|---|
| R1 « Isoler les systèmes sensibles de fichiers de l'hôte » | Appliquée : pas de clé `privileged:`. Le seul montage est `./exports:/data:ro` | Appliquée : pas de clé `privileged:`. Aucun montage de `/`, `/dev`, `/proc`, `/sys` ni du socket Docker (tableau 8) |
| R2 « Restreindre l'accès aux périphériques de l'hôte » | Sans objet : pas de clé `devices:` | Sans objet : pas de clé `devices:`. `TS_USERSPACE: "true"` ne nécessite aucun périphérique TUN |
| R3 « Interdire la connexion du conteneur au réseau bridge docker0 » | À la charge de l'exploitant (service Docker). Le service rejoint le réseau de projet que Compose crée | À la charge de l'exploitant. Chaque service nomme ses réseaux, `network_mode: service:tailscale` ou `network_mode: none` |
| R4 « Isoler l'interface réseau de l'hôte » | Appliquée : pas de `network_mode: host` | Appliquée : pas de réseau d'hôte (figé par `tests/test_docker.py`) |
| R5 « Créer un réseau dédié pour chaque connexion » | Appliquée par le comportement par défaut de Compose : pas de clé `networks:`, un seul réseau de projet dessert donc l'unique service et son unique port publié | Partiellement appliquée : `egress` et `internal` sont dédiés, mais `caddy` partage l'espace de noms réseau de `tailscale`, ces deux-là ne sont donc pas séparés |
| R6 « Dédier des namespaces PID, IPC et UTS pour chaque conteneur » | Appliquée : pas de clé `pid:`, `ipc:` ni `uts:` | Appliquée : pas de clé `pid:`, `ipc:` ni `uts:` |
| R7 « Dédier un namespace USER ID pour chaque conteneur » | À la charge de l'exploitant (service Docker) | À la charge de l'exploitant. L'uid qui lit le dossier des exports change en cas de remappage |
| R7+ « Restreindre la création des Namespace USER ID à l'utilisateur root » | À la charge de l'exploitant (réglage du noyau) | À la charge de l'exploitant |
| R7- « Restreindre le partage du Namespace USER ID de l'hôte » | Sans objet : pas de clé `userns_mode:` | Sans objet : pas de clé `userns_mode:` |
| R8 « Interdire l'utilisation des capabilities » | Appliquée : `cap_drop: [ALL]` | Appliquée pour `tailscale`, `xerscope` et `lexicon-init` : `cap_drop: [ALL]`. Non appliquée pour `caddy` : voir R8- |
| R8- « Limiter l'utilisation des capabilities » | Sans objet | Utilisée par `caddy` : `cap_drop: [ALL]` et `cap_add: [NET_BIND_SERVICE]`. La raison donnée par le fichier : le binaire porte cette capability de fichier et le noyau refuse de l'exécuter avec un ensemble limite (bounding set) vide. Caddy écoute sur 8080. La liste des 19 capabilities « sensibles » du document ne contient pas `CAP_NET_BIND_SERVICE`. De cette capability, il dit que l'application « doit être configurée sur des ports non priviligiés », ce qui est le cas de Caddy (8080) |
| R9 « Dédier les Control groups pour chaque conteneur » | Appliquée : pas de clé `cgroup_parent:` | Appliquée : pas de clé `cgroup_parent:` |
| R10 « Limiter l'utilisation de la mémoire de l'hôte pour chaque conteneur » | Non appliquée : pas de `mem_limit` | Partiellement appliquée : `mem_limit` sur les quatre services (`256m`, `256m`, `${XERSCOPE_MEM_LIMIT:-2g}` deux fois). Pas de limite de swap (`memswap_limit`) |
| R11 « Limiter l'utilisation du CPU de l'hôte pour chaque conteneur » | Non appliquée : pas de limite de CPU | Non appliquée : pas de limite de CPU. La raison donnée par le fichier : Docker refuse de créer un conteneur avec un quota sur un noyau sans contrôle de bande passante CFS |
| R12 « Restreindre en lecture le système de fichiers racine de chaque conteneur » | Appliquée : `read_only: true` | Appliquée : `read_only: true` sur les quatre services |
| R12- « Limiter l'écriture de l'espace de stockage de chaque conteneur » | Sans objet : R12 est appliquée | Sans objet |
| R12- - « Limiter l'écriture de l'espace de stockage de l'ensemble des conteneurs » | Sans objet | Sans objet |
| R13 « Créer un système de stockage pour les données non persistantes » | Partiellement appliquée : tmpfs sur `/tmp` (`mode=1777`) et `/home/nonroot` (`mode=700`), appartenant à 65532, sans taille | Partiellement appliquée : sept tmpfs, chacun avec une taille. Un mode n'est défini que sur les deux de `xerscope` |
| R14 « Créer un système de stockage pour les données persistantes ou partagées » | Appliquée pour la partie en lecture seule : `./exports:/data:ro`. Aucun montage inscriptible | Partiellement appliquée : les montages en lecture seule portent `:ro`. Les montages inscriptibles (`tailscale-state`, `generated/`, `suggested/`) n'ont pas de limite de taille. L'application cesse d'enregistrer des suggestions à 256 Ko |
| R15 « Restreindre l'accès aux répertoires et aux fichiers sensibles » | Appliquée par la liste des montages. Permissions des fichiers : à la charge de l'exploitant | Appliquée par la liste des montages et par l'uid de `XERSCOPE_UID`. Permissions sur `deploy/.env`, les exports et le dossier du lexique : à la charge de l'exploitant |
| R16 « Exporter les journaux avec Docker » | À la charge de l'exploitant (service Docker). Pas de clé `logging:` | À la charge de l'exploitant. Pas de clé `logging:`, par un choix énoncé dans l'en-tête du fichier |
| R16- « Exporter les journaux depuis l'intérieur du conteneur » | Non appliquée : pas d'exportateur dans l'image | Non appliquée : aucun exportateur dans les conteneurs |

Les deux fichiers Compose définissent aussi `security_opt: ["no-new-privileges:true"]` sur chaque
service, et l'image de l'application s'exécute sous un utilisateur non root. ANSSI-FT-082 ne
mentionne ni ces deux points, ni les limites de processus, ni les contrôles de santé, et il laisse
les images hors de son périmètre. Le tableau ne les évalue donc pas.

Le durcissement de `compose.yaml` et de `deploy/compose.yaml` s'applique aux conteneurs démarrés par
Compose. Un simple `docker run` de l'image n'en bénéficie pas.

### Limites de ressources et stockage par service

Le tableau 19 liste les limites que porte chaque service.

**Tableau 19.** Limites de ressources et stockage par service

| Service | Mémoire | Processus | CPU | tmpfs | Redémarrage | Contrôle de santé |
|---|---|---|---|---|---|---|
| `xerscope` (option B) | Aucune | Aucune | Aucune | `/tmp`, `/home/nonroot`, sans taille | `unless-stopped` | Celui de l'image |
| `tailscale` | `mem_limit: 256m` | `pids_limit: 128` | Aucune | `/tmp:size=16m`, `/var/run/tailscale:size=1m` | `unless-stopped` | Aucun |
| `caddy` | `mem_limit: 256m` | `pids_limit: 128` | Aucune | `/tmp`, `/data`, `/config`, `size=16m` chacun | `unless-stopped` | Aucun |
| `xerscope` (option C) | `${XERSCOPE_MEM_LIMIT:-2g}` | `pids_limit: 256` | Aucune | `/tmp` (`mode=1777,size=256m`), `/home/nonroot` (`mode=700,size=16m`) | `unless-stopped` | Celui de l'image |
| `lexicon-init` | `${XERSCOPE_MEM_LIMIT:-2g}` | `pids_limit: 64` | Aucune | Aucun | `"no"` | Désactivé |

Le contrôle de santé de l'image est
`HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3`, une requête vers
`http://127.0.0.1:8501/_stcore/health` effectuée avec le Python de l'image. Le service `caddy`
attend que `tailscale` soit démarré, non qu'il soit en bonne santé (`depends_on: [tailscale]`).

L'en-tête de `deploy/compose.yaml` indique que, sur un noyau dépourvu des cgroups de mémoire et de
processus, Docker abandonne la limite avec un avertissement et que la pile démarre quand même. Ses
commentaires donnent un seul chiffre de dimensionnement, environ 1 Go de mémoire pour un export de
40 Mo une fois analysé. Les tests du projet ne mesurent pas ce chiffre. Le nombre de sessions
simultanées qui tiennent sous la limite n'est pas établi. Chaque session détient ses propres
fichiers analysés. L'application est un seul conteneur, sans réplica : un redémarrage vide la
mémoire des sessions, et les planificateurs relisent leurs fichiers.

### Ce qui relève de l'hôte et du service Docker

ANSSI-FT-082 laisse deux sujets hors de son périmètre : « le Docker daemon et la gestion des images
Docker sont hors périmètre de l'étude. » Il nomme aussi des risques résiduels qu'aucun fichier
Compose ne supprime. Le premier tient aux droits du démon lui-même : « les processus Docker
Community Edition (CE) s'exécutent avec les droits de l'utilisateur root (UID=0). » Le second tient
à l'hôte : « Un durcissement du système et des services Docker conformément au guide «
Recommandations de configuration d'un système GNU/Linux » [1] publié par l'ANSSI doit être
réalisé ». Le guide cité, ANSSI-BP-028, définit quatre niveaux (minimal, intermédiaire, renforcé,
élevé), et le choix du niveau vous revient.

Les réglages suivants relèvent de l'hôte : le réseau bridge par défaut (R3), le remappage de
l'espace de noms utilisateur (R7, R7+), le pilote de journalisation (R16) et les modules de
sécurité. Aucun des deux fichiers Compose ne définit d'option seccomp, AppArmor ou SELinux : les
valeurs par défaut du service Docker s'appliquent donc. Les fichiers n'indiquent aucune version
minimale de Docker ou de Compose. Le `Dockerfile` nécessite BuildKit.

## Origine et intégrité des images et des dépendances

Cette section indique d'où vient chaque artefact et ce qui peut être vérifié. ANSSI-FT-082 ne couvre
pas les images. La règle la plus proche parmi les documents cités est générale : « Seuls les dépôts
internes à l'organisation ou officiels (de la distribution ou de d'un éditeur) doivent être
utilisés. » (ANSSI-BP-028, R59).

### Registres et étiquettes

Le workflow [`image.yml`](../.github/workflows/image.yml) publie deux images,
`ghcr.io/xerscope/xerscope` et `ghcr.io/xerscope/xerscope-caddy`. Il ne s'exécute que comme dernière
tâche (`publish`) du workflow `tests`, lors d'une poussée sur `main` ou de la poussée d'une
étiquette git `v*`. Il ne s'exécute que lorsque huit tâches ont réussi : `lint`, `oracle-report`,
`test`, `fitness`, `audit`, `crosscheck`, `container` et `deploy`. Le tableau 20 liste les règles
d'étiquetage.

**Tableau 20.** Règles d'étiquetage des images publiées

| Étiquette | Règle | Remarques |
|---|---|---|
| `latest` | `type=raw,value=latest,enable={{is_default_branch}}` | Évolue avec `main`. Le fait que la poussée d'une étiquette la déplace aussi n'est pas établi |
| `X.Y.Z` | `type=semver,pattern={{version}}` sur une étiquette git `vX.Y.Z` | Aucune étiquette de ce type n'existe : aucune version publiée n'existe. Rien ne vérifie que l'étiquette se trouve sur `main` |
| `sha-<short>` | `type=sha` | Chaque construction |

Un paquet sur ghcr.io est privé lors de sa première publication, et l'analyse quotidienne du dépôt
lui-même s'authentifie pour récupérer les deux images. La visibilité des paquets est un réglage du
registre que les fichiers ne montrent pas. Une copie n'est envoyée sur Docker Hub que si le secret
`DOCKERHUB_TOKEN` et la variable `DOCKERHUB_IMAGE_OWNER` du workflow sont définis.

Dans `deploy/compose.yaml`, les références des images de l'application et de Caddy sont les
variables `XERSCOPE_IMAGE` et `XERSCOPE_CADDY_IMAGE` : une référence à un registre interne ne
demande donc aucune modification du fichier. La référence de Tailscale est une valeur littérale sur
la ligne `image:` du service `tailscale`. `deploy/.env.example` documente la forme épinglée
`tag@sha256:<digest>`. Pour les étapes, consultez [Importer les images dans un registre
interne](#importer-les-images-dans-un-registre-interne) de ce guide.

### Provenance, SBOM et attestation

L'étape de construction définit `provenance: mode=max` et `sbom: true`. Une seconde étape,
`actions/attest-build-provenance`, atteste le condensé poussé avec
`subject-name: ghcr.io/xerscope/<image>` et `push-to-registry: true`. Les images ne portent pas de
signature cosign : aucun workflow n'a d'étape cosign. Ce que liste le SBOM n'est pas établi.

Les commandes de vérification sont consignées dans le workflow et dans le guide de déploiement sur
Synology. Aucune tâche du projet ne les exécute. La première vérifie l'attestation. Les deux autres
affichent la provenance et le SBOM :

```bash
gh attestation verify oci://ghcr.io/xerscope/IMAGE_NAME@sha256:IMAGE_DIGEST --owner Xerscope
docker buildx imagetools inspect ghcr.io/xerscope/IMAGE_NAME@sha256:IMAGE_DIGEST --format '{{json .Provenance}}'
docker buildx imagetools inspect ghcr.io/xerscope/IMAGE_NAME@sha256:IMAGE_DIGEST --format '{{json .SBOM}}'
```

`IMAGE_NAME` vaut `xerscope` ou `xerscope-caddy`, et `IMAGE_DIGEST` est le condensé de l'image, soit
64 caractères hexadécimaux. Le fait que l'attestation se vérifie sur une copie de Docker Hub n'est
pas établi. L'image Tailscale n'a pas d'attestation de ce projet, et son étiquette peut être
déplacée.

### Sources auxquelles une construction fait appel

Le tableau 21 liste les sources amont d'une construction à partir des sources et la façon dont
chacune est épinglée.

**Tableau 21.** Sources amont d'une construction

| Source | Usage | Épinglage |
|---|---|---|
| `ghcr.io/astral-sh/uv:0.13.8-trixie-slim` | Étapes de construction de l'image de l'application | Étiquette et condensé |
| `gcr.io/distroless/cc-debian13:nonroot` | Étape d'exécution de l'image de l'application | Étiquette et condensé |
| Archive Debian | `OS_FIXES` (`zlib1g`) | `package=version`. Le commentaire du `Dockerfile` indique qu'apt vérifie la signature de l'archive. Un second commentaire indique que l'image de base distroless, à son condensé actuel, livre la même version corrigée, ce qui rend l'entrée redondante |
| Le CPython géré par uv | L'interpréteur | `PYTHON_VERSION=3.14` : la version mineure seulement |
| PyPI | Les dépendances Python | Versions exactes et empreintes sha256 dans `uv.lock`. Les deux appels à `uv sync` utilisent `--locked` |
| `caddy:2.11.9-builder`, `caddy:2.11.9` | Image Caddy | Étiquette et condensé |
| Modules Go | `caddy-ratelimit`, `golang.org/x/net` | Un commit et une version. La construction échoue sauf si le binaire enregistre les versions attendues et liste `http.handlers.rate_limit` |

Le niveau de correctif de CPython n'est pas épinglé : deux constructions du même commit peuvent donc
différer, et la reproductibilité des images n'est pas établie. L'image locale est construite par
`build: .` dans `compose.yaml`, qui n'offre aucun réglage pour utiliser à la place une image
publiée.

### Analyses et mises à jour en CI

Le tableau 22 liste les contrôles qui s'exécutent dans la chaîne d'intégration continue du
fournisseur. Ils ne couvrent pas votre déploiement.

**Tableau 22.** Contrôles dans la chaîne d'intégration continue du fournisseur

| Contrôle | Périmètre | Quand | Bloquant |
|---|---|---|---|
| Trivy (`.github/trivy/scan.sh`) | Image de l'application construite à partir du commit | Tâche `container` | Un constat HIGH ou CRITICAL qui dispose d'un correctif fait échouer la tâche et bloque la publication. Un constat sans correctif est seulement listé |
| Trivy | Image Caddy et image Tailscale | Tâche `deploy`, à chaque événement | Même règle. Deux exceptions datées pour l'image Tailscale : CVE-2026-78661 (`golang.org/x/net` v0.60.0), `expired_at: 2026-12-09`, et CVE-2026-124709 (OpenSSL, `libssl3` et `libcrypto3` 3.5.9-r0), `expired_at: 2026-12-17`. Avant l'analyse, la tâche vérifie que les trois binaires de Tailscale ne contiennent aucun code `golang.org/x/net/html` et ne chargent aucune bibliothèque partagée |
| Trivy | Les deux images `latest` publiées | [`scanner.yml`](../.github/workflows/scanner.yml), chaque jour à 04:41 UTC | Ne conditionne pas une publication |
| `pip-audit@2.10.1` (OSV et PyPI), `bandit@1.9.4 -r src -ll` | Dépendances verrouillées, sources | Tâche `audit`, à chaque exécution de `tests` | Bloque la publication |
| CodeQL, requêtes `security-and-quality` | Sources Python | Poussée et demande de fusion vers `main`, le lundi à 05:17 UTC | Workflow distinct |
| Dependabot | Python, Actions, Docker, Compose | Hebdomadaire (quotidien pour l'image Trivy), délai de carence de sept jours | Propose des mises à jour |

Chaque action des workflows est épinglée par SHA de commit. Le commit de `caddy-ratelimit` est mis
à jour à la main : Dependabot ne le lit pas. Rien, dans l'une ou l'autre pile, ne se met à jour tout
seul.

### Engagements du fournisseur

[`SECURITY.md`](../SECURITY.md) (en anglais) énonce trois choses. Les versions prises en charge sont
« the `main` branch and the latest published image » (la branche principale et la dernière image
publiée). Une vulnérabilité se signale par le signalement privé de vulnérabilités de GitHub, sur le
dépôt. L'auteur du signalement peut « Expect an acknowledgement within a week. » (attendre un accusé
de réception sous une semaine). Le fichier ne définit ni délai de correction, ni canal annonçant un
correctif, ni date de fin de support. Ces engagements ne sont pas fournis, et le dépôt ne contient
aucun document pouvant être annexé à un contrat en tant que plan d'assurance sécurité.

## Procédures

Chaque procédure nomme son option. Exécutez les commandes Docker depuis le dossier qui contient le
fichier Compose. Pour la signification d'une variable, consultez [Réglages lus par
l'application](#réglages-lus-par-lapplication) et [Réglages de l'option C](#réglages-de-loption-c)
de ce guide.

### Installer et démarrer l'option A

Pour exécuter l'application sur un poste de travail, vous avez besoin de uv et d'une copie de
l'arborescence des sources.

1. À la racine de l'arborescence des sources, installez les dépendances verrouillées :

   ```bash
   uv sync --locked
   ```

2. Démarrez l'application sur votre dossier des exports :

   ```bash
   uv run xerscope app --data EXPORTS_FOLDER
   ```

   Remplacez `EXPORTS_FOLDER` par le dossier qui contient les fichiers `.xer`. Le terminal affiche
   `You can now view your Streamlit app in your browser.` et `URL: http://localhost:8501`.
3. Ouvrez `http://localhost:8501` dans un navigateur sur le même poste de travail. La barre latérale
   affiche **Files · none read** (Fichiers · aucun lu) jusqu'à ce qu'un planificateur choisisse les
   fichiers.

### Installer et démarrer l'option B

Pour exécuter l'image locale, vous avez besoin de Docker avec Compose et BuildKit, ainsi que d'un
accès à Internet pour la construction.

1. À la racine de l'arborescence des sources, créez le dossier des exports :

   ```bash
   mkdir -p exports
   ```

2. Copiez vos fichiers `.xer` dans `exports/`. Les fichiers doivent être lisibles par l'uid 65532.
3. Construisez l'image et démarrez le conteneur :

   ```bash
   docker compose up -d --build
   ```

   Compose construit `xerscope:latest` et démarre le service `xerscope`.
4. Ouvrez `http://localhost:8501` dans un navigateur sur l'hôte.

### Installer et démarrer l'option C

Pour exécuter la pile distante, vous avez besoin de Docker avec Compose, d'un tailnet dont la
politique accorde Funnel à `tag:xerscope`, d'une clé d'authentification portant cette étiquette et
d'un accès aux trois images. La politique et la clé se créent dans la console d'administration de
Tailscale : le guide de déploiement sur Synology les décrit.

1. Dans le dossier `deploy`, créez le fichier de réglages :

   ```bash
   cp .env.example .env
   ```

2. Dans `.env`, renseignez `TS_AUTHKEY`, `XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH`, `XERSCOPE_PATH`
   et `XERSCOPE_EXPORTS`. Les commentaires de `.env.example` donnent la commande qui génère
   l'empreinte et celle qui génère le préfixe. Conservez les guillemets simples autour de
   l'empreinte.
3. Dans `.env`, définissez `XERSCOPE_LEXICON_DIR` sur un dossier existant qui contient `generated/`,
   `curated/` et `suggested/` et dans lequel le compte de l'application peut écrire. Les montages
   sont inconditionnels, et ce que Docker fait d'un dossier manquant n'est pas établi.
4. Vérifiez que les réglages sont complets :

   ```bash
   docker compose config --quiet
   ```

   Une valeur obligatoire manquante arrête la commande avec un message tel que
   `required variable XERSCOPE_USER is missing a value: login for the password prompt`.
5. Démarrez la pile :

   ```bash
   docker compose up -d
   ```

6. Lisez l'état de Funnel :

   ```bash
   docker compose exec tailscale tailscale funnel status
   ```

7. Ouvrez `https://xerscope.<tailnet>.ts.net/<XERSCOPE_PATH>/`, avec la barre oblique finale. Le
   navigateur demande l'identifiant et le mot de passe.

### Arrêter l'application ou modifier un réglage

Pour arrêter l'option B ou C, exécutez `docker compose down`. Dans l'option C, le volume
`tailscale-state` subsiste : le nœud conserve donc son identité. Pour arrêter l'option A, appuyez
sur `Ctrl+C` dans le terminal : Streamlit affiche `Stopping...`, puis Python affiche une trace
d'appels (traceback) qui se termine par `KeyboardInterrupt`.

Pour modifier un réglage ou un secret de l'option C, modifiez `deploy/.env`, puis exécutez de
nouveau `docker compose up -d`. Compose recrée les services dont la configuration a changé. Après un
changement de `XERSCOPE_PATH`, l'ancienne URL répond 404.

### Vérifier l'état de santé

Pour vérifier l'option A ou B, interrogez la route de santé depuis l'hôte :

```bash
curl -fsS http://127.0.0.1:8501/_stcore/health
```

La commande affiche `ok`. Dans l'option C, aucun port n'est publié : exécutez `docker compose ps` et
lisez l'état de santé du service `xerscope`. Les services `caddy` et `tailscale` n'ont pas de
contrôle de santé.

### Mettre à jour et revenir en arrière

Rien ne se met à jour tout seul. Pour mettre à jour l'option A, mettez à jour l'arborescence des
sources, exécutez `uv sync --locked` et redémarrez l'application. Pour mettre à jour l'option B,
mettez à jour l'arborescence des sources et exécutez de nouveau `docker compose up -d --build`. Pour
mettre à jour l'option C, suivez ces étapes dans le dossier `deploy`.

1. Copiez en lieu sûr les lignes `XERSCOPE_IMAGE` et `XERSCOPE_CADDY_IMAGE` de `.env`. Elles sont
   votre chemin de retour.
2. Dans `.env`, définissez les deux lignes sur la construction à exécuter, épinglée par condensé,
   sous la forme `ghcr.io/xerscope/xerscope:IMAGE_TAG@sha256:IMAGE_DIGEST`.
3. Si la mise à jour modifie `Caddyfile`, `compose.yaml` ou `tailscale-serve.json`, copiez les
   fichiers modifiés à la place des vôtres, et ajoutez à `.env` toute variable apparue dans
   `.env.example`.
4. Récupérez les images :

   ```bash
   docker compose pull
   ```

5. Recréez les conteneurs :

   ```bash
   docker compose up -d
   ```

   L'état du nœud reste dans son volume et l'URL ne change pas.

Pour revenir en arrière, rétablissez les deux lignes de l'étape 1 et exécutez de nouveau
`docker compose up -d`. Pour changer la version de Tailscale, modifiez la ligne `image:` du service
`tailscale`.

### Importer les images dans un registre interne

Si votre hôte ne doit pas récupérer d'images depuis des registres publics, copiez les images depuis
une machine qui le peut. Il s'agit de commandes Docker standard.

1. Sur la machine qui dispose de l'accès, copiez l'image de l'application vers votre registre :

   ```bash
   docker pull ghcr.io/xerscope/xerscope@sha256:IMAGE_DIGEST
   docker tag ghcr.io/xerscope/xerscope@sha256:IMAGE_DIGEST REGISTRY_HOST/xerscope/xerscope:IMAGE_TAG
   docker push REGISTRY_HOST/xerscope/xerscope:IMAGE_TAG
   ```

   Remplacez les éléments suivants :

   - `IMAGE_DIGEST` : le condensé de l'image que vous avez vérifiée
   - `REGISTRY_HOST` : le nom d'hôte de votre registre
   - `IMAGE_TAG` : l'étiquette que vous donnez à la copie

2. Répétez l'étape 1 pour `ghcr.io/xerscope/xerscope-caddy` et pour `tailscale/tailscale:v1.104.7`,
   qui est référencée par étiquette.
3. Dans `deploy/.env`, définissez `XERSCOPE_IMAGE` et `XERSCOPE_CADDY_IMAGE` sur les références dans
   votre registre.
4. Dans `deploy/compose.yaml`, remplacez la valeur `image:` du service `tailscale` par la référence
   dans votre registre.

Si l'hôte n'atteint aucun registre, écrivez chaque image dans un fichier avec `docker save`,
transportez le fichier et chargez-le avec `docker load`.

### Sauvegarder et restaurer

L'application ne stocke aucun planning : pour les options A et B, sauvegardez votre dossier des
exports. Pour l'option C, suivez ces étapes.

1. Copiez `deploy/.env` dans un emplacement qui protège les secrets.
2. Copiez `Caddyfile`, `compose.yaml` et `tailscale-serve.json` si vous les avez modifiés.
3. Copiez le dossier du lexique, et sauvegardez le dossier des exports avec vos propres outils.

Pour restaurer, remettez les fichiers et les dossiers là où `.env` pointe, puis démarrez la pile. Si
le volume `tailscale-state` est perdu, la pile démarre comme un autre nœud : définissez d'abord
`TS_AUTHKEY` sur une nouvelle clé.

### Supprimer l'application

Pour supprimer l'option C et ses données, suivez ces étapes dans le dossier `deploy`.

1. Arrêtez la pile et supprimez son volume :

   ```bash
   docker compose down --volumes
   ```

   Docker supprime les conteneurs, les deux réseaux et le volume `tailscale-state`.
2. Supprimez `deploy/.env`, qui contient les secrets.
3. Supprimez le dossier du lexique. Ses fichiers contiennent des mots tirés des exports et les
   corrections sur lesquelles les visiteurs ont cliqué.
4. Supprimez les trois images de l'hôte avec `docker image rm`.
5. Dans la console d'administration de Tailscale, supprimez le nœud et révoquez la clé.
6. Supprimez ou archivez le dossier des exports selon vos propres règles.

Pour supprimer l'option B, exécutez `docker compose down`, supprimez l'image `xerscope:latest` et
traitez le dossier `exports`. Pour supprimer l'option A, supprimez l'arborescence des sources avec
son dossier `.venv`.

## Journalisation

Cette section indique ce que chaque composant écrit. Aucun fichier livré ne fixe de durée de
conservation.

### Ce que chaque composant écrit

Le tableau 23 liste les sorties de journal par composant. Chaque conteneur écrit sur sa sortie
standard, et le service Docker conserve les lignes avec son pilote par défaut.

**Tableau 23.** Sorties de journal par composant

| Composant | Lignes | Champs et filtres |
|---|---|---|
| Application (code propre à xerscope) | Aucune | Le code de l'application ne contient aucun appel de journalisation |
| Application (Streamlit) | Bannière de démarrage (`You can now view your Streamlit app in your browser.` et les lignes d'URL), avertissements, traces d'appels des erreurs non interceptées | Le fait qu'une trace d'appels cite un nom de fichier ou une valeur n'est pas établi. Dans l'option C, les traces d'appels vont dans le journal et non sur la page |
| Caddy, journal d'accès | Une ligne par requête, `output stdout`, `format filter` enveloppant `console` | Le chemin, le statut et l'adresse IP du visiteur sont conservés. Le préfixe est remplacé par `<prefix>` dans l'URI de la requête, le `Referer` et le `Location` de redirection. `Sec-Websocket-Protocol` (jeton XSRF et identifiant de session de Streamlit) et `Content-Disposition` (nom de fichier d'un téléchargement) sont supprimés |
| Caddy, journaliseur par défaut | Erreurs du mandataire, JSON | Le préfixe est remplacé dans l'URI de la requête et le `Referer`. `Sec-Websocket-Protocol` est supprimé |
| tailscaled | Ses propres lignes | `TS_NO_LOGS_NO_SUPPORT: "true"` est défini pour qu'aucun journal de diagnostic ne soit envoyé à Tailscale. Contenu non établi |
| `lexicon-init` | Des décomptes, des noms de colonnes sources et le chemin du dossier dans un message d'erreur | Aucun nom d'export et aucun mot. `generated/report.txt` nomme les fichiers qu'il a ignorés |
| Suggestions du champ **Ask the schedule** | Aucune | Rien de ce qui concerne une suggestion n'est affiché ni journalisé |

La tâche de CI `deploy` échoue lorsque le préfixe secret atteint le journal de Caddy. Le `Caddyfile`
n'a pas de filtre pour les en-têtes de requête `Authorization` et `Cookie`. Ce que Caddy écrit pour
eux relève de son comportement par défaut : non établi.

### Ce qui n'est ni journalisé ni configuré

Aucun composant n'enregistre qui a fait quoi. L'application n'écrit aucun événement pour un fichier
lu, une page ouverte ou un téléchargement. Le journal d'accès de Caddy montre le statut de chaque
requête, 401 compris, et ne peut pas distinguer deux lecteurs, car l'identifiant est partagé. Les
options A et B n'ont aucun journal d'accès.

Ni le `Dockerfile` ni les fichiers Compose ne définissent `TZ` ou des paramètres régionaux. Les
horodatages qu'écrit le code propre à xerscope sont en UTC. La source de temps des horodatages n'est
pas fournie : aucun fichier livré ne configure une horloge ni sa synchronisation, ce qui est à la
charge de l'exploitant. Aucun des deux fichiers Compose n'a de clé `logging:` : la taille et la
rotation des journaux sont donc celles par défaut du service Docker. L'export vers une autre machine
et la durée de conservation sont à la charge de l'exploitant.

## Écarts connus et risques résiduels

Les sections précédentes énoncent chaque limite là où elle s'applique. Le tableau 24 les rassemble,
car un dossier d'homologation a besoin des risques résiduels en un seul endroit. La dernière colonne
est un élément d'entrée pour votre plan d'action, non un engagement du fournisseur.

**Tableau 24.** Écarts connus et risques résiduels

| Écart | Conséquence | Ce que l'exploitant peut faire |
|---|---|---|
| L'option D n'est pas livrée et n'est pas testée : les tests du projet figent l'agencement Funnel et ne couvrent pas un fichier adapté | Un déploiement interne derrière votre mandataire est votre propre intégration | Construisez-la à partir des éléments réutilisables et testez-la |
| Pas de gestion des utilisateurs : un identifiant partagé dans l'option C, aucun dans A et B | Aucun lecteur n'est distingué. Aucun ne peut être révoqué seul | Authentifiez devant l'application avec votre fournisseur d'identité |
| Pas d'expiration de session, pas de déconnexion, pas de blocage après échecs, pas d'authentification multifacteur. L'effet d'un changement de mot de passe sur les sessions ouvertes n'est pas établi | Une session dure aussi longtemps que le navigateur la conserve | Imposez-les dans votre propre mandataire |
| Pas de piste d'audit. L'application ne journalise rien | Aucune trace de qui a lu ou téléchargé quoi | Journalisez au niveau de votre mandataire. Exportez les journaux des conteneurs |
| Aucun test du projet n'exerce Funnel, la politique du tailnet ou le certificat | Le point d'entrée de l'option C n'est éprouvé que sur votre tailnet | Testez l'URL publiée après chaque modification de la pile |
| L'option C est un point d'entrée sur Internet relayé par un tiers | L'URL est joignable depuis n'importe quel réseau, et le relais échappe à votre maîtrise | Cotez l'exposition dans votre analyse de risque. Comparez avec un point d'entrée interne |
| Les hôtes et les ports sortants du conteneur `tailscale` ne sont pas établis. Aucune variable de serveur mandataire n'est définie | La matrice de flux de l'option C ne peut pas être close à partir des fichiers | Obtenez-les dans la documentation de Tailscale et testez |
| Les versions et les suites TLS de l'option C sont celles de Tailscale : non établi. Pas de TLS entre tailscaled, Caddy et l'application | La protection en transit à l'intérieur de l'hôte repose sur les réseaux de conteneurs | Terminez TLS sur un équipement que vous maîtrisez |
| `caddy` partage l'espace de noms réseau de `tailscale` | Ces deux conteneurs ne sont pas séparés au niveau réseau | Acceptez-le, ou reprenez la conception dans l'option D |
| L'image Tailscale est épinglée par étiquette. `tailscale` et `caddy` s'exécutent sous l'utilisateur par défaut de leur image | Une étiquette déplacée change l'image. Root dans deux conteneurs, avec aucune capability ou une seule | Épinglez un condensé dans votre copie. Appuyez-vous sur le durcissement de l'hôte |
| Deux constats acceptés dans l'image Tailscale : CVE-2026-78661, exception expirant le 2026-12-09, et CVE-2026-124709, exception expirant le 2026-12-17 | Deux vulnérabilités connues subsistent jusqu'à ce qu'une version de Tailscale porte leurs correctifs | Suivez le fichier d'exceptions `deploy/tailscale.trivyignore.yaml` |
| Les constats sans correctif sont listés, non bloquants | Une image peut être publiée avec des constats connus non corrigés | Analysez vous-même les images avant usage |
| Aucune version publiée n'existe. `latest` évolue avec `main`. Visibilité des paquets non établie | Aucune version stable à nommer dans un contrat ou un dossier | Épinglez par condensé. Demandez au fournisseur une version publiée et étiquetée |
| Pas de signature d'image. Aucune tâche du projet n'exécute les commandes de vérification. Contenu du SBOM non établi | L'intégrité repose sur les condensés et sur l'attestation | Exécutez les commandes de vérification. Consignez les résultats |
| Une seule architecture, et aucune tâche du projet ne construit pour une autre. Reproductibilité non établie. Niveau de correctif de CPython non épinglé | Une reconstruction peut différer de l'image publiée | Construisez à partir des sources dans votre propre chaîne si vous l'exigez |
| Pas de limite de CPU ni de limite de swap. Aucune limite dans l'option B | Un conteneur peut utiliser le CPU de l'hôte. L'option B peut utiliser sa mémoire | Ajoutez des limites dans votre copie du fichier Compose |
| Aucun test du projet ne mesure les chiffres de dimensionnement. Capacité par session non établie | La valeur par défaut `2g` peut être trop petite ou trop grande | Mesurez avec vos propres exports |
| L'option B n'est pas verrouillée. `/_stcore/metrics` répond sur une instance directe | Quiconque se trouve sur l'interface de bouclage de l'hôte lit tout | Réservez-la à un usage par une seule personne |
| **Anonymous exports** n'est pas imposé | Un visiteur peut télécharger des tables non anonymisées | Traitez les téléchargements comme aussi sensibles que les exports |
| Un téléversement de plus de 1 Mo passe par un fichier temporaire (gestionnaire de téléversement de Streamlit, d'après son code source) | Dans l'option A, le fichier transite par le répertoire temporaire du système | Préférez le dossier au téléversement |
| Streamlit interroge `checkip.amazonaws.com` à chaque démarrage du conteneur, et lors d'une négociation WebSocket depuis une origine étrangère | Une tentative sortante à chaque démarrage dans les options B et D, et lors d'une telle négociation dans l'option A | Bloquez-la. L'application fonctionne sans elle |
| Les requêtes côté navigateur du JavaScript de Streamlit ne sont pas établies | Une requête externe depuis la page ne peut pas être exclue à partir des fichiers | Observez la page dans un navigateur derrière votre mandataire |
| Le traitement de `Authorization` et de `Cookie` par Caddy dans son journal n'est pas établi. Les traces d'appels peuvent citer des valeurs | Les journaux peuvent contenir davantage que ce que montrent les fichiers | Lisez un échantillon des journaux avant de les exporter |
| Pas de clé `logging:`, pas d'exportateur, pas de `TZ`, aucune source de temps configurée | Les journaux restent sur l'hôte avec les valeurs par défaut du service, datés par l'horloge de l'hôte | Configurez le pilote de journalisation du service Docker et la synchronisation de l'horloge de l'hôte |
| Aucun test du projet ne s'exécute avec `--userns-remap`. Aucune version minimale de Docker ou de Compose n'est indiquée | Le durcissement de l'hôte peut casser la pile | Testez sur votre hôte durci |
| Aucun test du projet n'exécute de bout en bout les procédures Docker de ce guide, ne démarre `lexicon-init` dans son conteneur ni ne démarre la pile sans le dossier `XERSCOPE_LEXICON_DIR` | Une étape peut se comporter différemment sur votre moteur | Faites un essai à blanc de chaque procédure sur un hôte de test |
| Le contenu de l'image de l'application (ni shell, ni gestionnaire de paquets, uid 65532) est énoncé d'après le `Dockerfile` | Ces propriétés reposent sur l'image de base | Inspectez l'image que vous récupérez ou construisez |
| Aucun test du projet ne restaure la pile. Emplacement de la clé TLS non établi | Une pile restaurée peut être un nouveau nœud | Faites un essai à blanc de restauration |
| Les conteneurs partagent le noyau de l'hôte. Aucun des deux fichiers Compose ne définit d'option seccomp, AppArmor ou SELinux, et le remappage de l'espace de noms utilisateur est à la charge de l'exploitant | L'isolation entre un conteneur et l'hôte repose sur le noyau et sur les valeurs par défaut du service Docker | Durcissez l'hôte et tenez son noyau à jour des correctifs |
| L'état de maintenance des composants tiers n'est pas fourni | Un composant peut atteindre sa fin de support sans avis du fournisseur | Suivez la politique de support de chaque éditeur |
| Politique de mots de passe non imposée. Le coût documenté de l'empreinte est 10 | La robustesse de l'identifiant repose sur le mot de passe que vous choisissez | Générez un mot de passe long |
| Engagements du fournisseur limités à `SECURITY.md`. La licence n'accorde rien | Pas de délai de correction, pas de notification, pas de date de fin de support | Fixez-les dans un contrat |

## Références

Le tableau 25 donne chaque document cité dans ce guide avec sa référence, sa version et sa date
telles qu'imprimées, ainsi que son adresse sur le site de l'éditeur au 26 novembre 2026.

**Tableau 25.** Documents cités

| Document | Référence | Version, date | Adresse |
|---|---|---|---|
| « Recommandations de sécurité relatives aux déploiements de conteneur Docker » | ANSSI-FT-082 | Version 1.0, 23/09/2020 | <https://messervices.cyber.gouv.fr/documents-guides/docker_fiche_technique.pdf> |
| « Guide d'hygiène informatique – Renforcer la sécurité de son système d'information en 42 mesures » | Aucune imprimée | Version 2.0 - Septembre 2017 | <https://messervices.cyber.gouv.fr/documents-guides/guide_hygiene_informatique_anssi.pdf> |
| « Recommandations relatives à l'authentification multifacteur et aux mots de passe » | ANSSI-PG-078 | Version 2.0, 08/10/2021 | <https://messervices.cyber.gouv.fr/documents-guides/anssi-guide-authentification_multifacteur_et_mots_de_passe.pdf> |
| « Recommandations de configuration d'un système GNU/Linux » | ANSSI-BP-028 | Version 2.0, 03/10/2022 | <https://messervices.cyber.gouv.fr/documents-guides/fr_np_linux_configuration-v2.0.pdf> |
| « Le guide de l'homologation de sécurité des systèmes d'information » (ANSSI, avec la DINUM) | Aucune imprimée | Version 2.2 – Mars 2026 | <https://messervices.cyber.gouv.fr/documents-guides/guide-homologation-securite-web-04-2025.pdf> |
| « Recommandations pour les architectures des systèmes d'information sensibles ou Diffusion Restreinte » | ANSSI-PG-075 | Version 1.2, 24/09/2021 | <https://messervices.cyber.gouv.fr/documents-guides/anssi-guide-recommandations_architectures_systemes_information_sensibles_ou_diffusion_restreinte-v1.2.pdf> |
| « Recommandations pour l'hébergement dans le cloud des systèmes d'information sensibles » | Aucune imprimée | Version 1.0 – Juillet 2024 | <https://messervices.cyber.gouv.fr/documents-guides/20240814_np_anssi_recommandations_hebergement_cloud_si_a5_v1g_fr.pdf> |
| « Prestataires de services d'informatique en nuage (SecNumCloud) – référentiel d'exigences » | Aucune imprimée | Version 3.2 du 8 mars 2022 | <https://cyber.gouv.fr/sites/default/files/document/secnumcloud-referentiel-exigences-v3.2.pdf> |
| « Recommandations relatives à l'interconnexion d'un système d'information à Internet » | ANSSI-PA-066 | Version 3.0, 19/06/2020 | <https://messervices.cyber.gouv.fr/documents-guides/anssi-guide-passerelle_internet_securisee-v3.pdf> |
| « Recommandations sur le nomadisme numérique » | ANSSI-PA-054 | Version 2.0, 13/11/2023 | <https://messervices.cyber.gouv.fr/documents-guides/guide_nomadisme_anssi_pa_054_v2.pdf> |
| « Les Essentiels – Architecture sécurisée de SI » | Aucune imprimée | V1.0 (08/25) | <https://messervices.cyber.gouv.fr/documents-guides/anssi_essentiels_architecture_securisee_v1.0.pdf> |
| « NIS 2 – Transposition nationale – Mesures de gestion des risques en matière de cybersécurité – ReCyF : Référentiel Cyber France (ReCyF) » | Aucune imprimée | Version 2.5 du 17/03/2026, document de travail | <https://messervices.cyber.gouv.fr/documents-ressources/20260317_NIS_V2_ReCyF_v2.5.pdf> |
| Page de l'ANSSI « Directive NIS 2 » | Aucune | Aucune date imprimée. Page au 26 novembre 2026 | <https://messervices.cyber.gouv.fr/nis2> |
| « Instruction générale interministérielle sur la protection du secret de la défense nationale » (SGDSN, IGI 1300) | Aucune imprimée sur la couverture | Fichier `igi-1300-20210809.pdf` | <https://www.sgdsn.gouv.fr/files/files/Nos_missions/igi-1300-20210809.pdf> |
| « La sécurité des activités d'importance vitale – Objectifs et enjeux » (SGDSN) | Aucune | Aucune date imprimée. PDF créé le 14/03/2016 | <https://www.sgdsn.gouv.fr/files/files/Nos_missions/plaquette-saiv.pdf> |
| « Guide de la sécurité des données personnelles » (CNIL) | Aucune | Fiches datées du 14 mars 2024 | <https://www.cnil.fr/fr/guide-de-la-securite-des-donnees-personnelles> ; la phrase sur l'article 32 figure sur <https://www.cnil.fr/fr/securite-avant-propos> |
| CNIL, « Donnée personnelle » et « Le registre des activités de traitement » | Aucune | Page sur le registre datée du 13 avril 2018 | <https://www.cnil.fr/fr/definition/donnee-personnelle>, <https://www.cnil.fr/fr/RGPD-le-registre-des-activites-de-traitement> |

### Documents cités à travers un autre document

Ce guide ne nomme les documents suivants qu'à travers un document du tableau 25 qui les cite, et il
ne rapporte rien de leur propre texte :

- l'II 901 (Instruction interministérielle n° 901/SGDSN/ANSSI du 28 janvier 2015) ;
- le Décret n° 2022-513 du 8 avril 2022 ;
- la Loi de programmation militaire et le code de la défense ;
- la loi de transposition de NIS 2 et ses décrets ;
- les documents du RGS v2.0 ;
- tout texte publié sur `legifrance.gouv.fr`.

Aucun document du tableau 25 ne définit le contenu d'un « dossier d'exploitation » ou d'un « dossier
d'installation », et aucun ne traite des images de conteneur, des registres ou des signatures
d'image.
