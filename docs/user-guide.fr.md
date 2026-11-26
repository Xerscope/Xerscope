# Guide utilisateur de xerscope

English: [User guide](user-guide.md)

xerscope lit les exports hebdomadaires de Primavera P6 (`.xer`) et en tire des rapports, depuis une
ligne de commande et depuis une application web qui s'exécute sur votre propre machine. Ce guide
comprend huit parties :

- [À propos de ce guide](#à-propos-de-ce-guide)
- [Concepts](#concepts)
- [Premiers pas](#premiers-pas)
- [Guides pratiques](#guides-pratiques)
- [Référence](#référence)
- [Dépannage](#dépannage)
- [Limites](#limites)
- [Glossaire et documents associés](#glossaire-et-documents-associés)

## À propos de ce guide

Ce guide s'adresse à un ingénieur planification qui connaît bien Primavera P6 et sait coller une
commande dans un terminal. Vous n'avez pas besoin de connaître Python. Le guide couvre xerscope sur
votre propre machine : son installation, la ligne de commande, l'application web et l'image Docker
locale. Il ne couvre pas l'hébergement de l'application pour une équipe. Pour cela, consultez
[docs/it-deployment-guide.fr.md](it-deployment-guide.fr.md) et [docs/deploy.md](deploy.md) (en
anglais).

Le guide décrit les versions suivantes :

- xerscope 0.1.0. La ligne de commande n'a pas d'option `--version` et l'application n'affiche
  aucune version.
- Python 3.11 ou version ultérieure. Les tests automatisés s'exécutent sur 3.11, 3.13 et 3.14.
- Le standard P6 Check Schedule (vérification du planning) suit la documentation de P6 Professional
  24.
- Le recalcul applique les règles de P6 Professional 23.12 / 24. Il est vérifié par rapport à des
  plannings calculés par P6 Professional 23.12.1. Certains contrôles sont vérifiés par rapport à des
  rapports de P6 Professional 26.8.
- xerscope lit les exports `.xer` comme des mises à jour, et un export P6 XML uniquement pour ses
  Baselines (plannings de référence).
- L'application et la ligne de commande sont en anglais. Le champ **Ask the schedule** (Interroger
  le planning) lit aussi le français.

Le guide applique les conventions suivantes :

- « Vous » désigne le lecteur. Vous saisissez chaque commande dans un terminal ouvert dans le
  dossier qui contient le code source de xerscope. Chaque commande xerscope commence par
  `uv run xerscope`, sauf dans l'image Docker.
- Un libellé de l'application est en gras, écrit comme l'application l'affiche, par exemple **Done**
  (Terminé). Les commandes, les noms de fichiers, les valeurs et les messages que l'outil affiche
  sont en police de code.
- Un mot en majuscules dans une commande ou un libellé, comme `ACTIVITIES_CSV` ou NAME, est un
  espace réservé. Dans un libellé, N, K et M représentent des nombres.
- Une partie entre chevrons dans un message ou un nom de fichier, comme `<file>` ou `<n>`,
  représente un nom ou un nombre.
- Le guide emploie les termes de P6 : *Data Date* (date des données), *activité* (*activity*) et
  *Activity ID* (identifiant d'activité). Les libellés de l'application disent *status date*, *task*
  et *Task ID* pour les mêmes notions.
- L'application écrit *labor* et *anonymized*. Le guide cite les libellés tels quels et écrit
  ailleurs « main-d'œuvre » et « anonymisé ».
- Les dates et les heures sont écrites comme l'outil les affiche : `2026-10-19` ou `19 Oct 2026`, ou
  `20/12/2026` dans le bandeau du champ **Ask the schedule**, et l'heure au format 24 heures
  (`08:00`).
- Tous les exemples utilisent la série de démonstration, un projet synthétique nommé `PRJ-ALPHA`.

Pour approfondir, le guide renvoie à [docs/formulas.md](formulas.md) (en anglais),
[docs/standards.md](standards.md) (en anglais), [docs/cpm.md](cpm.md) (en anglais) et
[docs/backlog.md](backlog.md) (en anglais). La liste complète figure dans
[Documents associés](#documents-associés) de ce guide.

## Concepts

Cette partie explique les notions qui sous-tendent les chiffres. Elle ne contient aucune procédure.

### Mises à jour, série hebdomadaire et snapshots

Une *mise à jour* est un export `.xer` d'un planning à une Data Date. xerscope lit ensemble
plusieurs mises à jour d'un même projet, sous forme de *série*, parce que la plupart de ses lectures
sont des comparaisons. Elles montrent ce qui a changé entre deux semaines, ce qui a été promis la
semaine précédente et réalisé cette semaine, et comment la fin prévisionnelle s'est déplacée. Une
mise à jour seule donne tout de même les contrôles, le recalcul et le Gantt.

Une série est ordonnée par Data Date, puis par nom de fichier. Elle contient une mise à jour par
Data Date : deux fichiers de même Data Date ne peuvent pas être lus tous les deux, car rien
n'indique lequel est le planning de la semaine. Dans un dossier, les mises à jour sont les fichiers
situés directement dans ce dossier et dont le nom se termine par `.xer`, quelle que soit la casse.
Les sous-dossiers ne sont pas lus. *Snapshot* est le mot de l'application pour une mise à jour une
fois lue. Quand un fichier contient plusieurs projets, xerscope en lit un : les copies de Baseline
sont écartées, puis le projet qui compte le plus d'activités l'emporte, puis la Data Date la plus
récente, puis le premier projet du fichier. Vous pouvez choisir un autre projet dans l'application
et sur la ligne de commande.

### Ce que xerscope lit dans une mise à jour

Quelques lectures diffèrent de ce que suggère un coup d'œil rapide aux tables XER :

- La Data Date est `PROJECT.last_recalc_date`, sinon `PROJECT.plan_start_date`. Quand les deux sont
  vides, la mise à jour n'a pas de Data Date : l'application ignore le fichier et, sur la ligne de
  commande, les contrôles qui ont besoin d'une Data Date affichent `n/a`. Les libellés de
  l'application l'appellent *status date*, et la « status date » de DECM est lue comme la Data Date
  de P6.
- La fin prévisionnelle du projet est la fin d'activité la plus tardive, hors lignes de synthèse
  WBS. `PROJECT.scd_end_date` n'est pas utilisé. Quand les deux diffèrent de plus d'un jour,
  xerscope émet un avertissement.
- Start (début) et Finish (fin) suivent les colonnes de même nom de P6 : la date réelle, sinon la
  date au plus tôt restante, sinon la date au plus tôt, sinon la date planifiée.
- Les heures de main-d'œuvre budgétées, réelles et restantes viennent de `TASK`. Une valeur vide est
  remplacée, par activité et par colonne, par celle des affectations de main-d'œuvre, de rôle ou
  sans type de l'activité dans `TASKRSRC`. Les unités Nonlabor (hors main-d'œuvre) sont tenues à
  part, et les affectations de matériaux n'entrent dans aucun des deux totaux.
- xerscope applique les réglages propres au projet : la définition du critique, le calendrier des
  Lags (décalages entre activités liées), l'option de calcul des activités commencées, l'option du
  Lag SS, le type de Float (marge), les dates Expected Finish (fin attendue) et le type de
  pourcentage d'avancement (physique, durée ou unités). Il lit aussi « Make open-ended activities
  critical » (rendre critiques les activités à extrémité ouverte), l'option des relations vers
  d'autres projets, et Must Finish By (date de fin imposée au projet).

Pour les champs exacts et les valeurs de repli, consultez [docs/formulas.md](formulas.md) (en
anglais).

### Baselines et types proposés par l'application

Une Baseline est le plan par rapport auquel sont mesurés la valeur planifiée, le Baseline Execution
Index (BEI, indice d'exécution de la Baseline), les activités manquées et les activités en retard.
xerscope ne la devine pas : vous la choisissez, et chaque résultat indique la Baseline utilisée. Le
choix comporte cinq types :

- **Baseline in each file (P6 Project Baseline)** (Baseline de chaque fichier) : chaque mise à jour
  est mesurée par rapport au projet que son propre fichier désigne comme sa Project Baseline
  (Baseline de projet), dans `PROJECT.sum_base_proj_id`. Cette Baseline est utilisable à trois
  conditions. C'est un autre projet du même fichier. Elle possède des activités. Quand elle
  enregistre le projet dont elle a été copiée, ce projet est le projet analysé. Si vous disposez
  d'un export P6 XML des Baselines, la Baseline que nomme une mise à jour est lue dans l'export.
- **Separate baseline file** (Fichier de Baseline séparé) : un seul fichier, XER ou export P6 XML,
  pour toute la série.
- Une mise à jour chargée, par exemple le premier export, pris avant tout avancement.
- **Planned dates in each file (target_*)** (Dates planifiées de chaque fichier) : chaque mise à
  jour par rapport à ses propres dates planifiées.
- **None** (Aucune).

Le premier type suit une Baseline qui change dans le temps, mise à jour après mise à jour. Les
autres figent un seul plan. Cela compte quand vous comparez des semaines : des mises à jour mesurées
par rapport à des plans différents ne montrent pas une tendance unique, et la barre latérale le
signale quand cela se produit. xerscope enregistre la façon dont la Baseline de chaque mise à jour a
été trouvée, par l'un de ces huit mots : *in file*, *exact*, *probable*, *chosen*, *fallback*,
*planned*, *series* ou *none*. *Exact* désigne la Baseline que nomme la mise à jour, lue dans
l'export P6 XML, et *series* une seule Baseline pour toutes les mises à jour. Selon la définition du
code lui-même, seuls *in file* et *exact* correspondent à la Baseline que P6 a lui-même utilisée.

Deux groupes de pages lisent la Baseline différemment. **Schedule health** (Santé du planning),
**Audit** et **Gantt & WBS** lisent la Project Baseline du fichier de la mise à jour chaque fois que
ce fichier en contient une utilisable, quel que soit votre choix, comme le fait un contrôle P6 sur
ce fichier. **Earned value** (Valeur acquise) mesure ses chiffres cumulés par rapport à l'origine de
la série, c'est-à-dire la Baseline qui ne bouge pas d'une mise à jour à la suivante, sauf si vous
activez sa vue P6.

La *base de valeur acquise* est un second choix : elle désigne les heures et les dates de Baseline
qu'utilisent la valeur planifiée et la valeur acquise. Par défaut, ce sont les valeurs budgétées
avec les dates planifiées. Le texte d'aide de cet élément nomme son équivalent dans P6 : l'Admin
Preference (préférence d'administration) « When calculating earned value from a baseline use ».

La base fixe aussi les dates d'une Baseline séparée, que le texte d'aide appelle BL Project Start /
Finish de P6. Une Baseline séparée est un planning à part entière : un fichier de Baseline, une mise
à jour chargée, ou la Project Baseline qu'un fichier contient ou nomme. Avec la base par défaut, ses
dates sont les dates planifiées des activités de la Baseline. Avec les deux options « current
dates », ce sont les dates Start et Finish actuelles de ces activités. Les activités en retard, le
BEI, les écarts de fin, le Gantt et la tendance des jalons lisent ces dates. Leurs résultats peuvent
donc changer avec la base pour une activité qui avait commencé quand la Baseline a été prise, ou
dont la Baseline a été modifiée sans être recalculée. Un résultat qui lit une Baseline est recalculé
quand la base change. Avec **Planned dates in each file (target_*)**, les dates de Baseline sont les
dates planifiées de la mise à jour elle-même, quelle que soit la base. Pour les sources de la règle,
consultez
[docs/standards.md](standards.md#p6-check-schedule-p6-professional-24-17-checks-18-report-lines) (en
anglais).

### Rapprochement des activités entre fichiers

Les activités sont rapprochées entre fichiers par Activity ID (`TASK.task_code`). `task_id` ne sert
pas au rapprochement : le code le traite comme un numéro qui peut changer d'un export au suivant. La
série de démonstration le change dans chaque fichier alors que les Activity ID restent. Quand un
Activity ID est répété dans un projet, la première ligne `TASK` est conservée et un avertissement
nomme les autres, qui sont écartées avec leurs relations, leurs affectations et leurs dépenses.

Une activité renumérotée entre deux fichiers compte donc pour une activité supprimée et une activité
nouvelle. Le journal des modifications et les chiffres de Percent Plan Complete (PPC, pourcentage du
plan réalisé) le signalent. Pour une Baseline, vous pouvez changer ce comportement avec
**Link renumbered tasks by GUID** (Lier par GUID les tâches renumérotées). Quand cette case est
cochée, une activité de la mise à jour qui porte le `TASK.guid` d'une activité de la Baseline sous
un nouvel Activity ID est mesurée par rapport à cette activité de la Baseline. La case est décochée
par défaut. Elle est sans effet avec une Baseline lue dans un export P6 XML, où le GUID est vide.

### Standards et contrôles

Un *standard* est une liste de contrôles. Quatre sont intégrés : P6 Check Schedule, DCMA 14-Point,
DCMA DECM v8.0 (schedule) et Integrity. Vous pouvez écrire le vôtre dans un fichier TOML. Un
*contrôle* possède une population (les activités ou les relations qu'il examine), un nombre trouvé,
une valeur, une cible et un statut :

- `pass` ou `fail` : la valeur atteint ou manque la cible.
- `info` : le contrôle n'a pas de cible, ou donne sa valeur pour examen.
- `n/a` : le contrôle a besoin d'une Baseline et aucune n'est chargée, ou il n'a rien à mesurer
  (population vide, pas de Data Date, pas de mise à jour antérieure).
- `error` : la règle n'a pas pu s'exécuter. La note en donne la raison, et la page ou la commande
  continue.

Un même nom ne désigne pas le même décompte dans tous les standards. Les contrôles P6 comparent des
heures, comme le fait P6. DCMA 14-Point et DECM comptent des jours ouvrés. Le BEI du standard P6
divise par toutes les activités de la Baseline. Celui de DCMA divise par les activités dues à la
Data Date. Pour les différences, consultez
[docs/standards.md](standards.md#same-check-several-definitions). Le statut est jugé sur la valeur
arrondie à six décimales, alors que l'affichage en montre moins : une valeur de 0,9545 s'affiche
`0.95` et satisfait `> 0.95`.

Le *score* d'un standard est le nombre de critères en pass rapporté au nombre de critères évalués
(pass plus fail). Les contrôles en `info`, `n/a` ou `error` n'entrent dans aucun des deux termes, et
les contrôles qui partagent un même item forment un seul critère : le standard P6 a 18 lignes et 17
critères. Le score est une convention de xerscope. L'aide de l'application précise elle-même
qu'aucune source ne définit de score global. Chaque contrôle peut être retracé jusqu'à sa
population, son calcul et sa source sur la page **Audit**.

### Recalcul

xerscope possède son propre moteur de calcul du chemin critique. Il recalcule un fichier avec les
règles de P6 Professional 23.12 / 24, chaque date sur le calendrier propre à l'activité et à la
minute près, puis compare ce qu'il a calculé avec ce que le fichier enregistre. Le moteur applique
les éléments suivants :

- tous les calendriers, avec leurs périodes de travail, leurs jours fériés et leurs exceptions ;
- les quatre types de relation, avec le Lag sur le calendrier que désigne l'option du projet (celui
  du successeur par défaut) ;
- le Lag SS d'un prédécesseur commencé, selon l'option du projet : à partir de son début au plus
  tôt, moins le Lag déjà écoulé depuis son début réel, ou à partir de son début réel avec le Lag
  entier ;
- les neuf types de contrainte, primaires et secondaires ;
- Retained Logic (logique conservée), Progress Override (priorité à l'avancement) ou Actual Dates
  (dates réelles), et les dates Expected Finish ;
- les activités Resource Dependent (dépendantes des ressources) sur les calendriers de leurs
  ressources, avec les affectations pilotantes et le Lag d'affectation ; la durée d'une affectation
  est égale à ses unités restantes divisées par ses unités par heure ;
- As Late As Possible (au plus tard), Level of Effort (niveau d'effort), les extrémités ouvertes,
  Must Finish By et le Longest Path (chemin le plus long).

Une règle dépend de la version de P6 qui a exporté le fichier. Une date Expected Finish antérieure
au début au plus tôt ramène la durée restante à 0 pour un export d'une version inférieure à 26. À
partir de la version 26, la durée restante enregistrée est conservée.

La comparaison porte sur chaque activité qui n'est ni terminée ni de type Level of Effort. Pour
chacune, elle lit les dates au plus tôt et au plus tard enregistrées, le Total Float (marge totale)
et le Free Float (marge libre), ainsi que les dates restantes de ses affectations de ressources. Une
date concorde quand elle indique la même heure, à la minute près. La comparaison sert à établir la
confiance dans le fichier. Selon la lecture qu'en fait le code lui-même, une différence signifie que
le fichier a été modifié après le dernier F9, ou qu'il utilise une fonction de calcul que xerscope
ne modélise pas. Des contrôles comme ceux du Float élevé ou du Float négatif lisent le Float
enregistré dans le fichier. La comparaison vous indique donc si ce Float est bien celui que produit
la logique du fichier. Le standard Integrity exécute la même comparaison dans les contrôles INT-01
et INT-03. Pour l'algorithme et ses éléments de preuve, consultez [docs/cpm.md](cpm.md) (en
anglais).

### Unités de temps

P6 enregistre les durées, le Float et le Lag en heures, et xerscope les conserve en heures. Trois
unités apparaissent dans les sorties :

- Les heures. Les contrôles de P6 Check Schedule comparent des heures.
- Les jours ouvrés (`wd`) : les heures divisées par le nombre d'heures par jour d'un calendrier
  (`CALENDAR.day_hr_cnt` ; 8 heures quand ce champ est vide, égal à 0 ou inférieur à une minute).
  Pour une activité, c'est le calendrier de l'activité. Pour un total de projet, comme le
  déplacement de la fin prévisionnelle, c'est le calendrier du projet.
- Les jours calendaires (`cal. d`). Un seul chiffre les utilise : **Time gap** (Écart en temps) sur
  la page **Earned value**.

Le temps de travail vient du champ `clndr_data` de chaque calendrier : les périodes de travail de
chaque jour de la semaine et les exceptions. Une exception sans heures est un jour non ouvré. Une
exception avec des heures est un jour ouvré avec ces heures. Une date qui devient plus tardive se
lit en négatif partout où un déplacement est donné en jours ouvrés : le déplacement de la fin, le
glissement d'un jalon, les déplacements de dates du journal des modifications, les écarts de début
et de fin. L'écart de délais (*schedule variance*) et l'écart en temps sont négatifs quand le projet
est en retard.

### Valeur planifiée, valeur acquise et engagements

Les chiffres de valeur acquise sont en heures de main-d'œuvre :

- La Planned Value (PV, valeur planifiée) est égale aux unités de main-d'œuvre de la Baseline
  multipliées par le Schedule % Complete (pourcentage d'avancement planifié). Le Schedule % Complete
  est linéaire en temps de travail entre le début et la fin de la Baseline, à la minute près, sur le
  calendrier de l'activité de la Baseline tel que le fichier de Baseline le définit.
- L'Earned Value (EV, valeur acquise) est égale aux unités de main-d'œuvre de la Baseline
  multipliées par le Performance % Complete (pourcentage d'avancement de performance). Celui-ci suit
  la technique de valeur acquise du WBS de l'activité : pourcentage d'avancement de l'activité,
  0/100, 50/50 ou pourcentage personnalisé. Une activité de la mise à jour qui n'est pas dans la
  Baseline n'acquiert rien et figure dans une liste.
- L'Actual Cost (AC, coût réel) correspond aux heures de main-d'œuvre réelles de toutes les
  activités de la mise à jour, l'Estimate to Complete (ETC, estimation du reste à faire) aux heures
  restantes, et l'Estimate at Completion (EAC, estimation à l'achèvement) à AC plus ETC. Les
  chiffres de coût restent masqués tant que vous n'avez pas coché **Costs** (Coûts).

Le PPC lit deux mises à jour consécutives, W−1 et W. Un *engagement* est un début ou une fin que W−1
planifie au plus tard à la Data Date de W, pour une activité pas encore commencée (ou pas encore
terminée) dans W−1. Il est tenu quand W contient la date réelle, au plus tard à cette Data Date. PPC
Start et PPC Finish sont les engagements tenus rapportés aux engagements pris, pour chaque type. PPC
W/W−1 couvre les deux. Le travail déjà en retard à W−1 est lui aussi engagé, par défaut. Les jalons
et les activités Level of Effort sont exclus, et une activité supprimée dans W est un changement de
périmètre, pas un engagement manqué. Quand rien n'était dû, le PPC affiche un tiret, pas 0.

L'écart de début et l'écart de fin d'une activité sont égaux à sa date dans W−1 (ou W−2) moins sa
date dans W, en jours ouvrés de son calendrier dans W. L'écart est vide quand une date manque.

### Ce qui reste sur votre machine

xerscope est conçu pour des plannings qui ne doivent pas quitter votre machine :

- L'application écoute sur `localhost` uniquement, sauf si vous la démarrez avec une autre valeur de
  `--host`. Elle n'a pas de procédure de connexion : tout programme et tout utilisateur local de la
  même machine peuvent y accéder.
- Le code de xerscope n'effectue aucun appel réseau. Les statistiques d'utilisation sont
  désactivées, et l'application sert elle-même ses deux polices.
- Un fichier téléversé est conservé dans la mémoire de la session, et le code de xerscope ne l'écrit
  jamais sur le disque. Pendant l'arrivée d'un fichier de plus de 1 Mo, le gestionnaire de
  téléversement de Streamlit le fait passer par un fichier temporaire du répertoire temporaire du
  système, supprimé une fois lu. Pour éviter cette copie temporaire, lisez le fichier depuis un
  dossier. L'application elle-même n'écrit rien sur le disque, à une exception près : une correction
  enseignée dans le champ **Ask the schedule** est enregistrée quand un dossier de lexique est
  configuré, ce qui n'est pas le cas par défaut.
- La ligne de commande n'écrit que là où vous le lui demandez, et les téléchargements sont
  anonymisés par défaut.

Ces affirmations décrivent le code de xerscope. Streamlit et Plotly, sur lesquels l'application est
construite, se comportent comme le dit leur propre code. Pour les requêtes qu'émet Streamlit,
consultez [Matrice de flux](it-deployment-guide.fr.md#matrice-de-flux) dans le guide de déploiement
pour la DSI.

## Premiers pas

À la fin de cette partie, xerscope est installé, l'application affiche une série de démonstration de
huit mises à jour hebdomadaires, et vous avez lu le même contrôle dans l'application et sur la ligne
de commande.

Avant de commencer, vérifiez que vous disposez d'un terminal, de git, de Python 3.11 ou version
ultérieure, d'un accès réseau pour l'installation, et de uv, l'outil qui installe et exécute
xerscope. Pour installer uv, consultez la [documentation de uv](https://docs.astral.sh/uv/). Les
commandes de ce guide sont écrites pour un interpréteur de commandes (shell) Linux. Sous Windows,
l'intégration continue (CI) du projet installe xerscope avec `uv sync --locked --extra crosscheck`
et exécute `sample` et `crosscheck` à chaque exécution. Chaque semaine, elle y exécute aussi
`uv sync --locked`, la suite de tests, `sample`, `info` et `export`.

### Installer xerscope et générer la série de démonstration

Pour installer xerscope et créer les fichiers de démonstration, procédez comme suit :

1. Récupérez le code source dans un dossier nommé `xerscope`. Cette étape nécessite un accès en
   lecture au dépôt.
   ```bash
   git clone https://github.com/Xerscope/Xerscope xerscope
   ```
2. Entrez dans le dossier. Toutes les commandes suivantes s'exécutent depuis ce dossier.
   ```bash
   cd xerscope
   ```
3. Installez xerscope et ses dépendances, aux versions que fixe le fichier `uv.lock`. uv crée
   l'environnement dans un dossier `.venv` du code source.
   ```bash
   uv sync --locked
   ```
4. Vérifiez l'installation en listant les commandes.
   ```bash
   uv run xerscope --help
   ```
   La sortie commence par `usage: xerscope [-h]` et liste 12 commandes, de `app` à `lexicon`.
5. Générez la série de démonstration.
   ```bash
   uv run xerscope sample
   ```
   La commande affiche les huit fichiers qu'elle a écrits, un par semaine. La date qui figure dans
   chaque nom est la Data Date de la mise à jour :
   ```text
   data/sample/PRJ-ALPHA_2026-08-31.xer
   data/sample/PRJ-ALPHA_2026-09-07.xer
   ...
   data/sample/PRJ-ALPHA_2026-10-19.xer
   ```

### Démarrer l'application et lire les fichiers

Pour lire les huit fichiers dans l'application, procédez comme suit :

1. Démarrez l'application sur le dossier de démonstration.
   ```bash
   uv run xerscope app --data data/sample
   ```
   Le terminal affiche `URL: http://localhost:8501` et reste occupé tant que l'application
   s'exécute.
2. Dans votre navigateur, ouvrez `http://localhost:8501`. La page **Overview** (Vue d'ensemble)
   affiche le message « Load your weekly XER exports from the sidebar's Files line (upload or folder
   path). » et la barre latérale affiche **Files · none read** (Fichiers · aucun lu). Rien n'est
   encore lu.
3. Dans la barre latérale, cliquez sur **Files · none read**. La fenêtre **Files and baseline**
   (Fichiers et Baseline) s'ouvre. Elle liste les huit fichiers, sans en sélectionner aucun. La
   première ligne indique `PRJ-ALPHA_2026-08-31.xer — PRJ-ALPHA · 31 Aug 2026 · 29 tasks`. Le
   compteur indique **0 of 8 ticked** (0 coché sur 8).
4. Cliquez sur **Select all** (Tout sélectionner). Le compteur indique **8 of 8 ticked**.
5. Cliquez sur **Done**. Les fichiers sont lus, et la progression s'affiche dans la barre latérale.
   Puis la fenêtre revient d'elle-même, cette fois avec sa seule section **Baseline** :
   **Baseline (BL)** est réglé sur `2026-08-31 · PRJ-ALPHA_2026-08-31.xer`, la première mise à jour.
   La page indique « 8 files · 1 project read. Choose the baseline in the window (the sidebar's
   Baseline line opens it again), then Done: the pages are computed once, against it. »
6. Cliquez de nouveau sur **Done** pour conserver cette Baseline. La page **Overview** s'affiche. La
   barre latérale affiche **Files · 8 files · 1 project** et **Baseline · update 2026-08-31**. Sous
   le titre de la page, une ligne résume ce qui est lu :
   ```text
   PRJ-ALPHA · status date 19 Oct 2026 · BL update 2026-08-31 (the window's choice) · EV budgeted, planned dates · costs off · 8 files · 1 project
   ```
   Quatre chiffres suivent : **Forecast finish** (Fin prévisionnelle) `23 Mar 2027`,
   **Shift since first update** (Déplacement depuis la première mise à jour) `-15.0 wd`,
   **Tasks complete** (Tâches terminées) `7 / 30` et **Critical tasks** (Tâches critiques) `18`. La
   fin prévisionnelle est plus tardive de 15 jours ouvrés que dans la première mise à jour.

### Lire une page

Pour lire les contrôles de planning de la dernière mise à jour, procédez comme suit dans
l'application :

1. Dans la navigation, sous **Analysis**, cliquez sur **Schedule health**. **Standard** est sur
   **P6 Check Schedule** et **Update** (Mise à jour) est sur
   `2026-10-19 · PRJ-ALPHA_2026-10-19.xer`. Les cartes indiquent **P6 Check Schedule score** `29 %`,
   **Checks passed** (Contrôles réussis) `6 / 18` et **Checks failed** (Contrôles en échec) `12`. Le
   tableau **Results** comporte une ligne par contrôle.
2. Dans la section **Detail by check** (Détail par contrôle), cliquez sur la première ligne,
   `FAIL P6-01 · Logic — 8.7 % (2 / 23) · target < 5%`. Le panneau indique « 8.7 % misses the target
   < 5 %. » et liste les deux activités que le contrôle a trouvées.

### Exécuter le même contrôle sur la ligne de commande

Pour obtenir le même résultat sans l'application, procédez comme suit :

1. Ouvrez un second terminal dans le dossier `xerscope`. L'application continue de s'exécuter dans
   le premier.
2. Exécutez les contrôles P6 Check Schedule sur la dernière mise à jour, avec la première mise à
   jour comme Baseline.
   ```bash
   uv run xerscope check data/sample/PRJ-ALPHA_2026-10-19.xer --baseline data/sample/PRJ-ALPHA_2026-08-31.xer
   ```
   La sortie comporte 18 lignes de contrôles et commence ainsi :
   ```text
   P6 Check Schedule · PRJ-ALPHA_2026-10-19.xer · data date 2026-10-19 · baseline BL 2026-08-31 · PRJ-ALPHA_2026-08-31.xer
       id                             check target  actual  found  total status
    P6-01                             Logic   < 5%    8.70      2     23   fail
    P6-02                  Hard Constraints   < 1%    0.00      0     22   pass
    P6-03                  Soft Constraints   < 5%    9.09      2     22   fail
   ...
   ```
   La ligne P6-01 porte les chiffres de la page : 2 trouvées sur 23. Six lignes indiquent `pass` et
   12 indiquent `fail`, comme les cartes de la page.
3. Dans le premier terminal, appuyez sur `Ctrl+C` pour arrêter l'application. Streamlit affiche
   `Stopping...`, puis Python affiche une trace d'appels (traceback) qui se termine par
   `KeyboardInterrupt`. L'application est arrêtée.

Vous avez installé xerscope, lu une série de huit mises à jour par rapport à une Baseline, et obtenu
les mêmes résultats de contrôle dans l'application et sur la ligne de commande. La série de
démonstration comporte des défauts volontaires, listés dans
[Série de démonstration](#série-de-démonstration) de ce guide. Pour travailler sur vos propres
fichiers, passez à
[Charger des fichiers et choisir la Baseline](#charger-des-fichiers-et-choisir-la-baseline) de ce
guide.

## Guides pratiques

Chaque guide de cette partie vise un objectif. Les commandes utilisent la série de démonstration
de [Premiers pas](#premiers-pas) de ce guide, si bien que chacune s'exécute telle quelle depuis le
dossier du code source. Remplacez `data/sample` et les noms des fichiers de démonstration par les
vôtres. Toutes les options de toutes les commandes figurent dans [Référence](#référence) de ce
guide.

### Charger des fichiers et choisir la Baseline

Utilisez ce guide pour lire vos propres exports hebdomadaires dans l'application et pour définir la
Baseline par rapport à laquelle ils sont mesurés. Conservez un seul fichier `.xer` par Data Date
dans le dossier. Pour la signification de chaque Baseline, consultez
[Baselines et types proposés par l'application](#baselines-et-types-proposés-par-lapplication) de ce
guide. Pour lire les fichiers `.xer` d'un dossier, procédez comme suit :

1. Démarrez l'application sur le dossier, puis ouvrez `http://localhost:8501` dans votre navigateur.
   ```bash
   uv run xerscope app --data data/sample
   ```
2. Dans la barre latérale, cliquez sur **Files · none read**. La fenêtre **Files and baseline**
   liste les fichiers `.xer` du dossier, sans en sélectionner aucun.
3. Cochez la case de chaque fichier à lire, ou cliquez sur **Select all**.
4. Si un fichier contient plusieurs projets, choisissez le projet à lire dans la liste sous
   **Project read from each file · why** (Projet lu dans chaque fichier · pourquoi).
5. Cliquez sur **Done**. Les fichiers sont lus, et la fenêtre revient avec sa section **Baseline**.
6. Dans **Baseline (BL)**, choisissez la Baseline. Si vous choisissez
   **Baseline in each file (P6 Project Baseline)**, choisissez aussi dans
   **When a file has no baseline** (Quand un fichier n'a pas de Baseline) ce par rapport à quoi les
   autres mises à jour sont mesurées. Avec **None**, leurs contrôles de Baseline affichent `n/a`.
7. Cliquez sur **Done**. Les pages sont calculées par rapport à la Baseline. La ligne **Baseline**
   de la barre latérale et la ligne sous chaque titre de page la nomment.

Pour changer de Baseline plus tard, cliquez sur la ligne **Baseline** de la barre latérale,
choisissez, puis cliquez sur **Done**. La même section contient **Earned value basis** (Base de
valeur acquise) et **Link renumbered tasks by GUID**. Cochez cette dernière case quand la barre
latérale signale des activités renumérotées. Pour désigner un fichier de Baseline séparé au
démarrage, ajoutez `--baseline FILE` à la commande `app` : **Baseline (BL)** démarre alors sur
**Separate baseline file**.

Pour lire un autre dossier sans redémarrer, saisissez un chemin absolu, ou un chemin qui commence
par `~`, dans le champ **…or read a folder** (…ou lire un dossier) de la fenêtre. Le dossier doit se
trouver sous la racine des dossiers : le dossier `--data` quand vous en avez donné un, sinon votre
répertoire personnel. Pour lire des fichiers qui ne sont dans aucun dossier de ce type, ajoutez-les
sous **Upload .xer files** (Téléverser des fichiers .xer), jusqu'à 200 Mo chacun. Les fichiers
téléversés priment sur le dossier.

#### Utiliser un export P6 XML ou un sous-dossier baselines

Utilisez un export P6 XML quand vos fichiers `.xer` nomment une Project Baseline qu'ils ne
contiennent pas. Le message de l'application décrit lui-même l'export dans P6 par « Export >
Primavera P6 XML, Baselines to Export ». Pour utiliser l'export, procédez comme suit :

1. Placez le fichier `.xml` dans le dossier des mises à jour, à côté des fichiers `.xer`.
2. Dans la section **Baseline** de la fenêtre **Files and baseline**, choisissez
   **Baseline in each file (P6 Project Baseline)** dans **Baseline (BL)**.
3. Dans **Baseline file in the folder** (Fichier de Baseline du dossier), vérifiez que le fichier
   `.xml` est choisi. Un fichier `.xml` unique est choisi automatiquement.
4. Cliquez sur **Done**. Chaque mise à jour est mesurée par rapport à la Baseline que nomme son
   fichier, lue dans l'export. Une mise à jour mesurée par rapport à une Baseline *probable* est
   annoncée sous le titre de chaque page et dans la barre latérale.

Si vous choisissez plutôt **Separate baseline file**, une seule Baseline de l'export sert pour
toutes les mises à jour : celle que nomme la dernière mise à jour, sinon la Project Baseline de
l'export, sinon son unique Baseline. Sur la ligne de commande, `--baseline` accepte aussi un export
P6 XML : l'option lit la Project Baseline de l'export, sinon son unique Baseline, et ne regarde pas
la Baseline que nomme chaque mise à jour.

Pour proposer des fichiers de Baseline qui ne doivent jamais être lus comme des mises à jour,
placez-les (fichiers `.xer` ou exports P6 XML) dans un sous-dossier nommé `baselines` du dossier des
mises à jour. Choisissez **Separate baseline file**, puis le fichier dans
**Baseline file in the folder**, où il est listé sous la forme `baselines/<name>`. La ligne de
commande ne lit pas ce sous-dossier.

### Contrôler la santé du planning selon un standard

Utilisez ce guide pour exécuter les contrôles d'un standard sur une mise à jour ou sur toute la
série, et pour obtenir les activités que chaque contrôle a trouvées. Pour lire les contrôles dans
l'application, procédez comme suit sur la page **Schedule health** :

1. Dans **Standard**, choisissez le standard et, dans **Update**, la mise à jour. Les cartes donnent
   le score et le nombre de contrôles réussis, en échec, à examiner et non applicables. Le tableau
   **Results** comporte une ligne par contrôle.
2. Dans la section **Detail by check**, cliquez sur un contrôle. Son panneau donne ce que mesure le
   contrôle, son calcul, sa population, sa source et les éléments qu'il a trouvés.
   **Show the N tasks in the Gantt** (Afficher les N tâches dans le Gantt) ouvre ces activités dans
   le planning.
3. Pour voir un contrôle dans le temps, allez à **Trend across updates** (Tendance au fil des mises
   à jour), cliquez sur **Compute the trend on the N updates** (Calculer la tendance sur les N mises
   à jour), puis choisissez le contrôle dans **Check** (Contrôle).
4. Pour conserver les résultats, cliquez sur **Summary (CSV)** (Synthèse) ou sur
   **All flagged items (CSV)** (Tous les éléments signalés).

Pour exécuter un standard sur chaque mise à jour d'un dossier et écrire les résultats, exécutez la
commande `check` :

```bash
uv run xerscope check data/sample --standard DCMA --baseline data/sample/PRJ-ALPHA_2026-08-31.xer --out results.csv --flagged flagged
```

La commande affiche un tableau par mise à jour, dans l'ordre des Data Dates, puis
`written results.csv`. Le CSV contient une ligne par contrôle et par mise à jour. Le dossier
`flagged` contient un CSV par mise à jour et par contrôle qui a trouvé quelque chose, par exemple
`PRJ-ALPHA_2026-08-31_DCMA-01.csv`. Sans option de Baseline, les contrôles qui ont besoin d'une
Baseline affichent `n/a`. La page lit la Project Baseline du fichier de la mise à jour quand ce
fichier en contient une utilisable. Pour reproduire ce résultat, utilisez `--baseline-in-file`.

### Auditer un contrôle

Utilisez ce guide quand un décompte vous surprend et que vous voulez voir quelles activités
l'expliquent, ou ce que donne le contrôle avec un autre seuil. L'audit n'existe que dans
l'application. Procédez comme suit sur la page **Audit** :

1. Choisissez le standard dans **Standard**, la mise à jour dans **Update** et le contrôle dans
   **Check**. Sur **Schedule health**, le bouton **Audit this check** (Auditer ce contrôle) du
   panneau d'un contrôle le fait pour vous.
2. Dans la section **Sets** (Ensembles), lisez les onglets **Counted** (Comptés),
   **Checked, not counted** (Contrôlés, non comptés) et **Excluded** (Exclus), chacun avec un bouton
   **Download CSV** (Télécharger le CSV), puis **Population, step by step** (Population, étape par
   étape) : chaque étape, ce qu'elle a retiré et ce qu'elle a laissé.
3. Pour un contrôle du standard P6, ouvrez
   **Calculation sheet: population, fields, sources, worked example** (Fiche de calcul : population,
   champs, sources, exemple chiffré).
4. Pour essayer d'autres réglages, modifiez **Rule parameters** (Paramètres de la règle) ou
   **Target** (Cible) sous **Settings for this audit** (Réglages de cet audit). Les cartes **Audit**
   et **Audit status** (Statut de l'audit) affichent le résultat à côté de celui du standard.
   **Reset** (Réinitialiser) revient aux valeurs du standard. Les modifications restent sur cette
   page.
5. Pour rendre un réglage permanent, ouvrez **Settings: how to change this check for good**
   (Réglages : comment modifier ce contrôle durablement) et copiez le bloc `[[metric]]` dans votre
   propre standard.

### Recalculer comme P6 et lire les différences

Utilisez ce guide pour savoir si les dates et le Float enregistrés dans un fichier sont bien ceux
que produit sa propre logique. Pour ce qui est comparé et pourquoi, consultez [Recalcul](#recalcul)
de ce guide. Procédez comme suit :

1. Exécutez la commande `recalc` avec un rapport et un CSV des valeurs recalculées.
   ```bash
   uv run xerscope recalc data/sample/PRJ-ALPHA_2026-10-19.xer --report --out recalc.csv
   ```
   La sortie ressemble à ceci :
   ```text
   PRJ-ALPHA_2026-10-19.xer · 30 activities · data date 2026-10-19 08:00 · recalculated finish 2027-03-23 16:00
     early_end_date            22 / 22      identical
   ...
     total_float_hr_cnt        22 / 22      identical
     assignments (19): 76 / 76 stored dates identical
     written recalc.csv
   ```
2. Lisez chaque ligne comme le nombre de valeurs enregistrées reproduites sur le nombre de valeurs
   enregistrées comparées.
3. Si une ligne montre une différence, lisez le tableau qui la suit : par activité et par champ, la
   valeur enregistrée, la valeur calculée et l'écart en heures ouvrées (`gap_hr`). Le bloc
   `differences by activity shape`, qu'ajoute `--report`, regroupe les différences par statut, type,
   contrainte, liens et option, de sorte que les différences d'une semaine désignent une règle.
4. Lisez les lignes qui commencent par `warning:`. Elles nomment ce que xerscope ne modélise pas
   dans ce fichier, par exemple le nivellement (leveling).

Le code de sortie est 0 quel que soit le nombre de différences. Dans l'application, la même
comparaison se trouve sur la page **Schedule health**. Choisissez **Integrity** dans **Standard** et
lisez INT-01 (**Schedule recalculated**, planning recalculé ; les quatre dates et le Total Float,
sans le Free Float) et INT-03 (**Assignments recalculated**, affectations recalculées). Les valeurs
qui diffèrent se trouvent sur la page **Debug** (Débogage), dans le bloc
**3 · INT-01 / INT-03 differences**.

### Comparer deux mises à jour

Utilisez ce guide pour lister tout ce qui a changé entre deux exports. Pour comparer deux mises à
jour chargées, procédez comme suit sur la page **Changelog** (Journal des modifications) :

1. Dans **From (older)** (De, la plus ancienne) et **To (newer)** (À, la plus récente), choisissez
   les deux mises à jour. La page démarre sur la dernière mise à jour et celle qui la précède.
2. Lisez les cartes : **Forecast finish**, **Added / deleted** (Ajoutées / supprimées),
   **Logic changes** (Modifications de logique), **Durations changed** (Durées modifiées),
   **Retroactive actuals** (Dates réelles rétroactives) et **Became critical** (Devenues critiques).
3. Dans la section **All changes** (Toutes les modifications), restreignez la liste avec
   **Category**, **Change** (Modification) et **Search** (Rechercher). Pour conserver la liste
   entière, cliquez sur **Download changelog (CSV)**.

Pour comparer deux fichiers sur la ligne de commande, le plus ancien en premier, exécutez la
commande `changelog`. Elle affiche le nombre de modifications de chaque type, puis
`written changelog.csv (60 changes)`.

```bash
uv run xerscope changelog data/sample/PRJ-ALPHA_2026-10-12.xer data/sample/PRJ-ALPHA_2026-10-19.xer --out changelog.csv
```

### Lire l'analyse des retards

Utilisez ce guide pour voir ce qui a déplacé la fin du projet entre une mise à jour et la
précédente. La page a besoin d'au moins deux mises à jour et ne lit pas la Baseline. La page nomme
sa méthode : AACE RP 29R-03 MIP 3.4, contemporaneous split (half-stepped update analysis). Pour la
méthode, consultez
[docs/formulas.md](formulas.md#51-half-step-reading-of-a-week-analysisforensicspy) (en anglais).
Procédez comme suit sur la page **Delay analysis** (Analyse des retards) :

1. Dans **Update**, choisissez une mise à jour postérieure à la première.
2. Lisez la légende **Finish held by** (Fin tenue par) : la dernière activité, Must Finish By ou une
   contrainte Mandatory Finish (fin obligatoire). Puis lisez les cartes :
   **Finish before replanning** (Fin avant replanification) avec le glissement de la semaine,
   **Finish shown** (Fin affichée), **Longest path float** (Float du Longest Path) et
   **Tasks matched** (Tâches rapprochées).
3. Dans la section **Step by step** (Étape par étape), lisez l'effet de chaque type de modification
   sur la fin : avancement, périmètre, durées, logique, contraintes, puis calendriers et options.
4. Dans la section **Longest path**, lisez quelles activités sont restées sur le Longest Path, y
   sont entrées ou en sont sorties, ainsi que les engagements de la semaine sur ce chemin.
5. Dans la section **Every update** (Chaque mise à jour), lisez la série : une fin affichée qui ne
   bouge pas alors que la fin avant replanification continue de glisser est un retard absorbé par la
   replanification.

Si la page avertit que xerscope ne recalcule pas la fin que P6 a enregistrée dans le fichier, ne
lisez les déplacements qu'à titre indicatif.

### Suivre la valeur acquise

Utilisez ce guide pour lire la valeur planifiée, la valeur acquise et la performance des délais sur
la série. La page a besoin d'une Baseline qui porte des heures de main-d'œuvre. Pour les
définitions, consultez
[Valeur planifiée, valeur acquise et engagements](#valeur-planifiée-valeur-acquise-et-engagements)
de ce guide. Procédez comme suit sur la page **Earned value** :

1. Dans **Update**, choisissez la mise à jour, puis lisez les premières cartes :
   **Percent complete** (Pourcentage d'avancement), **Percent scheduled** (Pourcentage planifié),
   **SPI (labor units)** (SPI en unités de main-d'œuvre), **SV**, **BEI (P6 / DCMA)** et **EAC**.
2. Dans les sections **Where the project stands** (Où en est le projet), **At what pace** (À quel
   rythme) et **Does it end on the planned finish** (Se termine-t-il à la fin planifiée), lisez les
   chiffres d'Earned Schedule (méthode du délai acquis).
3. Dans la section **S-curve** (Courbe en S), lisez PV, EV et AC dans le temps. **Show as % of BAC**
   (Afficher en % du BAC) donne des pourcentages.
4. Pour mesurer la mise à jour par rapport à sa propre Baseline, comme P6 calcule sa valeur
   planifiée, activez **P6 view: the file's baseline** (Vue P6 : la Baseline du fichier).
5. Pour voir les chiffres de coût, cochez **Costs** dans la barre latérale. La page ajoute la carte
   **SPI** ainsi que les lignes et les colonnes de coût.
6. Ouvrez **Earned hours by task** (Heures acquises par tâche) pour lire le Schedule %, le
   Performance % et la technique EV de chaque activité. Sous le tableau, la page liste les activités
   qui ne sont pas dans la Baseline et celles dont la technique EV n'est pas modélisée.

### Suivre les jalons

Utilisez ce guide pour observer le déplacement des dates prévisionnelles des jalons d'une mise à
jour à l'autre. La tendance a besoin d'au moins deux mises à jour. Procédez comme suit sur la page
**Milestone trend** (Tendance des jalons) :

1. Dans **Milestones and key tasks (up to 6)** (Jalons et tâches clés, 6 au plus), choisissez les
   jalons ou les activités. La page démarre sur les jalons de fin de la dernière mise à jour, les
   critiques en premier. Les boutons **Finish milestones** (Jalons de fin), **Critical milestones**
   (Jalons critiques) et **Clear** (Effacer) règlent la liste en un clic.
2. Lisez le graphique, une ligne par jalon. Le dernier point est rouge quand le jalon est devenu
   plus tardif dans la dernière mise à jour, et vert quand il est devenu plus précoce.
3. Dans la section **Slippage** (Glissement), lisez le glissement de chaque jalon en jours ouvrés
   sur son propre calendrier. Une date plus tardive se lit en négatif.

### Mesurer le PPC

Utilisez ce guide pour mesurer, semaine après semaine, combien des débuts et des fins planifiés pour
la semaine ont eu lieu. La page a besoin d'au moins deux mises à jour. Procédez comme suit sur la
page **PPC & progress** (PPC et avancement) :

1. Dans **Week ending** (Semaine se terminant le), choisissez la mise à jour qui clôt la semaine.
2. Facultatif : dans **PPC target (%)** (Cible de PPC), définissez la cible. Elle déplace la ligne
   pointillée du graphique.
3. Pour exclure le travail qui était déjà en retard à W−1, décochez
   **Include commitments late at W−1** (Inclure les engagements en retard à W−1).
4. Lisez **PPC Start**, **PPC Finish** et **PPC W/W−1**, avec **Starts kept** (Débuts tenus) et
   **Finishes kept** (Fins tenues). Un tiret signifie que rien n'était dû.
5. Dans la section **Commitments** (Engagements), lisez chaque engagement et son issue.
   **Milestones committed** (Jalons engagés) et **Unplanned work** (Travail non planifié) sont
   listés à part, hors décomptes. Dans la section **Start and finish variance** (Écart de début et
   de fin), lisez comment les dates de chaque activité se sont déplacées par rapport à W−1 et W−2.

### Explorer le Gantt et interroger le planning

Utilisez ce guide pour examiner une mise à jour sous forme de Gantt regroupé par WBS, et pour le
filtrer par une phrase. Pour explorer une mise à jour, procédez comme suit sur la page
**Gantt & WBS** :

1. Dans **Update**, choisissez la mise à jour. Dans **Compare with** (Comparer avec), choisissez ce
   que montre le contour derrière chaque barre : **Previous update** (Mise à jour précédente),
   **Baseline (BL)**, **First snapshot** (Premier snapshot), **None** ou une autre mise à jour
   chargée.
2. Pour vous concentrer sur une branche, choisissez-la dans **WBS**. Les cartes et le graphique
   suivent. Restreignez les lignes avec **Status** (Statut), **Float** et **Search**.
3. Activez **Logic links** (Liens logiques) pour tracer les relations, et désactivez **Hide LOE**
   (Masquer les LOE) pour afficher les activités Level of Effort. Dans **Timescale** (Échelle de
   temps), choisissez **Month** (Mois) ou **Week** (Semaine).
4. Cliquez sur une activité dans le graphique. Sa carte s'ouvre avec son identité, son statut, ses
   dates, ses contraintes, ses ressources et sa logique, ainsi que son **History across updates**
   (Historique au fil des mises à jour).
5. Pour conserver les lignes affichées, ouvrez **Table view** (Vue tableau) et cliquez sur
   **Download CSV**.

Pour filtrer le Gantt par une phrase, procédez comme suit sur la même page :

1. Dans **Ask the schedule**, saisissez une phrase, par exemple
   `critical not started in civil works`, puis appuyez sur `Enter` (touche Entrée). Un bandeau sous
   le champ indique ce qui a été compris. Sur la dernière mise à jour de la démonstration, il
   indique « 2 activities critical not started in CIV · Civil works; worst float -9 wd (C3050),
   latest finish 20/12/2026. »
2. Pour retirer un filtre, cliquez sur sa pastille, qui se termine par **×**. Pour effacer la
   phrase, cliquez sur **Show all** (Tout afficher).
3. Si le bandeau nomme un mot qu'il ne connaît pas, cliquez sur l'un des libellés sous
   **Did you mean** (Vouliez-vous dire), ou reformulez avec les mots du fichier.

Le champ lit l'anglais et le français. Il combine les mots avec `and`, `or`, `not` et des
parenthèses, compare des mesures (`float < 10 d`) et lit des dates (`starting next week`). Les mots
qui nomment un nœud WBS, un code ou une ressource doivent être ceux du fichier. Le champ utilise une
grammaire de mots-clés. Aucun modèle n'intervient.

### Exporter pour Power BI et télécharger des données anonymisées

Utilisez ce guide pour sortir des données de xerscope, avec ou sans les noms de votre projet. Pour
télécharger les tables Power BI depuis l'application, procédez comme suit :

1. Dans la barre latérale, décidez si les téléchargements sont anonymisés. **Anonymous exports**
   (Exports anonymes) est activé par défaut : les téléchargements portent de nouveaux Task ID et de
   nouveaux noms, et le reste du texte est vidé. Les pages affichent toujours les données des
   fichiers eux-mêmes.
2. Sur la page **Export for Power BI** (Export pour Power BI), dans **Format**, choisissez `parquet`
   ou `csv`.
3. Si **Anonymous exports** est activé, cliquez sur **Prepare anonymized downloads** (Préparer les
   téléchargements anonymisés). Les fichiers sont relus pour l'outil d'anonymisation.
4. Cliquez sur le bouton de téléchargement. Le zip contient quatre tables : `dim_snapshot`,
   `fact_activity`, `fact_relationship` et `fact_assignment`.

Le même bouton bascule et les deux mêmes étapes s'appliquent aux téléchargements des autres pages.
Pour télécharger une copie anonymisée des fichiers XER eux-mêmes, cliquez sur
**Build anonymized extract** (Construire l'extrait anonymisé) sous **Anonymized XER extract**
(Extrait XER anonymisé), puis sur **Download anonymized XER (.zip)**. L'extrait est anonymisé quelle
que soit la position du bouton bascule. Sur la ligne de commande, la commande `export` écrit les
quatre tables à partir d'un dossier de mises à jour et affiche leurs chemins. Ces tables ne sont pas
anonymisées.

```bash
uv run xerscope export data/sample --out export --format csv
```

### Écrire votre propre standard en TOML

Utilisez ce guide pour exécuter les contrôles et les cibles propres à votre entreprise. Procédez
comme suit :

1. Écrivez le modèle commenté dans un fichier. La commande affiche `written my.toml`.
   ```bash
   uv run xerscope standards --template my.toml
   ```
2. Listez les règles et leurs paramètres.
   ```bash
   uv run xerscope standards --rules
   ```
3. Modifiez le fichier `my.toml`. Donnez au standard un `id` et un `name` qui lui sont propres, et
   écrivez une table `[[metric]]` par contrôle, chacune avec un `id`, un `name` et une `rule`. Le
   format du fichier est décrit dans [Fichier de standard](#fichier-de-standard) de ce guide.
4. Exécutez le standard sur une mise à jour. Le tableau a pour titre le nom du standard. Une erreur
   dans le fichier arrête la commande avec une ligne qui nomme le fichier et la faute.
   ```bash
   uv run xerscope check data/sample/PRJ-ALPHA_2026-10-19.xer --standard my.toml
   ```

Pour utiliser le standard dans l'application, ouvrez **Use your own standard** (Utiliser votre
propre standard) sur la page **Schedule health** et ajoutez le fichier sous
**Upload a standard (.toml)** (Téléverser un standard). Le standard est conservé pendant la session.
Pour proposer des standards à toutes les sessions, démarrez l'application avec
`uv run xerscope app --standards FOLDER`, où `FOLDER` contient vos fichiers `.toml`. Un fichier
ajouté à ce dossier est vu sans redémarrage. Pour modifier la cible d'un contrôle intégré, la page
**Audit** fournit le bloc `[[metric]]` à copier. Pour le détail des règles, consultez
[docs/standards.md](standards.md#your-own-standard) (en anglais).

### Comparer xerscope avec P6

Utilisez ce guide pour confronter les chiffres de xerscope à ceux de P6 sur le même fichier.
L'en-tête du standard P6 intégré nomme le rapport dans P6 par « Tools > Check Schedule ». Un
pas-à-pas dans les menus de P6 n'est pas fourni. Pour comparer les décomptes du rapport Check
Schedule de P6 avec ceux de xerscope, procédez comme suit :

1. Dans P6, exécutez Check Schedule sur le même projet, la même Data Date et la même Baseline, et
   notez le nombre trouvé et le total de chaque ligne.
2. Écrivez les décomptes dans un fichier CSV nommé `p6-summary.csv`, avec les colonnes `id`, `found`
   et `total` et les identifiants qu'affiche xerscope. Cet exemple contient les décomptes de
   xerscope lui-même sur la démonstration, de sorte que la commande suivante signale une
   concordance :
   ```text
   id,found,total
   P6-01,2,23
   P6-06,3,22
   ```
3. Exécutez le contrôle avec l'option `--expect`.
   ```bash
   uv run xerscope check data/sample/PRJ-ALPHA_2026-10-19.xer --expect p6-summary.csv
   ```
   Après le tableau des résultats, la commande affiche une ligne par décompte comparé, avec une
   colonne `match`, puis `all counts match`. Quand un décompte diffère, elle affiche le nombre de
   différences et renvoie le code de sortie 1.

Dans l'application, la même comparaison se trouve sur la page **Schedule health**, dans
**Compare with a P6 Check Schedule report** (Comparer avec un rapport P6 Check Schedule). Saisissez
les décomptes dans **Found (report)** (Trouvés, rapport) et **Total (report)**, ou ajoutez le CSV
dans **Report counts (.csv)** (Décomptes du rapport). Les lignes laissées vides ne sont pas
comparées.

Pour comparer la valeur planifiée et la valeur acquise activité par activité, procédez comme suit :

1. Dans P6, enregistrez la vue Activities au format CSV avec les colonnes Activity ID, Planned Value
   Labor Units, Earned Value Labor Units et Schedule % Complete. Utilisez la même Data Date et la
   même Baseline que le fichier : rien ne le vérifie pour vous.
2. Exécutez la commande `pv-compare`. Remplacez `ACTIVITIES_CSV` par le chemin du fichier CSV.
   ```bash
   uv run xerscope pv-compare data/sample/PRJ-ALPHA_2026-10-19.xer --baseline data/sample/PRJ-ALPHA_2026-08-31.xer --p6 ACTIVITIES_CSV
   ```
3. Lisez le tableau des totaux qu'affiche la commande : PV et EV selon xerscope, selon P6, et
   l'écart, pour les activités rapprochées et pour les activités qu'un seul côté contient. Les cinq
   tables écrites dans le dossier `pv_compare` donnent l'écart par tranche de Schedule %, par cause
   candidate et par calendrier, ainsi que les activités en écart.

Si l'export nomme une colonne autrement, nommez-la avec `--column`, par exemple
`--column pv_hr="PV Labor Units"`. Dans l'application, la même comparaison se trouve sur la page
**Debug**, dans le bloc **10 · PV against a P6 export** (PV comparée à un export P6).

### Exécuter avec l'image Docker locale

Utilisez ce guide pour exécuter l'application dans un conteneur sur votre propre machine au lieu
d'installer uv et Python. La construction de l'image nécessite un accès réseau et Docker avec
BuildKit. Procédez comme suit dans le dossier du code source :

1. Créez le dossier que lit le conteneur, et copiez-y vos fichiers `.xer`.
   ```bash
   mkdir -p exports
   cp data/sample/*.xer exports/
   ```
2. Construisez l'image et démarrez le conteneur.
   ```bash
   docker compose up -d --build
   ```
3. Dans votre navigateur, ouvrez `http://localhost:8501`, et lisez les fichiers comme dans
   [Charger des fichiers et choisir la Baseline](#charger-des-fichiers-et-choisir-la-baseline) de ce
   guide. La fenêtre s'ouvre sur `/data`, qui est le dossier `exports`, monté en lecture seule.

Le conteneur n'est publié que sur `127.0.0.1`. Pour les propriétés de l'image et du conteneur,
consultez [Composants et images](it-deployment-guide.fr.md#composants-et-images),
[Option B](it-deployment-guide.fr.md#option-b-limage-locale-sur-linterface-de-bouclage-de-lhôte) et
[Limites de ressources et stockage par service](it-deployment-guide.fr.md#limites-de-ressources-et-stockage-par-service)
dans le guide de déploiement pour la DSI. Le téléversement, le champ de dossier (limité à `/data`)
et la page **Debug** sont disponibles. Pour fournir un fichier de Baseline, placez-le dans
`exports/baselines/` et choisissez-le dans **Baseline file in the folder**, ou téléversez-le dans la
fenêtre. Un `.xer` de Baseline placé directement dans `exports/` est listé parmi les mises à jour.
Après une mise à jour du code source, exécutez de nouveau `docker compose up -d --build`. Pour
exécuter une commande de la ligne de commande dans l'image, passez-la après le nom de l'image. La
commande `crosscheck` ne s'exécute pas dans l'image, et une commande qui écrit des fichiers a besoin
d'un dossier accessible en écriture monté dans le conteneur.

```bash
docker run --rm -v "$PWD/exports:/data:ro" xerscope check /data --standard P6
```

## Référence

Cette partie décrit la ligne de commande, l'application et leurs réglages.

### Ligne de commande

Le tableau suivant liste les 12 commandes. `uv run xerscope COMMAND --help` affiche les options
d'une commande. Certaines options y figurent sans description.

| Commande | Objet | Arguments positionnels |
|---|---|---|
| `app` | Lancer l'application web | Aucun |
| `info` | Résumer les mises à jour, une ligne chacune | `paths` : un ou plusieurs fichiers ou dossiers |
| `check` | Exécuter un standard | `paths` : un ou plusieurs fichiers ou dossiers |
| `standards` | Lister les standards et les règles, ou afficher le modèle | Aucun |
| `recalc` | Recalculer comme P6 et comparer avec les dates enregistrées | `paths` : un ou plusieurs fichiers ou dossiers |
| `changelog` | Lister ce qui a changé entre deux fichiers | `old`, puis `new` : deux fichiers |
| `export` | Écrire les tables Power BI | `folder` : un dossier |
| `crosscheck` | Comparer xerscope avec MPXJ | `paths` : un ou plusieurs fichiers ou dossiers |
| `pv-compare` | Comparer PV et EV avec un export Activities de P6 | `path` : un fichier, la mise à jour |
| `sample` | Générer la série de démonstration | Aucun |
| `ask-bench` | Noter la lecture du champ **Ask the schedule** | `path` : un fichier ou un dossier ; la dernière mise à jour est lue |
| `lexicon` | Lister ou construire les mots que le champ **Ask the schedule** lit comme un seul | `folder` : un dossier facultatif de groupes `*.toml` ; ou `build`, puis `source`, un dossier de fichiers `.xer` |

Les règles suivantes s'appliquent aux commandes qui lisent des fichiers :

- Un dossier représente les fichiers `.xer` qu'il contient directement, quelle que soit la casse.
  Les sous-dossiers et les autres fichiers ne sont pas lus.
- Un fichier nommé explicitement est lu quelle que soit son extension. Un export P6 XML nommé comme
  mise à jour est lu pour l'une de ses Baselines, sans avertissement.
- `~` est développé dans les chemins de `info`, `check`, `recalc`, `crosscheck` et `ask-bench`, et
  dans les trois options de chemin de `app`.
- `info`, `check` et `export` lisent les fichiers dans l'ordre des Data Dates, puis par nom de
  fichier. `recalc` les lit dans l'ordre donné. `info`, `check`, `export` et `ask-bench` refusent
  deux fichiers de même Data Date.
- Dans un dossier, un seul fichier `.xer` illisible arrête la commande, sauf pour `lexicon build`.
- Les fichiers de sortie existants sont écrasés sans confirmation. Rien n'est écrit en dehors de ce
  qu'indique une option ou un dossier par défaut.

#### Options

Le tableau suivant liste toutes les options. *Désactivée* est la valeur par défaut d'une option qui
ne prend pas de valeur.

| Commande | Option | Valeur par défaut | Signification |
|---|---|---|---|
| `app` | `--data DATA` | Aucune | Dossier des fichiers `.xer` hebdomadaires sur lequel s'ouvre la fenêtre **Files and baseline**. Transmis à l'application dans `XERSCOPE_DATA`, sous forme de chemin absolu. |
| `app` | `--baseline BASELINE` | Aucune | `.xer` de Baseline, ou export P6 XML contenant la Baseline. Transmis dans `XERSCOPE_BASELINE`. Le type de fichier est déterminé d'après son contenu. |
| `app` | `--standards STANDARDS` | Aucune | Dossier de fichiers `.toml` de standards. Transmis dans `XERSCOPE_STANDARDS`. |
| `app` | `--port PORT` | `8501` | Port, un entier. |
| `app` | `--host HOST` | `localhost` | Interface d'écoute. `0.0.0.0` expose les plannings au réseau. Aucun avertissement n'est affiché à l'exécution. |
| `check` | `--standard STANDARD` | `P6` | `P6`, `DCMA`, `DECM` ou `INTEGRITY`, quelle que soit la casse, ou le chemin d'un fichier `.toml`. Le texte d'aide ne nomme que P6 et DCMA. |
| `check` | `--baseline BASELINE` | Aucune | Un seul fichier de Baseline, XER ou export P6 XML, pour toutes les mises à jour. |
| `check` | `--planned-baseline` | Désactivée | Mesure chaque fichier par rapport à ses propres dates planifiées (`target_*`). |
| `check` | `--baseline-in-file` | Désactivée | Mesure chaque fichier par rapport à la Project Baseline de P6 qu'il contient (`sum_base_proj_id`). Nécessite des noms de fichiers distincts. |
| `check` | `--out OUT` | Aucune | Écrit tous les résultats dans ce CSV, une ligne par contrôle et par fichier. Le dossier doit exister. |
| `check` | `--flagged DIR` | Aucune | Écrit les éléments trouvés, un CSV par fichier et par contrôle qui a trouvé quelque chose, nommé `<file name without extension>_<check id>.csv`. Le dossier est créé. |
| `check` | `--expect CSV` | Aucune | Compare avec des décomptes saisis à partir de la synthèse Check Schedule de P6. Colonnes `id`, `found`, `total`, plus `file` quand plusieurs fichiers sont contrôlés. |
| `check` | `--fail-on {none,fail,error}` | `none` | `fail` : code de sortie 1 quand un résultat est `fail` ou `error`. `error` : code de sortie 1 sur `error` uniquement. Non évaluée quand `--expect` trouve une différence. |
| `standards` | `--rules` | Désactivée | Liste les 68 règles, chacune avec son unité, ses paramètres et leurs valeurs par défaut, et sa méthode. |
| `standards` | `--template [FILE]` | Désactivée | Écrit le modèle d'un standard dans `FILE` en UTF-8, ou l'affiche quand aucun fichier n'est nommé. |
| `recalc` | `--out OUT` | Aucune | Écrit les dates et le Float recalculés de chaque activité dans ce CSV. Avec plusieurs fichiers, un CSV par fichier, nommé `<file name without extension>_<name given>`. |
| `recalc` | `--report` | Désactivée | Regroupe les différences par forme d'activité. |
| `recalc` | `--show SHOW` | `20` | Nombre de lignes de différences à afficher, pour les activités puis de nouveau pour les affectations. |
| `changelog` | `--out OUT` | Aucune | Écrit chaque modification dans ce CSV, une ligne chacune. |
| `export` | `--out OUT` | `export` | Dossier de destination, créé s'il manque. |
| `export` | `--format {parquet,csv}` | `parquet` | Format de fichier des tables. |
| `crosscheck` | `--out OUT` | Aucune | Écrit chaque comparaison dans ce CSV. |
| `crosscheck` | `--cpm` | Désactivée | Compare le recalcul avec le moteur de calcul de MPXJ. |
| `crosscheck` | `--p6` | Désactivée | Lit les chemins comme des dossiers des jeux de référence P6 mis de côté (held-out) et compare le recalcul avec ce que P6 23.12 a calculé. |
| `crosscheck` | `--show SHOW` | `20` | Nombre de différences à afficher, pour `--cpm` et `--p6`. |
| `pv-compare` | `--baseline BASELINE` | Aucune | `.xer` de Baseline ou export P6 XML. L'une des options `--baseline` et `--planned-baseline` est obligatoire. |
| `pv-compare` | `--planned-baseline` | Désactivée | Utilise les dates planifiées de la mise à jour (`target_*`). |
| `pv-compare` | `--p6 CSV` | Obligatoire | Vue Activities de P6 enregistrée en CSV. |
| `pv-compare` | `--column FIELD=HEADER` | En-têtes de P6 | Une colonne que l'export nomme autrement. Répétable. |
| `pv-compare` | `--tolerance H` | `0.01` | Écart en heures en dessous duquel une activité concorde. |
| `pv-compare` | `--p6-total H` | Aucune | Total PV labor units affiché par P6. Ajoute une ligne de totaux. |
| `pv-compare` | `--out OUT` | `pv_compare` | Dossier des cinq tables, créé s'il manque. |
| `sample` | `--out OUT` | `data/sample` | Dossier de destination, créé avec ses parents. |
| `sample` | `--weeks WEEKS` | `8` | Nombre de fichiers hebdomadaires. Avec 0 ou moins, aucun fichier n'est écrit et le dossier est tout de même créé. |
| `ask-bench` | `--cases CASES` | Aucune | Fichier TOML de phrases `[[case]]` dont les filtres sont connus. Répétable. La commande a besoin de `--cases`, de `--self` ou des deux. |
| `ask-bench` | `--self` | Désactivée | Note les libellés du fichier lui-même, dits de toutes les façons que lit la grammaire. |
| `ask-bench` | `--anonymize` | Désactivée | Note `--cases` sur la copie anonymisée du fichier. |
| `ask-bench` | `--lexicon LEXICON` | Aucune | Dossier de groupes de synonymes `*.toml` à ajouter. |
| `ask-bench` | `--show SHOW` | `20` | Phrases manquées à afficher par jeu. |
| `lexicon` | `--word WORD` | Aucune | Affiche les mots lus comme celui-ci. |
| `lexicon` | `--out OUT` | Aucune | Avec `build` : le dossier du lexique. Ses sous-dossiers `generated` et `suggested` doivent exister. |
| `info`, `check`, `recalc`, `changelog`, `export`, `pv-compare` | `--project PROJECT` | Choisi par règle | Nom court du projet (`PROJECT.proj_short_name`), exact et sensible à la casse, pour les fichiers qui contiennent plusieurs projets. `changelog` l'applique aux deux fichiers, `pv-compare` à la mise à jour. |

Quand plusieurs options de Baseline de `check` sont données, la première qui existe l'emporte pour
chaque mise à jour : la Baseline dans le fichier, puis le fichier `--baseline`, puis les dates
planifiées, sinon aucune. La ligne de commande n'a pas d'option pour la base de valeur acquise. Elle
lit une Baseline sur la base par défaut. Les dates d'un fichier `--baseline` ou d'une Baseline
contenue dans un fichier sont donc les dates planifiées des activités de la Baseline.

#### Sortie

Le tableau suivant indique ce que chaque commande affiche sur la sortie standard et ce qu'elle
écrit.

| Commande | Affiche | Écrit |
|---|---|---|
| `app` | `You can now view your Streamlit app in your browser.` et `URL: http://localhost:<port>`. | Rien. |
| `info` | Une ligne par mise à jour : `data_date`, `source`, `forecast_finish`, `finish_shift_wd` (jours ouvrés par rapport à la ligne précédente, négatif quand la fin devient plus tardive), `activities`, `complete`, `critical`, `relationships`. Les avertissements de chargement vont sur stderr sous la forme `warning: ...`. | Rien. |
| `check` | Par mise à jour, une ligne de titre `<standard name> · <file> · data date YYYY-MM-DD · baseline <label or none>`, puis un tableau : `id`, `check`, `target`, `actual` (deux décimales, sans unité), `found`, `total`, `status`. Un contrôle auquel manque sa Baseline ou sa mise à jour antérieure affiche `NaN`, `<NA>`, `<NA>` et `n/a`. Un contrôle dont la population est vide affiche `NaN`, `0`, `0` et `n/a`. Avec `--expect` : la comparaison, puis `all counts match` ou, sur stderr, `<n> difference(s)`. | Avec `--out` : un CSV avec les colonnes `file`, `data_date`, `id`, `group`, `check`, `description`, `target`, `result`, `count`, `actual`, `found`, `total`, `status`, `note`, annoncé par `written <path>`. Avec `--flagged` : les fichiers CSV des éléments trouvés. |
| `standards` | Chaque standard intégré sous la forme `<id> <name> (<n> metrics)`, puis une ligne par contrôle avec son identifiant, son nom, sa cible et sa règle. | Avec `--template FILE` : le modèle, annoncé par `written <FILE>`. |
| `recalc` | Par fichier : une ligne de titre avec le nombre d'activités, la Data Date et la fin recalculée ; une ligne par champ, `<identical> / <compared> identical`, pour `early_end_date`, `early_start_date`, `free_float_hr_cnt`, `late_end_date`, `late_start_date` et `total_float_hr_cnt` ; un tableau des différences (`task_code`, `field`, `stored`, `computed`, `gap_hr`, `agree`) ; la ligne des affectations ; les avertissements. | Avec `--out` : un CSV des valeurs recalculées, et non de la comparaison, avec les colonnes `task_code`, `status_code`, `es`, `ef`, `remaining_start`, `ls`, `lf`, `tf_hr`, `ff_hr`, `resource_dependent`, `longest_path`, `rem_override_hr`, `task_name`. |
| `changelog` | Un tableau : `category`, `change`, `count`. Les catégories sont Project, Scope, Tasks, Durations, Relationships, Progress, Dates, Float, Constraints, Resources, Calendars et Options. | Avec `--out` : un CSV avec les colonnes `category`, `change`, `task_code`, `task_name`, `wbs_code`, `field`, `before`, `after`, `delta`, `unit`, annoncé par `written <file> (<n> changes)`. |
| `export` | Les quatre chemins écrits. | `dim_snapshot`, `fact_activity`, `fact_relationship` et `fact_assignment`, avec l'extension du format. Les tables ne sont pas anonymisées. |
| `crosscheck` | `agree` et `checks` par fichier, puis `<n> disagreement(s) out of <m> checks`. | Avec `--out` : un CSV de chaque comparaison. |
| `pv-compare` | `<update> at <data date> against <csv> (tolerance 0.01 h)` ; un tableau de totaux par groupe (`all`, `matched`, `only P6`, `only xerscope`, `in update, not in baseline`, `in baseline, not in update`) ; `<n> activities in gap; tables written to <folder>/`. | `10_pv_p6_totals.csv`, `10_pv_p6_by_schedule_pct.csv`, `10_pv_p6_gap_causes.csv`, `10_pv_p6_by_calendar.csv` et `10_pv_p6_activities_in_gap.csv`. Seul le dernier contient des codes et des noms d'activités. |
| `sample` | Les chemins écrits. | Un fichier par semaine à partir du 2026-08-31, nommé `PRJ-ALPHA_<data date>.xer`. Le contenu est identique à chaque exécution. |
| `ask-bench` | Les scores. | Rien. |
| `lexicon` | Les groupes des fichiers `*.toml` du dossier, un par ligne, puis `<n> group(s), <m> word(s) in <FOLDER>` ; une ligne `error: <file>: <reason>` pour un fichier qui ne se charge pas. Sans dossier : `0 group(s), 0 word(s)`, car aucun lexique n'est livré avec xerscope. | `lexicon build FOLDER --out LEXICON_FOLDER` lit les fichiers `.xer` de `FOLDER` (64 Mo chacun au plus) et écrit `generated/variants.toml` et `generated/report.txt` sous le dossier du lexique. |

La commande `app` n'ouvre aucun navigateur et reste au premier plan. Elle ne vérifie pas que ses
chemins existent, conserve une variable déjà définie dans l'environnement quand son option n'est pas
donnée, et n'accepte aucune autre option de Streamlit. La commande `crosscheck`, sans option et avec
`--cpm`, a besoin de Java et du composant optionnel (extra) installé avec
`uv sync --extra crosscheck`. Avec `--p6`, elle n'a besoin ni de l'un ni de l'autre. Avec `--cpm` et
sans la variable `XERSCOPE_MPXJ_CPM_JAR`, elle utilise le moteur de calcul de la version publiée de
MPXJ et affiche un avertissement. Pour le lexique d'une application hébergée, consultez
[docs/deploy.md](deploy.md#10-the-gantt-ask-field) (en anglais).

Les fichiers CSV sont en UTF-8 avec une marque d'ordre d'octets (BOM) et la virgule comme
séparateur. Les nombres ont quatre décimales et les dates se présentent sous la forme
`YYYY-MM-DD HH:MM`. Une cellule de texte qu'un tableur exécuterait comme une formule est
neutralisée. Un tableur peut lire le statut `n/a` comme une cellule vide. Le dossier d'un CSV
`--out` et celui de `standards --template FILE` doivent exister.

#### Colonnes de l'export Activities de P6

Le tableau suivant donne les champs de `pv-compare --column` et les en-têtes que la commande cherche
dans le CSV. Les en-têtes sont rapprochés sans tenir compte de la casse ni des espaces répétées. Le
nom du fichier doit se terminer par `.csv`, et le séparateur peut être une virgule, un point-virgule
ou une tabulation.

| Champ | En-tête attendu | Obligatoire |
|---|---|---|
| `task_code` | Activity ID | Oui |
| `pv_hr` | Planned Value Labor Units | Oui |
| `ev_hr` | Earned Value Labor Units | Oui |
| `schedule_pct` | Schedule % Complete | Oui |
| `bl_hr` | BL Project Labor Units, ou Budgeted Labor Units | Non |
| `status` | Activity Status | Non |
| `bl_start`, `bl_finish` | BL Project Start, BL Project Finish | Non |
| `start`, `finish` | Planned Start, Planned Finish | Non |

#### Série de démonstration

Le tableau suivant liste les événements introduits dans la série qu'écrit `sample`. Les semaines
sont comptées à partir de 0, le premier fichier.

| Semaine | Événement | Ce que cela montre |
|---|---|---|
| 0 | Aucun avancement ; P2030 est une activité de 60 jours | La Baseline ; une durée élevée |
| À partir de 2 | E1030 et P2030 avancent lentement | Glissement, érosion du Float |
| 4 | L'activité C3045 est ajoutée ; E1040 perd 3 jours | Un changement de périmètre ; un PPC inférieur à 100 % |
| 5 | La durée restante de P2030 augmente de 10 jours | Un Float négatif à travers la contrainte dure de X4050 |
| 6 | Le lien SS+10 de C3050 vers X4030 devient FS ; C3010 a une fin réelle postérieure à la Data Date ; E1020 perd 7 jours | Une modification de logique ; une date invalide ; un PPC inférieur à 100 % |
| Toujours | E1040 vers E1050 a un Lead (avance) de 3 jours ; K5040 n'a pas de successeur ; K5040 et E1050 n'ont pas de ressources ; `task_id` change dans chaque fichier | Un Lead, une extrémité ouverte, des ressources manquantes, le rapprochement par Activity ID |

#### Codes de sortie

Le tableau suivant donne les codes de sortie de toutes les commandes sauf `app`, qui renvoie le code
de sortie de Streamlit.

| Code | Signification | Cas |
|---|---|---|
| 0 | Terminé | Toute commande qui se termine normalement, y compris `recalc` avec des différences et `ask-bench` avec des scores faibles. |
| 1 | Un constat | `check --fail-on` (stderr : `<n> result(s) with status error/fail`) ; `check --expect` (stderr : `<n> difference(s)`) ; une différence de `crosscheck` ; un fichier de `lexicon` qui ne se charge pas. |
| 1 | Une commande qui ne peut pas faire son travail | `ask-bench` sans `--cases` ni `--self` (stderr) ; `lexicon build` quand `generated/` ou `suggested/` manque, quand aucun fichier ne passe son contrôle ou quand le fichier de suggestions n'est pas du TOML (stdout) ; `crosscheck` sans son extra (une trace d'appels Python). |
| 2 | Une entrée inutilisable | Un chemin manquant, un fichier tronqué ou endommagé, un standard inconnu : une ligne `xerscope: <reason>` sur stderr. Une erreur dans la commande elle-même : l'usage, puis une ligne `xerscope: error: ...` ou `xerscope <command>: error: ...`. `lexicon build` sans `FOLDER` ou `--out` : son usage sur stdout. |

### Application web

L'application est une page de navigateur avec une barre latérale, une navigation et une fenêtre pour
les fichiers.

#### Pages

Le tableau suivant liste les pages par groupe de navigation. La colonne Mise à jour indique quelle
mise à jour lit une page. *Partagée* désigne la liste **Update**, dont le choix se reporte sur les
autres pages qui en ont une. Elle démarre sur la dernière mise à jour.

| Groupe | Page | Mise à jour | Contenu |
|---|---|---|---|
| Schedule | **Overview** (page d'ouverture) | La dernière | **Forecast finish**, **Shift since first update**, **Tasks complete**, **Critical tasks** ; **Score by standard** (Score par standard), une carte par standard disponible, calculée en arrière-plan ; **Forecast finish by update** (Fin prévisionnelle par mise à jour) ; **Updates loaded** (Mises à jour chargées) ; **Limits** (Limites), affichée quand les fichiers contiennent quelque chose que xerscope lit différemment de P6. |
| Schedule | **Gantt & WBS** | Partagée | **Compare with** ; **Ask the schedule** ; **WBS** ; cartes **Focus**, **% complete** (% d'avancement), **Forecast finish**, **Labor hours** (Heures de main-d'œuvre), **Open critical** (Critiques ouvertes) ; filtres **Status**, **Float**, **Search**, **Task code (P6 activity code)** (Code de tâche, le code d'activité de P6) ; **Logic links** (désactivé), **Hide LOE** (activé), **Timescale** ; le graphique, regroupé par WBS, avec les colonnes **Activity / WBS**, **% complete**, **Float (wd)** et les boutons **Collapse all** (Tout replier), **Expand all** (Tout déplier), **Level** (Niveau) ; **Task** ; la carte de l'activité et **History across updates** ; **Population, step by step** ; **Table view**. |
| Analysis | **Schedule health** | Partagée | **Standard** (démarre sur P6 Check Schedule), **Failed checks only** (Contrôles en échec uniquement) ; cartes de score et de décompte ; **Results** ; **Show the sets of** (Afficher les ensembles de) ; **Detail by check** avec **Expand all** ; **Trend across updates** ; **Compare with a P6 Check Schedule report** ; **Use your own standard**. |
| Analysis | **Audit** | Partagée | **Standard**, **Check** ; **Settings for this audit** (**Rule parameters**, **Target**, **Reset**) ; **Calculation** (Calcul) ; **Sets** ; **Calculation sheet: population, fields, sources, worked example** (standard P6 uniquement) ; **Settings: how to change this check for good**. |
| Analysis | **Changelog** | **From (older)**, **To (newer)** | Boutons **Previous** (Précédente), **4 back** (4 en arrière), **First** (Première) ; six cartes ; **Changes by category** (Modifications par catégorie) ; **All changes** avec **Category**, **Change**, **Search** ; **Every week, side by side** (Chaque semaine, côte à côte). |
| Analysis | **Delay analysis** | Partagée | **Finish before replanning**, **Finish shown**, **Longest path float**, **Tasks matched** ; **Step by step** ; les révisions à l'intérieur et au-delà d'un horizon à court terme (lookahead) de 6 semaines ; **Longest path** ; **Every update**. La Baseline n'est pas lue. |
| Analysis | **Earned value** | Partagée | **P6 view: the file's baseline** (désactivé) ; les cartes ; les chiffres d'Earned Schedule ; **S-curve** avec **Show as % of BAC** (désactivé) ; **Performance indices by update** (Indices de performance par mise à jour) ; **How it is calculated** (Mode de calcul) ; **The weeks of the 4 weeks' figures** (Les semaines des chiffres sur 4 semaines) ; **Earned hours by task**. |
| Analysis | **Milestone trend** | La dernière | **Milestones and key tasks (up to 6)**, **Finish milestones**, **Critical milestones**, **Clear** ; le graphique ; **Slippage** ; **Data** (Données). |
| Analysis | **PPC & progress** (titre : **PPC & weekly progress**) | **Week ending** | **PPC target (%)** (80), **Include commitments late at W−1** (cochée) ; **Percent plan complete by week** (PPC par semaine) ; **Lookahead reliability** (Fiabilité du lookahead) ; **Commitments** ; **Progress by WBS** (Avancement par WBS) ; **Milestones committed** ; **Unplanned work** ; **Progress by task** (Avancement par tâche) ; **Start and finish variance**. |
| Data | **Export for Power BI** | La dernière | Les quatre tables avec leurs lignes et leurs colonnes ; **Format** ; le téléchargement ; **Preview fact_activity** (Aperçu de fact_activity) ; **Anonymized XER extract**. |
| Data | **Debug** | Partagée | Ce que xerscope a lu dans le fichier et ce qu'il a décidé, en 14 blocs numérotés, et **Diagnostic**. Masquée quand les données sont verrouillées. |

Les éléments suivants figurent sur chaque page :

- Sous le titre, une ligne qui est aussi un bouton : `<project codes> · status date <date> · BL
  <where> (<rule>) · EV <basis> · costs on|off · N files · K projects`. Un clic sur cette ligne
  ouvre la fenêtre **Files and baseline**. La règle est l'une des suivantes : « the window's
  choice », « assigned in this update », « origin of the series » et « P6 view: this update's
  baseline ».
- Un tableau de plus de 10 lignes dispose d'un élément **Filter columns** (Filtrer les colonnes). Un
  filtre de texte conserve les lignes qui contiennent le texte. Un filtre numérique lit `<0`, `>=5`,
  `=3` ou `-10..0`. Un filtre de date lit `>2026-11-01`, `2026-11` ou `2026-11..2026-12`.
- Un tableau ou un graphique dispose d'un élément **How to read** (Comment lire). Une ligne
  sélectionnée dans un tableau d'activités donne un bouton qui ouvre l'activité dans le Gantt. Une
  valeur manquante s'écrit `–`.
- Les tableaux ne peuvent être ni exportés ni copiés par leur propre barre d'outils. Pour en sortir
  les données, utilisez les boutons de téléchargement.

Les blocs de la page **Debug** s'affichent dans cet ordre :

- **1 · Scheduling options (SCHEDOPTIONS, PROJECT)** (Options de calcul du planning)
- **2 · Expected finish**
- **3 · INT-01 / INT-03 differences**
- **4 · Check Schedule parameters applied (P6 standard)** (Paramètres Check Schedule appliqués,
  standard P6)
- **5 · Baseline and calendars**
- **6 · Load warnings** (Avertissements de chargement)
- **7 · Costs in the file (TASKRSRC, PROJCOST)** (Coûts dans le fichier)
- **8 · Earned Value settings of the WBS (PROJWBS)** (Réglages Earned Value du WBS)
- **9 · XER tables and planned value labor units** (Tables XER et unités de main-d'œuvre de la
  valeur planifiée)
- **10 · PV against a P6 export**
- **11 · Project settings (PROJECT, TASK.complete_pct_type)** (Réglages du projet)
- **13 · Calendar detail (CALENDAR.clndr_data, hours per time period)** (Détail des calendriers,
  heures par période)
- **12 · App runtime (where the theme and fonts come from)** (Exécution de l'application : d'où
  viennent le thème et les polices)
- **14 · Ask vocabulary (variants generated per source column)** (Vocabulaire du champ Ask :
  variantes générées par colonne source)

Le bloc 12 n'est pas affiché quand les données sont verrouillées.

#### Téléchargements

Le tableau suivant liste les téléchargements. `<date>` est la Data Date au format `YYYY-MM-DD`.
Quand **Anonymous exports** est activé, un téléchargement vient après
**Prepare anonymized downloads** et son libellé se termine par « · anonymized ».

| Page | Bouton | Fichier |
|---|---|---|
| **Gantt & WBS**, **Table view** | **Download CSV** | `gantt_<date>.csv` |
| **Schedule health** | **Summary (CSV)** | `<standard id>_<date>_summary.csv` |
| **Schedule health** | **All flagged items (CSV)** | `<standard id>_<date>_flagged.csv` |
| **Schedule health** | **Prepare all sets** (Préparer tous les ensembles), puis **All sets (CSV)** ou **All sets (ZIP)** | `<standard id>_<date>_sets.csv` ou `.zip` |
| **Schedule health**, panneau d'un contrôle | **Download list (CSV)** | `<check id>_<date>.csv` |
| **Schedule health** et **Audit**, un ensemble | **Download CSV** | `<check id>_<date>_counted.csv`, `_not_counted.csv`, `_excluded.csv` ; sur **Audit**, également `_removed.csv` |
| **Schedule health** | **Download the template** (Télécharger le modèle) | `my-standard.toml`, jamais anonymisé |
| **Changelog** | **Download changelog (CSV)** | `changelog_<from date>_<to date>.csv` |
| **Delay analysis** | **Download steps (CSV)** (Télécharger les étapes) | `half_step_<from date>_<to date>.csv` |
| **Delay analysis** | **Download series (CSV)** | `half_step_series.csv` |
| **Delay analysis** | **Download longest path (CSV)** | `longest_path_churn.csv` |
| **Earned value** | **Download CSV** | `earned_<date>.csv` |
| **Earned value** | **Download deleted tasks (CSV)** (Télécharger les tâches supprimées) | `earned_deleted_<date>.csv` |
| **PPC & progress** | **Download CSV** | `progress_<date>.csv` |
| **PPC & progress** | **Download variances (CSV)** (Télécharger les écarts) | `variances_<date>.csv` |
| **Export for Power BI** | **Download PARQUET tables (.zip)** ou **Download CSV tables (.zip)** | `<project code>_xerscope_<format>.zip` ; anonymisé : `xerscope_<format>.zip` |
| **Export for Power BI** | **Build anonymized extract**, puis **Download anonymized XER (.zip)** | `xerscope_anonymised_xer.zip`, toujours anonymisé |
| **Debug** | **Build calendar detail** (Construire le détail des calendriers), puis **Download calendar detail (.zip)** | `xerscope_calendars_<date>.zip` |
| **Debug** | **Build diagnostic** (Construire le diagnostic), puis **Download diagnostic (.zip)** | `xerscope_diagnostic.zip` |

Dans un téléchargement anonymisé, les Task ID, les codes WBS et les identifiants de projet sont
renommés, et les noms sont reconstruits à partir des nouveaux codes. Les colonnes que xerscope écrit
lui-même sont conservées, et tout autre texte du fichier est vidé. Les dates, les durées, les unités
et la logique sont conservées. Les coûts sont écrits à 0. Les nouveaux codes sont les mêmes dans
tous les téléchargements d'une session et changent avec la session.

#### Barre latérale

Le tableau suivant liste la barre latérale de haut en bas. Les lignes de **Baseline** à **Costs**
existent une fois qu'une série est lue.

| Élément | Type | Valeur par défaut | Effet |
|---|---|---|---|
| **Files · none read**, puis **Files · N files · K projects** | Bouton | Sans objet | Ouvre la fenêtre **Files and baseline** sur sa section **Files**. Son info-bulle donne les projets lus ainsi que la première et la dernière Data Date. |
| **Reading the updates · n/N** (Lecture des mises à jour) | Progression | Sans objet | Affiché pendant que plusieurs fichiers sont lus en arrière-plan. |
| Erreurs de chargement | Messages | Sans objet | Une par fichier qui n'a pas pu être lu. Les autres fichiers se chargent. |
| **Baseline · NAME** | Bouton | Sans objet | Ouvre la fenêtre sur sa section **Baseline**. Le nom est « in each file », « planned dates », « none », « update » avec la Data Date de la mise à jour, le nom du fichier de Baseline, ou « file missing ». |
| Lignes de Baseline | Légendes et avertissements | Sans objet | Le libellé de la Baseline, ses activités et ses heures de main-d'œuvre, et les avertissements sur les Baselines. |
| **Anonymous exports** | Bouton bascule | Activé | Anonymise les téléchargements. Les pages affichent toujours les données des fichiers eux-mêmes. |
| **Costs** | Case à cocher | Décochée | Affiche les chiffres de coût sur **Earned value**. |
| **Glossary** (Glossaire) | Volet dépliable | Fermé | Chaque acronyme des pages avec son nom complet, sa définition et sa source (37 entrées). |

#### Fenêtre Files and baseline

Le tableau suivant liste les éléments de la fenêtre. Rien ne s'applique avant **Done**, et fermer la
fenêtre d'une autre façon abandonne toutes les modifications. Pour lister les fichiers, la fenêtre
ne lit que le projet, la Data Date et le nombre d'activités de chaque fichier.

| Section | Élément | Valeur par défaut | Effet |
|---|---|---|---|
| Files | **Upload .xer files** | Vide | Accepte plusieurs fichiers `.xer`, de 200 Mo chacun au plus. Non affiché quand les données sont verrouillées. |
| Files | **…or read a folder** | Le dossier `--data` | Liste les fichiers `.xer` du dossier. Le dossier doit se trouver sous la racine des dossiers. Non affiché quand les données sont verrouillées. |
| Files | Une case à cocher par fichier : `<file> — <project> · <dd Mon YYYY> · N tasks` | Décochée ; une fenêtre rouverte sélectionne le dernier choix validé | Sélectionne le fichier. Le libellé ajoute ` · K projects` pour un fichier de plusieurs projets, ` — same date as <file>` pour un doublon, ou indique `<file> — unreadable`. |
| Files | **Select all**, **Clear** | Sans objet | Sélectionne tous les fichiers lisibles sauf les doublons d'une même Data Date ; efface tout. Le compteur indique **N of M ticked**. |
| Files | **Project read from each file · why** | Le projet choisi par règle | Une ligne par fichier, et une liste de projets pour un fichier qui en contient plusieurs. |
| Files | **Selection details** (Détails de la sélection) | Fermé | Un tableau : fichier, projet, règle qui l'a retenu, Data Date et sa source, Baseline dans le fichier, activités. |
| Baseline | **Baseline (BL)** | Voir la liste qui suit ce tableau | La Baseline de la série. |
| Baseline | **Earned value basis** | **Budgeted · planned dates** (Budgété · dates planifiées) | Propose aussi **Budgeted · current dates** (Budgété · dates actuelles) et **At completion · current dates** (À l'achèvement · dates actuelles). Fixe les heures et les dates de Baseline de la valeur planifiée et de la valeur acquise, ainsi que les dates d'une Baseline séparée : ses dates planifiées, ou ses dates actuelles avec les deux options « current dates ». Un résultat qui lit une Baseline est recalculé quand la base change. |
| Baseline | **Link renumbered tasks by GUID** | Décochée | Mesure une activité renumérotée par rapport à l'activité de la Baseline qui porte son GUID. |
| Baseline | **When a file has no baseline** | **None** | Affiché avec **Baseline in each file (P6 Project Baseline)**. Propose les autres entrées de **Baseline (BL)**. |
| Baseline | **Baseline of FILE (undecided)** (Baseline de FILE, non tranchée) | Aucun choix | Pour une mise à jour dont l'export ne tranche pas la Baseline : **None: not measured** (Aucune : non mesurée), **Baseline ID, held by version ID** (Baseline ID, portée par la version ID) ou **The fallback above** (Le repli ci-dessus). |
| Baseline | **Baseline file in the folder** | **(none)** (aucun), ou l'unique fichier `.xml` du dossier | Les fichiers `.xml` situés à côté des mises à jour et les fichiers `.xer` et `.xml` du sous-dossier `baselines`. |
| Baseline | **Baseline .xer, or a P6 XML export with its baselines** (.xer de Baseline, ou export P6 XML avec ses Baselines) | Vide | Accepte un fichier `.xer` ou `.xml`. Non affiché quand les données sont verrouillées. |
| Baseline | **Project read from the baseline file** (Projet lu dans le fichier de Baseline) | Le projet choisi par règle | Pour un XER de Baseline de plusieurs projets. |
| Les deux | **Done** | Sans objet | Applique les choix. Désactivé tant que deux téléversements portent le même nom. |

**Baseline (BL)** propose les entrées suivantes, dans cet ordre :

- **Baseline in each file (P6 Project Baseline)**, uniquement quand un fichier contient une Baseline
  utilisable ou qu'un export P6 XML est disponible ;
- **Separate baseline file** ;
- chaque mise à jour chargée sous la forme `<YYYY-MM-DD> · <file name>` ;
- **Planned dates in each file (target_*)** ;
- **None**.

La liste démarre sur **Baseline in each file (P6 Project Baseline)** quand un fichier contient une
Baseline utilisable et qu'aucun fichier de Baseline n'a été désigné au démarrage. Elle démarre sur
**Separate baseline file** quand un fichier a été désigné, et sinon sur la première mise à jour.
Après **Done** sur un nouveau choix de fichiers, la fenêtre se rouvre d'elle-même sur sa section
**Baseline**, et les pages attendent un second **Done**. Un changement ultérieur de Baseline demande
un seul **Done**.

#### Raccourcis clavier

Le tableau suivant liste les raccourcis que déclare l'application.

| Touche | Où | Effet |
|---|---|---|
| `F` | Toute page | Ouvre la fenêtre sur sa section **Files**. |
| `B` | Toute page, une fois qu'une série est lue | Ouvre la fenêtre sur sa section **Baseline**. |
| `Ctrl+Enter` (Ctrl+Entrée) | Fenêtre **Files and baseline** | **Done**. |
| `Esc` (Échap) | Fenêtre **Files and baseline** | Ferme la fenêtre sans appliquer. |

### Variables d'environnement

Le tableau suivant liste les variables que vous pouvez définir avant de démarrer xerscope. Une
variable de type oui ou non est activée pour `1`, `true` ou `yes`, quelle que soit la casse, et
désactivée pour toute autre valeur.

| Variable | Valeur par défaut | Effet |
|---|---|---|
| `XERSCOPE_DATA` | Non définie | Dossier des fichiers `.xer` hebdomadaires sur lequel s'ouvre la fenêtre **Files and baseline**. Définie par `app --data`. |
| `XERSCOPE_BASELINE` | Non définie | `.xer` de Baseline, ou export P6 XML contenant les Baselines. Définie par `app --baseline`. |
| `XERSCOPE_STANDARDS` | Non définie | Dossier de fichiers `.toml` de standards, relu à chaque exécution d'une page. Un fichier qui réutilise l'identifiant d'un standard intégré le remplace. Un dossier qui n'existe pas est ignoré sans message. Définie par `app --standards`. |
| `XERSCOPE_FOLDER_ROOT` | `XERSCOPE_DATA`, sinon votre répertoire personnel | Le dossier sous lequel doit se trouver un chemin saisi dans la fenêtre **Files and baseline**. La valeur `/` n'accepte aucun dossier autre que `/`. |
| `XERSCOPE_DATA_LOCKED` | Désactivée | Oui ou non. Activée : pas de champ de dossier, pas de téléversement de planning ni de Baseline, et pas de page **Debug**. Seuls les fichiers de `XERSCOPE_DATA` sont proposés. |
| `XERSCOPE_DEBUG_PAGE` | Désactivée | Oui ou non. Activée : la page **Debug** est affichée même quand les données sont verrouillées. La page décrit la lecture de chaque fichier à quiconque peut ouvrir l'application. |
| `XERSCOPE_LOAD_WORKERS` | Un processus par cœur, 2 au plus | Nombre de fichiers lus en même temps. `1` lit dans le fil d'exécution appelant. Une valeur invalide est ignorée. |
| `XERSCOPE_LEXICON` | Non définie | Dossier du lexique du champ **Ask the schedule**, avec les sous-dossiers `curated`, `generated` et `suggested`. |
| `XERSCOPE_SYNC_LOAD` | Désactivée | Oui ou non. Activée : les fichiers sont lus et les scores calculés pendant l'exécution de la page et non en arrière-plan. **Overview** a alors un bouton **Compute scores** (Calculer les scores). Destinée aux tests automatisés. |
| `XERSCOPE_MPXJ_CPM_JAR` | Non définie | Chemin de la version du moteur de calcul de MPXJ qu'utilise `crosscheck --cpm`. |

Une autre variable, `XERSCOPE_STRICT_READINGS`, ne sert qu'aux tests automatisés.

### Standards

Le tableau suivant liste les standards intégrés.

| Identifiant | Nom | Contrôles | Groupes |
|---|---|---|---|
| `P6` | P6 Check Schedule | 18 lignes pour 17 contrôles | Inflexibility and Inefficiency, Inaccuracy, Lateness |
| `DCMA` | DCMA 14-Point | 14 | Aucun |
| `DECM` | DCMA DECM v8.0 (schedule) | 16 | Logic ; Constraints and float ; Critical path ; Baseline, forecast and actual dates |
| `INTEGRITY` | Integrity | 8 (INT-01 à INT-08) | Aucun |

Les fiches de calcul n'existent que pour le standard P6. Trois contrôles DECM (06A504a, 06A504b et
06A506c) comparent chaque mise à jour avec la dernière mise à jour datée d'au moins 28 jours avant
elle. Les contrôles qui ont besoin d'une Baseline sont P6-12 et P6-13, DCMA-08, DCMA-11 et DCMA-14,
ainsi que 06A501a. DCMA-13 affiche aussi `n/a` quand le projet n'a ni date Must Finish By ni
Baseline.

Le tableau suivant liste les contrôles du standard P6 avec les cibles du fichier intégré.

| Identifiant | Nom | Groupe | Cible |
|---|---|---|---|
| P6-01 | Logic | Inflexibility and Inefficiency | `< 5%` |
| P6-02 | Hard Constraints | Inflexibility and Inefficiency | `< 1%` |
| P6-03 | Soft Constraints | Inflexibility and Inefficiency | `< 5%` |
| P6-04 | Large Durations | Inflexibility and Inefficiency | `< 5%` |
| P6-05 | Long Lags | Inflexibility and Inefficiency | `< 5%` |
| P6-06 | Large Float | Inflexibility and Inefficiency | `< 1%` |
| P6-07 | Relationship Types | Inflexibility and Inefficiency | `> 90%` |
| P6-08 | Positive Lags | Inflexibility and Inefficiency | `< 5%` |
| P6-09 | Negative Lags | Inaccuracy | `< 1%` |
| P6-10a | Invalid Progress Before Data Date | Inaccuracy | `< 1%` |
| P6-10b | Invalid Progress After Data Date | Inaccuracy | `< 1%` |
| P6-11 | Resource / Cost | Inaccuracy | `< 1%` |
| P6-12 | Late Activities | Lateness | `< 5%` |
| P6-13 | BEI | Lateness | `> 0.95` |
| P6-14 | Negative Float | Lateness | `< 1%` |
| P6-15 | Out of Sequence | Inaccuracy | `< 2%` |
| P6-16 | Dangling Start Activities | Inaccuracy | `<= 0%` |
| P6-17 | Dangling Finish Activities | Inaccuracy | `<= 0%` |

Le fichier intégré, `src/xerscope/standards/p6.toml`, attribue P6-01 à P6-14 à l'aide de P6
Professional 24. La limite de P6-04, P6-05 et P6-06 est de 352 heures dans ce fichier. P6-10a et
P6-10b forment un seul critère du score. L'application écrit `≤` et `≥` là où la ligne de commande
affiche `<=` et `>=`.

#### Fichier de standard

Le tableau suivant décrit le fichier TOML d'un standard. `xerscope standards --template` affiche un
exemple commenté de 14 contrôles.

| Table | Clé | Obligatoire | Valeurs |
|---|---|---|---|
| `[standard]` | `id` | Oui | Lettres, chiffres, `.`, `_` et `-`. Un fichier téléversé ne peut pas réutiliser l'identifiant d'un standard intégré. |
| `[standard]` | `name` | Oui | Texte, affiché dans les listes et les titres. |
| `[standard]` | `description`, `source` | Non | Texte. |
| `[[metric]]` | `id` | Oui | Lettres, chiffres, `.`, `_` et `-`. |
| `[[metric]]` | `name` | Oui | Texte. |
| `[[metric]]` | `rule` | Oui | L'une des règles que liste `xerscope standards --rules`. |
| `[[metric]]` | `target` | Non | `<= 5%`, `>= 0.95`, `== 0`, `pass`, `info`, ou aucune. Les opérateurs sont `<`, `<=`, `>`, `>=` et `==`. |
| `[[metric]]` | `unit` | Non | `%`, `count`, `ratio` ou `pass/fail`. Une unité autre que celle de la règle n'est acceptée qu'entre `%` et `count`. |
| `[[metric]]` | `params` | Non | Les paramètres de la règle. |
| `[[metric]]` | `description`, `source`, `group`, `item` | Non | Texte. Les contrôles de même `item` forment un seul critère du score. |

Douze règles sont écrites pour votre propre standard, chacune avec ses paramètres :
`missing_logic`, `dangling`, `lag`, `relationship_type`, `constraints`, `float`, `duration`,
`invalid_dates`, `on_data_date`, `no_resource`, `late_vs_baseline` et `bei`. Seize règles des
standards intégrés prennent aussi des paramètres, par exemple `p6_04_large_durations`
(`limit_hours`).

### Valeurs fixes et tailles

Le tableau suivant liste des valeurs fixées dans le code. Aucune option, aucune variable ni aucun
élément de l'interface ne les modifie, sauf là où le tableau l'indique.

| Valeur | Réglage | Portée |
|---|---|---|
| Heures par jour quand un calendrier n'en donne pas | 8 | Toute conversion en jours ouvrés |
| Valeur de Total Float à laquelle ou sous laquelle une activité est critique | 0 jour ouvré | Quand le projet ne définit rien d'autre |
| Valeur de Total Float à laquelle ou sous laquelle une activité est quasi critique | 10 jours ouvrés | Couleurs et filtres du Gantt |
| Nombre de lignes à partir duquel un tableau reçoit des filtres de colonnes | Plus de 10 | Tous les tableaux de l'application |
| Lookahead | 6 semaines | Page **Delay analysis** |
| Cible de PPC | 80 % | Page **PPC & progress**, où elle peut être modifiée |
| Taille d'un fichier téléversé | 200 Mo au plus | Les champs de téléversement |
| Processus qui lisent des fichiers | 2 au plus | L'application |
| Longueur d'une phrase | 300 caractères au plus | Champ **Ask the schedule** |
| Jalons ou activités sélectionnés | 6 au plus | Page **Milestone trend** |

## Dépannage

Le tableau suivant liste des symptômes, de la ligne de commande à l'application. Les messages sont
cités tels que l'outil les affiche. Une partie entre chevrons représente un nom ou un nombre.

| Symptôme | Cause | Que faire |
|---|---|---|
| `xerscope: <path>: no such file or folder`, ou `xerscope: [Errno 2] No such file or directory: '<path>'` ; code de sortie 2 | Un chemin donné à une commande n'existe pas. La commande `app` ne vérifie pas ses chemins et démarre quand même. | Corrigez le chemin. |
| `xerscope: no .xer file in <folder>` ; code de sortie 2 | Le dossier ne contient aucun fichier dont le nom se termine par `.xer`. Les sous-dossiers ne sont pas lus. | Indiquez le dossier qui contient les exports. |
| `<file>: incomplete file, no %E end line (still being copied, or cut short)` | L'export n'est pas complet. | Attendez la fin de la copie, ou exportez de nouveau le fichier. |
| `<file>: not an XER file (no ERMHDR header, no tables)` | Le fichier n'est pas un export XER de P6. | Fournissez un fichier `.xer` exporté par P6. |
| `xerscope: unknown standard '<name>': use DCMA, DECM, INTEGRITY, P6 or a .toml file` | `--standard` ne nomme ni un standard intégré ni un fichier existant. | Utilisez l'un des quatre identifiants, ou le chemin de votre fichier `.toml`. |
| `several files per status date, keep one per date: <date>: <files>` (dans l'application, le message se termine par `Untick the others.`) | Deux fichiers ont la même Data Date. | Conservez un seul fichier par Data Date. |
| `<file>: project '<name>' not found (has [...])` | `--project` ne correspond à aucun nom court de projet du fichier. La comparaison est sensible à la casse. | Utilisez l'un des noms que liste le message. |
| `xerscope: --baseline-in-file needs distinct file names` | Deux fichiers de deux dossiers portent le même nom. | Renommez-en un, ou contrôlez les dossiers un par un. |
| `xerscope --version` affiche l'usage et une erreur | Il n'existe pas d'option `--version`. | La version est 0.1.0. |
| `Port 8501 is not available` ; code de sortie 1 | Un autre programme, ou un autre xerscope, utilise le port. | Arrêtez-le, ou démarrez l'application avec `--port` et un autre numéro. |
| Après `Ctrl+C`, une trace d'appels Python `KeyboardInterrupt` suit `Stopping...` | La commande `app` n'intercepte pas l'interruption. | Rien : l'application est arrêtée. |
| La fenêtre **Files and baseline** affiche **Folder not found** (Dossier introuvable) | Le dossier n'existe pas, ou vous avez saisi un chemin relatif. Un chemin relatif est lu à partir du dossier de l'application elle-même, si bien que le chemin `data/sample` que suggère le message d'ouverture est introuvable. | Saisissez un chemin absolu ou un chemin qui commence par `~`. |
| `Folder outside <root>: set XERSCOPE_FOLDER_ROOT to read another tree` | Le dossier n'est pas sous la racine des dossiers : le dossier `--data` quand il est donné, sinon votre répertoire personnel. | Démarrez l'application avec `--data` sur ce dossier, ou définissez `XERSCOPE_FOLDER_ROOT`. Ne lui donnez pas la valeur `/`. |
| La fenêtre **Files and baseline** affiche **No .xer file in that folder** (Aucun fichier .xer dans ce dossier) | Le dossier ne contient directement aucun fichier `.xer`. | Saisissez le dossier qui contient les exports. |
| Un fichier indique `<file> — unreadable` dans la fenêtre **Files and baseline** | Le fichier ne peut pas être lu comme un XER. Son info-bulle en donne la raison. | Exportez de nouveau le fichier. **Select all** l'ignore. |
| `<file>: no status date (PROJECT.last_recalc_date); the file is skipped` | Le fichier ne porte pas de Data Date. | Exportez de nouveau le projet une fois qu'il a une Data Date. |
| `N files named <name>: untick all but one` ; **Done** est désactivé | Deux fichiers téléversés portent le même nom. | Décochez-les tous sauf un. |
| Chaque page affiche `N files · K projects read. Choose the baseline in the window (...), then Done` | Les fichiers sont lus et la Baseline n'est pas encore confirmée. | Cliquez sur la ligne **Baseline** de la barre latérale, puis sur **Done**. |
| La barre latérale affiche **Baseline · file missing** (Baseline · fichier manquant) | Le chemin `--baseline` n'existe pas. | Redémarrez avec le bon chemin, ou choisissez une autre Baseline dans la fenêtre. |
| `Baseline not read: <file>: N baselines and none named as the Project Baseline: ...` | L'export P6 XML contient plusieurs Baselines et n'en désigne aucune comme Project Baseline. Sur la ligne de commande, la même raison s'accompagne du code de sortie 2. | Dans l'application, choisissez **Baseline in each file (P6 Project Baseline)** : chaque mise à jour est alors rapprochée de la Baseline qu'elle nomme. |
| `Baseline not read: <file>: not an XER file (no ERMHDR header, no tables)` | Un fichier `.xml` du dossier n'est pas un export P6 XML. | Choisissez un autre fichier dans **Baseline file in the folder**. |
| `<xml>: no baseline in this P6 XML export (tick them under Baselines to Export)` | L'export a été fait sans ses Baselines. | Exportez de nouveau depuis P6 avec les Baselines. |
| Des contrôles affichent `n/a` avec la note `needs a baseline` ; **Earned value** indique « Choose a baseline from the sidebar's Baseline line (...) » | Aucune Baseline n'est choisie, ou le fichier de la mise à jour n'en a pas. | Choisissez une Baseline dans la fenêtre, ou donnez `--baseline`, `--planned-baseline` ou `--baseline-in-file` à `check`. |
| Trois contrôles DECM affichent `n/a` avec la note `needs an update 28 days older` | 06A504a, 06A504b et 06A506c ont besoin d'une mise à jour datée d'au moins 28 jours avant celle qui est contrôlée. | Chargez les mises à jour antérieures. Sur une série hebdomadaire, les contrôles sont calculés à partir de la cinquième mise à jour. |
| Une page indique « Load at least two XER files to compare them. » ou une phrase semblable | **Changelog**, **Delay analysis**, **PPC & progress** et **Milestone trend** comparent des mises à jour. | Chargez au moins deux mises à jour. |
| `N task(s) renumbered since the baseline: turn on Link by GUID in the Baseline window. ...` | Des Activity ID ont changé depuis la Baseline. | Dans la section **Baseline** de la fenêtre **Files and baseline**, cochez **Link renumbered tasks by GUID**. |
| « The word « x » is in neither this file nor the lexicon. » | Le champ **Ask the schedule** ne connaît pas le mot. | Utilisez les mots du fichier, ou cliquez sur un libellé sous **Did you mean**. |
| Un bouton de téléchargement est remplacé par une erreur `<what> not written: it still holds values of ...` | L'outil d'anonymisation a trouvé des valeurs d'origine restées dans la sortie et a refusé de l'écrire. | Rien n'est écrit. Pour télécharger les données avec leurs propres noms, désactivez **Anonymous exports**. |
| La page garde une apparence plus ancienne après une mise à jour de xerscope (autres polices) | Selon le texte de l'application elle-même : une ancienne copie encore en cours d'exécution, ou une page qui n'a pas chargé le thème. | Arrêtez l'application et redémarrez-la avec `uv run xerscope app` : elle exécute le code du dossier source tel qu'il est. Puis rechargez la page en contournant le cache (`Ctrl+Shift+R`, soit Ctrl+Maj+R). Pour l'image locale, exécutez `docker compose up -d --build`. Sur la page **Debug**, le bloc 12 montre ce que l'application en cours d'exécution a lu : `Config read` doit indiquer `yes`. |
| `check --expect` s'arrête avec `<csv>: columns total missing` ou `<csv>: add a 'file' column, N files were checked` | Il manque une colonne au CSV. | Fournissez les colonnes `id`, `found` et `total`, ainsi que `file` quand plusieurs fichiers sont contrôlés. |
| `xerscope: pv-compare: give --baseline BL.xer or --planned-baseline` | `pv-compare` a besoin d'une Baseline. | Ajoutez l'une des deux options. |
| `<csv>: column(s) not found for pv_hr; headers read: ... Name them with --column FIELD=HEADER.` | L'export P6 nomme une colonne autrement. | Ajoutez `--column` avec le champ et l'en-tête de votre export. |
| `<file>: invalid TOML: ...`, `unknown rule '<name>'`, `needs a [standard] table with id and name`, ou `id 'P6' is a built-in standard's; give yours another id` | Le fichier de standard comporte une faute. | Corrigez le fichier. `uv run xerscope standards --rules` liste les noms des règles. |
| `crosscheck` se termine par une trace d'appels et `RuntimeError: crosscheck needs the optional extra: uv sync --extra crosscheck` | L'extra optionnel n'est pas installé. | Exécutez `uv sync --extra crosscheck`. Java doit être dans `PATH` : les tests automatisés utilisent les JDK 21 et 25. |
| `warning: MPXJ's released scheduler predates its out-of-sequence fix (#972); ...` | `crosscheck --cpm` s'exécute sans la version épinglée du moteur de calcul. | Construisez-la avec `tests/reference/mpxj_cpm.py` et donnez son chemin à `XERSCOPE_MPXJ_CPM_JAR`. |
| Une exécution des tests ignore des tests avec `mpxj missing: no Java runtime on PATH` | Les tests qui utilisent MPXJ ont besoin de Java. | Installez un JDK (21 ou version ultérieure) si vous avez besoin de ces tests. |
| Dans l'image Docker locale, un `.xer` de Baseline placé dans `exports/` est listé comme une mise à jour | Tous les fichiers `.xer` du dossier sont listés. | Laissez-le non sélectionné, ou placez-le dans `exports/baselines/`. |

## Limites

Cette partie indique ce que xerscope ne modélise pas et ce qui n'est pas établi. Les résultats
mesurés figurent dans la [section Validation du README](../README.md#validation) (en anglais), et
les travaux ouverts dans [docs/backlog.md](backlog.md) (en anglais).

### Ce que xerscope ne modélise pas

Le recalcul ne modélise ni le nivellement des ressources, ni les Multiple Float Paths (chemins de
Float multiples ; les dates et le Float ne sont pas affectés, mais les numéros de Float Path ne sont
pas calculés), ni les relations vers des projets qui ne sont pas dans le fichier. Un fichier qui les
utilise peut présenter des différences qui ne sont pas des erreurs du fichier. `recalc` et la page
**Debug** avertissent quand un fichier semble nivelé. Une période de travail qui franchit minuit ne
compte aucun travail, avec une note.

Que le résultat soit égal à celui de P6, le code ne le prouve pas. Cette égalité est mesurée par
rapport à des plannings calculés par P6 Professional 23.12.1, avec un plancher par jeu de référence
que les tests imposent. Le plancher le plus bas est de 98,2 % des valeurs enregistrées reproduites.
Pour les conventions qu'aucun fichier de référence ne tranche, consultez
[docs/cpm.md](cpm.md#conventions-no-reference-file-settles) (en anglais).

La valeur acquise a les limites suivantes, détaillées dans
[docs/formulas.md](formulas.md#7-known-limits) (en anglais) :

- Les courbes de ressources et les valeurs manuelles des périodes futures ne sont pas modélisées :
  la valeur planifiée est répartie linéairement.
- La technique de valeur acquise « WBS milestones » et les techniques inconnues ne sont pas
  modélisées : le pourcentage d'avancement de l'activité est utilisé, et la page liste les
  activités.
- La technique ETC de chaque WBS est indiquée, non appliquée : l'ETC est égal aux heures restantes.
- Le coût réel, un CPI de coût et un EAC de coût ne sont pas modélisés. Les chiffres de coût
  utilisent les valeurs budgétées quelle que soit la base de valeur acquise.

Le code marque les lectures suivantes de P6 Check Schedule comme n'étant tranchées par aucune
source :

- une contrainte dure secondaire (P6-02) ;
- un lien externe d'un seul côté (P6-01) ;
- les relations FF et SF (P6-15) ;
- les activités terminées et les liens vers d'autres projets dans les contrôles Dangling (P6-16,
  P6-17).

Une Baseline lue dans un export P6 XML ne porte pas de GUID. Les activités renumérotées ne peuvent
donc pas lui être liées.

xerscope n'a ni procédure de connexion, ni option `--version`, ni autre langue que l'anglais, ni
analyse d'impact sur les délais (time impact analysis). Les valeurs de
[Valeurs fixes et tailles](#valeurs-fixes-et-tailles) de ce guide ne peuvent pas être modifiées.

### Ce qui n'est pas établi

Cette liste est le seul endroit où le guide dit ce que les tests automatisés du projet ne couvrent
pas :

- macOS : aucun test automatisé ne s'y exécute. Sous Windows, la CI couvre la suite de tests et les
  commandes `sample`, `info`, `export` et `crosscheck`, mais ni l'application dans un navigateur ni
  Docker. Aucune tâche d'intégration continue n'exécute les autres commandes de ce guide sous
  Windows.
- Python 3.12 : le paquet l'accepte (`requires-python = ">=3.11"`), et aucun test automatisé ne
  s'exécute sur cette version.
- P6 Professional 24 : aucune sortie de cette version ne figure parmi les références de test.
- Docker : la CI du projet construit l'image, démarre un conteneur, lit sa route de santé et un
  dossier monté. Aucun test ne démarre le conteneur avec `docker compose up` et le fichier
  `compose.yaml` de la racine.
- Un navigateur : les tests automatisés pilotent les pages sans navigateur, et une exécution
  hebdomadaire ouvre chaque page dans un navigateur sans interface graphique pour vérifier son
  accessibilité. Aucun test n'appuie sur un raccourci clavier, et aucun test ne téléverse ni ne
  télécharge un fichier par un navigateur.
- Une première installation à la main : la CI du projet exécute `uv sync --locked` sur une machine
  neuve à chaque exécution, à partir d'une copie de travail du dépôt créée par GitHub Actions.
  Que uv récupère Python de lui-même n'est pas établi.
- La commande `crosscheck` sans Java : aucun test du projet ne l'exécute.
- Les écrans de P6 : l'application et le standard intégré citent des chemins de menu et des noms de
  préférences de P6, et aucun test du projet ne les compare avec P6.
- Les dates d'une Baseline séparée selon chaque base de valeur acquise :
  [docs/standards.md](standards.md#p6-check-schedule-p6-professional-24-17-checks-18-report-lines)
  (en anglais) donne les sources de la règle et consigne qu'aucune lecture sur P6 Professional 26.8
  ne l'étaye encore.
- Streamlit et Plotly : aucun test du projet ne capture ce qu'un navigateur demande à la page.
- La mémoire : un test maintient l'analyseur à quatre fois au plus la taille d'un fichier de 10 Mo
  construit en mémoire. Aucun test ne mesure la mémoire dont l'application a besoin pour une série
  de mises à jour.
- Les exemples de ce guide : la série de démonstration contient un projet par fichier, aucune
  Baseline dans un fichier, aucun coût, aucun Activity Code (code d'activité) et aucun export P6
  XML. Aucun exemple ne montre donc ces cas.

## Glossaire et documents associés

Cette partie définit les termes du guide et liste les documents qui le complètent.

### Glossaire

La liste suivante donne les termes de ce guide. Les termes de P6 conservent l'orthographe de P6.

- **AC**, *actual cost* (coût réel) : ici, les unités de main-d'œuvre réellement consommées à ce
  jour, sur toutes les activités.
- **Activity ID** (identifiant d'activité) : l'identifiant d'une activité dans P6
  (`TASK.task_code`) ; **Task ID** dans l'application.
- **BAC**, *budget at completion* (budget à l'achèvement) : les heures de main-d'œuvre de la
  Baseline pour les activités que contient la mise à jour.
- **Baseline (BL)** (planning de référence) : le plan par rapport auquel une mise à jour est
  mesurée.
- **BEI**, *Baseline Execution Index* (indice d'exécution de la Baseline) : activités terminées
  rapportées aux activités dues à la Data Date. Le standard P6 divise par toutes les activités de la
  Baseline.
- **Check** (contrôle) : un test d'un standard, avec une population, une cible et un statut.
- **Commitment** (engagement) : un début ou une fin que la mise à jour W−1 planifie au plus tard à
  la Data Date de W.
- **Criterion** (critère) : un ou plusieurs contrôles qui partagent un item et comptent une seule
  fois dans le score.
- **Data Date** (date des données) : la date jusqu'à laquelle l'avancement du planning est saisi ;
  **status date** dans l'application.
- **DCMA**, Defense Contract Management Agency (agence américaine de gestion des contrats de
  défense) : auteur du 14-Point Assessment et de DECM.
- **DECM**, DCMA EVMS Compliance Metrics (métriques de conformité EVMS de la DCMA) : ici, ses
  métriques de planning, version 8.0.
- **EAC**, **ETC** : *estimate at completion* (estimation à l'achèvement), AC plus ETC ; *estimate
  to complete* (estimation du reste à faire), les heures restantes.
- **Earned value basis** (base de valeur acquise) : les heures et les dates de Baseline qu'utilisent
  PV et EV. Elle fixe aussi les dates d'une Baseline séparée.
- **EV**, *earned value* (valeur acquise) : unités de main-d'œuvre de la Baseline multipliées par le
  Performance % Complete.
- **Forecast finish** (fin prévisionnelle) : la fin la plus tardive des activités du projet.
- **FS**, **SS**, **FF**, **SF** (fin-début, début-début, fin-fin, début-fin) : les quatre types de
  relation. Dans l'application, **FF** signifie Finish to Finish, et non Free Float.
- **Half-step** (demi-pas) : la mise à jour la plus ancienne recalculée avec le seul avancement de
  la mise à jour la plus récente.
- **LOE**, **WBS**, **MTA** : *level of effort* (niveau d'effort) ; *work breakdown structure*
  (organigramme des tâches) ; *milestone trend analysis* (analyse de tendance des jalons).
- **P6 Project Baseline** (Baseline de projet de P6) : la Baseline qu'un projet nomme dans
  `PROJECT.sum_base_proj_id`.
- **P6 XML export** (export P6 XML) : le format d'export XML de P6, lu par xerscope pour ses
  Baselines.
- **Planned dates** (dates planifiées) : les dates `target_*` d'une activité.
- **Population** (population) : les activités ou les relations qu'examine un contrôle.
- **PPC**, *percent plan complete* (pourcentage du plan réalisé) : engagements tenus rapportés aux
  engagements pris.
- **PV**, *planned value* (valeur planifiée) : unités de main-d'œuvre de la Baseline multipliées par
  le Schedule % Complete.
- **Recalculation** (recalcul) : le calcul du planning d'un fichier par xerscope lui-même, comparé
  aux dates enregistrées.
- **Score** (score) : critères en pass rapportés aux critères en pass ou en fail.
- **Series**, **update**, **snapshot** (série, mise à jour, snapshot) : les mises à jour d'un même
  projet, ordonnées par Data Date ; un export `.xer` du planning à une Data Date ; une mise à jour
  une fois lue.
- **SPI**, **SV** : *schedule performance index* (indice de performance des délais), EV sur PV ;
  *schedule variance* (écart de délais), EV moins PV. **SPI(t)** et **TSPI** sont les indices
  d'Earned Schedule, en temps au lieu d'heures.
- **Standard** (standard) : une liste de contrôles avec leurs cibles, intégrée ou écrite en TOML.
- **TA**, **TMR** : Tasks Anticipated (tâches anticipées) et Tasks Made Ready (tâches rendues
  prêtes), les mesures de lookahead du PPC.
- **TF** : Total Float (marge totale).
- **W**, **W−1** : une mise à jour et celle qui la précède.
- **wd**, **cal. d** : *working days* (jours ouvrés) du calendrier de l'activité, ou du calendrier
  du projet pour un total de projet ; *calendar days* (jours calendaires).
- **XER** : le fichier d'export de P6, à champs séparés par des tabulations.

### Documents associés

Les documents suivants complètent ce guide :

- [docs/it-deployment-guide.fr.md](it-deployment-guide.fr.md) : l'hébergement de l'application pour
  une équipe.
- [docs/deploy.md](deploy.md) (en anglais) : le déploiement distant, et le lexique du champ
  **Ask the schedule**.
- [docs/formulas.md](formulas.md) (en anglais) : la formule et la population de chaque chiffre.
- [docs/standards.md](standards.md) (en anglais) : les standards, leurs sources et leurs
  différences.
- [docs/cpm.md](cpm.md) (en anglais) : le moteur de recalcul.
- [docs/backlog.md](backlog.md) (en anglais) : ce qui est connu comme faux, non prouvé ou manquant.
- [docs/architecture.md](architecture.md) (en anglais) : le code, module par module.
- [docs/adr/README.md](adr/README.md) (en anglais) : les relevés de décisions d'architecture.
- [README.md](../README.md) (en anglais) : la vue d'ensemble du projet et sa validation.
- [CONTRIBUTING.md](../CONTRIBUTING.md) (en anglais) : la mise en place pour les contributeurs et
  les tests.
