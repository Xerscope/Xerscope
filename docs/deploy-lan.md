# Installation sur le NAS, réseau local uniquement (Container Manager)

Cible : ouvrir xerscope depuis un ordinateur du réseau local, à l'adresse
`https://<ip-du-nas>:8443`, avec un identifiant et un mot de passe. Rien ne sort du NAS :
pas de Tailscale, pas de téléchargement d'image, pas d'accès internet. Les fichiers sont
ceux de `deploy/lan/`.

```
navigateur (réseau local) ──https──▶ <ip-du-nas>:8443 ──▶ caddy (mot de passe) ──▶ xerscope
                                                                                   └─ exports, lecture seule
```

Le guide a deux parties. La partie A se fait une fois, sur un PC, par la personne qui
construit les images. La partie B se fait sur le NAS, entièrement dans DSM, sans ligne de
commande. Les libellés sont ceux de DSM 7.2 et suivants en français ; ils peuvent varier
d'un mot selon la version.

## Partie A. Préparer le kit (sur un PC, avec Docker)

Depuis la racine du dépôt, sur un PC de même architecture que le NAS (Intel/AMD pour un
DS918+ ; sur un Mac Apple Silicon, ajouter `--platform linux/amd64` aux deux `build`) :

```bash
docker build -t xerscope:custom .
```

```bash
docker build -t xerscope-caddy:custom deploy/caddy
```

```bash
docker save xerscope:custom -o xerscope.tar
```

```bash
docker save xerscope-caddy:custom -o xerscope-caddy.tar
```

Le mot de passe est stocké sous forme d'empreinte. La commande le demande deux fois et
affiche l'empreinte (`$2a$10$...`) :

```bash
docker run --rm -it xerscope-caddy:custom caddy hash-password --algorithm bcrypt --bcrypt-cost 10
```

Créer ensuite le fichier `.env` à partir de `deploy/lan/.env.example` et y écrire
l'identifiant et l'empreinte (entre apostrophes). Les autres valeurs se remplissent à
l'étape B6.

Le kit à remettre, sur une clé USB ou un partage :

| Fichier | Rôle |
|---|---|
| `xerscope.tar`, `xerscope-caddy.tar` | les deux images |
| `compose.yaml`, `Caddyfile` | copiés de `deploy/lan/`, à ne pas modifier |
| `.env` | les réglages (identifiant, empreinte, puis les valeurs de B6) |

## Partie B. Installer sur le NAS (dans DSM)

À faire avec un compte administrateur de DSM. Compter vingt minutes.

### B1. Vérifier Container Manager

Centre de paquets → rechercher **Container Manager** → Installer s'il ne l'est pas.

### B2. Noter l'adresse du NAS

Panneau de configuration → **Réseau** → onglet **Interface réseau** → noter l'adresse IP
de `LAN 1`, par exemple `192.168.1.50`.

Cette adresse ne doit plus changer : la réserver dans la box (bail DHCP statique) ou la
fixer dans ce même écran (Modifier → Configuration manuelle). Si elle change, le projet ne
démarre plus tant que `.env` n'est pas corrigé.

### B3. Créer les trois dossiers

Panneau de configuration → **Dossier partagé** → Créer, deux fois :

| Nom | Contenu | Options |
|---|---|---|
| `xerscope-data` | les fichiers `.xer` hebdomadaires | masqué, sans corbeille, non chiffré |
| `xerscope-lexicon` | le lexique du champ « Ask » | masqué, sans corbeille, non chiffré |

Puis dans **File Station** :

- dans `xerscope-lexicon`, créer trois dossiers vides : `generated`, `curated`, `suggested` ;
- dans `docker`, créer le dossier `xerscope-lan` et y déposer `compose.yaml`, `Caddyfile`
  et `.env` (si `.env` n'apparaît pas, c'est normal sous Windows : il est bien là).

Le dossier partagé `docker` contient les réglages : Panneau de configuration → Dossier
partagé → `docker` → Modifier → Permissions → lecture/écriture pour votre compte seul.

### B4. Créer le compte de l'application

L'application lit les plannings avec un compte à elle, qui n'a accès à rien d'autre.

Panneau de configuration → **Utilisateur et groupe** → Créer :

1. Nom : `xerscope-app`, mot de passe long quelconque (il ne sert jamais).
2. Groupe : `users`.
3. Permissions des dossiers : **Lecture seule** sur `xerscope-data`,
   **Lecture/écriture** sur `xerscope-lexicon`, **Aucun accès** partout ailleurs.
4. Permissions des applications : tout **Refuser**.

### B5. Lire le numéro du compte

Panneau de configuration → **Planificateur de tâches** → Créer → Tâche planifiée →
Script défini par l'utilisateur :

1. Onglet Général : nom `uid-xerscope`, utilisateur : votre compte, décocher « Activé ».
2. Onglet Paramètres de tâche, dans « Exécuter la commande » :

   ```
   id xerscope-app > /volume1/docker/xerscope-lan/uid.txt 2>&1
   ```

3. OK, puis sélectionner la tâche → **Exécuter**.

Dans File Station, ouvrir `docker/xerscope-lan/uid.txt`. Il contient par exemple
`uid=1028(xerscope-app) gid=100(users)` : noter les deux nombres. Supprimer ensuite la
tâche et le fichier `uid.txt`.

### B6. Compléter `.env`

Télécharger `.env` depuis File Station, l'ouvrir avec le Bloc-notes, compléter, enregistrer
(type « Tous les fichiers », nom `".env"` avec les guillemets), puis le redéposer dans
`docker/xerscope-lan` en remplaçant l'ancien.

```
XERSCOPE_LAN_IP=192.168.1.50                    # l'adresse notée en B2
XERSCOPE_IMAGE=xerscope:custom                  # ne pas changer
XERSCOPE_CADDY_IMAGE=xerscope-caddy:custom      # ne pas changer
XERSCOPE_USER=<identifiant>                     # déjà rempli (partie A)
XERSCOPE_PASSWORD_HASH='$2a$10$...'             # déjà rempli, garder les apostrophes
XERSCOPE_EXPORTS=/volume1/xerscope-data         # majuscules et minuscules exactes
XERSCOPE_LEXICON_DIR=/volume1/xerscope-lexicon
XERSCOPE_UID=1028                               # les deux nombres notés en B5
XERSCOPE_GID=100
```

Si le NAS a plusieurs volumes, remplacer `/volume1` par celui qu'affiche File Station →
clic droit sur le dossier → Propriétés → Emplacement.

### B7. Importer les deux images

Container Manager → **Image** → Action → **Importer** → Ajouter à partir d'un fichier →
choisir `xerscope.tar`. Recommencer avec `xerscope-caddy.tar`.

Attendre que les deux lignes `xerscope` et `xerscope-caddy`, étiquette `custom`,
apparaissent dans la liste (une à deux minutes chacune).

### B8. Créer le projet

Container Manager → **Projet** → Créer :

1. Nom du projet : `xerscope-lan`.
2. Chemin : `/docker/xerscope-lan`.
3. Source : **Utiliser le docker-compose.yml existant** (il trouve `compose.yaml`).
4. Suivant. Ne rien cocher à l'étape du portail web. Suivant → Effectué.

Laisser vides les champs « Environnement » : seuls ceux de `.env` comptent.

Après une quarantaine de secondes, Container Manager → **Conteneur** affiche deux
conteneurs en cours d'exécution, `xerscope-lan-caddy-1` et `xerscope-lan-xerscope-1`, ce
dernier marqué « sain ». Un troisième, `lexicon-init`, n'est pas démarré : c'est voulu.

### B9. Ouvrir l'application

Depuis un ordinateur du réseau local : `https://192.168.1.50:8443` (l'adresse de B2).

- Le navigateur affiche un avertissement de sécurité à la première visite : le
  certificat est fabriqué par le NAS lui-même, aucun organisme extérieur ne le connaît.
  Cliquer sur **Paramètres avancés** → **Continuer vers le site**. La connexion est
  chiffrée.
- Saisir l'identifiant et le mot de passe.
- La page liste les fichiers de `xerscope-data`.

Si le pare-feu de DSM est activé (Panneau de configuration → Sécurité → Pare-feu),
ajouter une règle : port TCP `8443`, source : le sous-réseau local, Autoriser.

## Au quotidien

| Besoin | Geste |
|---|---|
| Ajouter une semaine | déposer le `.xer` dans `xerscope-data`, recharger la page |
| Arrêter, redémarrer | Container Manager → Projet → `xerscope-lan` → Action → Arrêter / Démarrer |
| Nouvelle version | importer les nouveaux `.tar` (B7), puis Projet → `xerscope-lan` → Action → **Créer** (reconstruire) |
| Changer le mot de passe | nouvelle empreinte (partie A) dans `.env`, puis Action → Créer |
| Lire les journaux | Container Manager → Conteneur → le conteneur → onglet Journal |

## En cas de problème

| Ce que l'on voit | Cause | Remède |
|---|---|---|
| Création du projet : `required variable XERSCOPE_... is missing a value` | une ligne manque dans `.env`, ou le fichier ne s'appelle pas exactement `.env` | corriger (B6), relancer |
| Création du projet : `No such image` ou `pull access denied` | image non importée, ou étiquette différente de celle de `.env` | B7 ; comparer avec Container Manager → Image |
| Création du projet : `cannot assign requested address` | `XERSCOPE_LAN_IP` n'est pas l'adresse du NAS | B2, corriger `.env` |
| Création du projet : `bind source path does not exist` | chemin de dossier faux dans `.env` (majuscules, volume) | B6 |
| La page ne s'ouvre pas | pare-feu DSM, ou adresse tapée en `http://` | règle de B9 ; l'adresse commence par `https://` |
| La page s'ouvre, aucun fichier ; journal : `Permission denied` | `XERSCOPE_UID` / `XERSCOPE_GID` faux, ou droits du compte | B4, B5 |
| Erreur 502 après le mot de passe | l'application démarre encore, ou s'est arrêtée | attendre une minute ; sinon lire son journal |
| Erreur 429 | trop de requêtes en une minute depuis le même poste | attendre une minute |

## Ce que cette installation garantit

- Le port n'est ouvert que sur l'adresse locale du NAS. Ne créer aucune redirection de
  port vers `8443` dans la box, ni règle QuickConnect ou proxy inversé DSM vers ce port.
- L'application est sur un réseau Docker sans passerelle : elle ne joint ni internet ni
  les autres machines du réseau local. Seul Caddy la joint.
- Aucune image n'est téléchargée : une image absente arrête la création du projet.
- Les plannings sont montés en lecture seule : l'application ne peut ni les modifier ni
  les supprimer.
