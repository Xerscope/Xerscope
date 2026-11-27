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
l'identifiant et l'empreinte (entre apostrophes). Sur un NAS qui porte déjà xerscope,
ce fichier est inutile : le `.env` en place garde son identifiant et son mot de passe (B4).

Le kit à remettre, sur une clé USB ou un partage :

| Fichier | Rôle |
|---|---|
| `xerscope.tar`, `xerscope-caddy.tar` | les deux images |
| `compose.yaml`, `Caddyfile` | copiés de `deploy/lan/`, à ne pas modifier |
| `.env` | seulement pour un NAS neuf : identifiant et empreinte |

## Partie B. Installer sur le NAS (dans DSM)

Le NAS porte déjà l'installation distante de `docs/deploy.md` : le dossier
`docker/xerscope`, le dossier partagé des exports (`xerscope-data`), le compte de
l'application et le dossier du lexique. Tout cela est repris tel quel ; seuls deux fichiers
et quelques lignes de `.env` changent. Sur un NAS neuf, faire d'abord les sections 4 et 5
de `docs/deploy.md` (dossiers, compte, uid), puis reprendre ici.

À faire avec un compte administrateur de DSM. Compter un quart d'heure.

### B1. Noter l'adresse du NAS

Panneau de configuration → **Réseau** → onglet **Interface réseau** → noter l'adresse IP
de `LAN 1`, par exemple `192.168.1.50`.

Cette adresse ne doit plus changer : la réserver dans la box (bail DHCP statique) ou la
fixer dans ce même écran (Modifier → Configuration manuelle). Si elle change, le projet ne
démarre plus tant que `.env` n'est pas corrigé.

### B2. Retirer l'ancien projet

Container Manager → **Projet** → `xerscope` → Action → **Arrêter**, puis Action →
**Supprimer**. Les fichiers de `docker/xerscope` et les plannings ne sont pas touchés.

L'accès distant s'arrête là. Pour qu'il ne puisse pas revenir, la personne qui gère le
compte Tailscale supprime la machine `xerscope` dans sa console d'administration.

### B3. Remplacer deux fichiers

Dans **File Station**, dossier `docker/xerscope` :

1. Télécharger `.env` sur l'ordinateur (il sert à l'étape suivante).
2. Déposer `compose.yaml` et `Caddyfile` du kit, en acceptant de **remplacer** les anciens.
3. Supprimer `tailscale-serve.json` : il ne sert plus.

Le dossier `lexicon` reste en place.

### B4. Adapter `.env`

Ouvrir le `.env` téléchargé avec le Bloc-notes. Supprimer deux lignes, en ajouter trois,
ne pas toucher aux autres :

```
TS_AUTHKEY=...                                  # à supprimer
XERSCOPE_PATH=...                               # à supprimer

XERSCOPE_LAN_IP=192.168.1.50                    # à ajouter : l'adresse notée en B1
XERSCOPE_IMAGE=xerscope:custom                  # à ajouter, tel quel
XERSCOPE_CADDY_IMAGE=xerscope-caddy:custom      # à ajouter, tel quel

XERSCOPE_USER=<identifiant>                     # inchangé : même identifiant, même mot de passe
XERSCOPE_PASSWORD_HASH='$2a$10$...'             # inchangé, garder les apostrophes
XERSCOPE_EXPORTS=/volume1/xerscope-data         # inchangé
XERSCOPE_UID=1028                               # inchangé
XERSCOPE_GID=100                                # inchangé
XERSCOPE_LEXICON_DIR=/volume1/docker/xerscope/lexicon   # inchangé
```

S'il existe déjà une ligne `XERSCOPE_IMAGE=` ou `XERSCOPE_CADDY_IMAGE=` (elle commence par
`ghcr.io/...`), la remplacer par celles ci-dessus au lieu d'en ajouter une seconde.

Enregistrer (type « Tous les fichiers », nom `".env"` avec les guillemets), puis redéposer
le fichier dans `docker/xerscope` en remplaçant l'ancien.

### B5. Importer les deux images

Container Manager → **Image** → Action → **Importer** → Ajouter à partir d'un fichier →
choisir `xerscope.tar`. Recommencer avec `xerscope-caddy.tar`.

Attendre que les deux lignes `xerscope` et `xerscope-caddy`, étiquette `custom`,
apparaissent dans la liste (une à deux minutes chacune).

### B6. Recréer le projet

Container Manager → **Projet** → Créer :

1. Nom du projet : `xerscope`.
2. Chemin : `/docker/xerscope`.
3. Source : **Utiliser le docker-compose.yml existant** (il trouve `compose.yaml`).
4. Suivant. Ne rien cocher à l'étape du portail web. Suivant → Effectué.

Laisser vides les champs « Environnement » : seuls ceux de `.env` comptent.

Après une quarantaine de secondes, Container Manager → **Conteneur** affiche deux
conteneurs en cours d'exécution, `xerscope-caddy-1` et `xerscope-xerscope-1`, ce dernier
marqué « sain ». Il n'y a plus de conteneur `tailscale`. Un troisième, `lexicon-init`,
n'est pas démarré : c'est voulu.

### B7. Ouvrir l'application

Depuis un ordinateur du réseau local : `https://192.168.1.50:8443` (l'adresse de B1).
L'ancienne adresse en `.ts.net` ne répond plus.

- Le navigateur affiche un avertissement de sécurité à la première visite : le
  certificat est fabriqué par le NAS lui-même, aucun organisme extérieur ne le connaît.
  Cliquer sur **Paramètres avancés** → **Continuer vers le site**. La connexion est
  chiffrée.
- Saisir l'identifiant et le mot de passe habituels.
- La page liste les fichiers de `xerscope-data`.

Si le pare-feu de DSM est activé (Panneau de configuration → Sécurité → Pare-feu),
ajouter une règle : port TCP `8443`, source : le sous-réseau local, Autoriser.

### B8. Ménage (facultatif)

Container Manager → **Image** : supprimer les anciennes images `ghcr.io/xerscope/...` et
`tailscale/tailscale`. Container Manager → **Volume** : supprimer `xerscope_tailscale-state`.

## Au quotidien

| Besoin | Geste |
|---|---|
| Ajouter une semaine | déposer le `.xer` dans `xerscope-data`, comme avant, recharger la page |
| Arrêter, redémarrer | Container Manager → Projet → `xerscope` → Action → Arrêter / Démarrer |
| Nouvelle version | importer les nouveaux `.tar` (B5), puis Projet → `xerscope` → Action → **Créer** (reconstruire) |
| Changer le mot de passe | nouvelle empreinte (partie A) dans `.env`, puis Action → Créer |
| Lire les journaux | Container Manager → Conteneur → le conteneur → onglet Journal |

## En cas de problème

| Ce que l'on voit | Cause | Remède |
|---|---|---|
| Création du projet : `required variable XERSCOPE_... is missing a value` | une ligne manque dans `.env`, ou le fichier ne s'appelle pas exactement `.env` | corriger (B4), relancer |
| Création du projet : `No such image` ou `pull access denied` | image non importée, ou étiquette différente de celle de `.env` | B5 ; comparer avec Container Manager → Image |
| Création du projet : `cannot assign requested address` | `XERSCOPE_LAN_IP` n'est pas l'adresse du NAS | B1, corriger `.env` |
| Création du projet : `bind source path does not exist` | chemin de dossier faux dans `.env` (majuscules, volume) | B4 |
| La page ne s'ouvre pas | pare-feu DSM, ou adresse tapée en `http://` | règle de B7 ; l'adresse commence par `https://` |
| La page s'ouvre, aucun fichier ; journal : `Permission denied` | `XERSCOPE_UID` / `XERSCOPE_GID` faux, ou droits du compte | `docs/deploy.md` §5 |
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
