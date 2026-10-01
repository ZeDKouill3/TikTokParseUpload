<div align="center">
  <img src="clipper/web/static/logo.svg" width="96" height="96" alt="Logo clipper"/>

  # clipper

  Vidéo YouTube ou VOD Twitch → clips verticaux TikTok sous-titrés, prêts à publier.

  <p>
    <img alt="Version" src="https://img.shields.io/badge/version-0.1.0%20pr%C3%A9--version-orange">
    <img alt="Python" src="https://img.shields.io/badge/python-3.11-blue">
    <img alt="Plateforme" src="https://img.shields.io/badge/plateforme-Windows-lightgrey">
    <img alt="GPU" src="https://img.shields.io/badge/GPU-CUDA%20optionnel-76b900">
  </p>
</div>

> ⚠️ **Pré-version.** Pas encore de garantie de stabilité de la ligne de
> commande ni du format de configuration. Voir
> [`docs/releases/v0.1.0.md`](docs/releases/v0.1.0.md).

## Ce que ça fait

`clipper` transforme une vidéo longue (live, podcast, reportage, VOD
Twitch...) en clips verticaux (9:16) sous-titrés, prêts à publier sur
TikTok. Une vidéo de plusieurs heures est découpée en moments forts —
sélectionnés par un LLM noté selon une grille et un jury à cinq juges — puis
chaque moment devient un clip (ou plusieurs parties s'il est trop long),
sous-titré mot par mot et recadré verticalement.

Le pipeline tourne en local : téléchargement, transcription
(faster-whisper), détection de scènes/visages, rendu (ffmpeg) sur ta
machine ; seules les étapes qui demandent du jugement (choix des moments,
points de coupe, titres/légendes, contrôle qualité...) passent par Claude
via `clipper.llm`.

## Démo

Rejeu d'une vraie session (identifiants remplacés par un id neutre) :

<img src="docs/assets/demo-terminal.svg" alt="Animation : session python -m clipper -v run, des 12 étapes au clip prêt" width="100%"/>

Les 12 étapes, du téléchargement au clip prêt :

<img src="docs/assets/pipeline.svg" alt="Schéma animé du pipeline clipper" width="100%"/>

<!-- demo-clip.gif -->

## Points forts

- **Mode `auto` de bout en bout** — sélection des moments, découpage,
  sous-titrage, recadrage, rendu et contrôle qualité sans intervention, avec
  reprise en file d'attente sur échec transitoire plutôt qu'un résultat
  dégradé en silence.
- **Jury IA à cinq juges** (rétention, monteur, avocat, spectateur,
  conformité) pour la sélection automatique des moments, appris de ses
  erreurs sans uniformiser les avis.
- **Deux formats de recadrage** — `letterbox` (zoom fixe, défaut) et
  `stream` (facecam fixe agrandie + jeu, pour les VOD de streamers).
- **Appel à l'abonnement optionnel** — pseudo de chaîne discret et carte de
  fin « Abonne-toi ! », désactivé par défaut, activable par preset de chaîne.
- **Tout tourne sur CPU** si besoin (`clipper.gpu` détecte CUDA
  automatiquement, jamais codé en dur), un seul modèle lourd en VRAM à la
  fois.
- **Étapes indépendantes et reprises depuis le cache** — une étape déjà
  faite ne se relance pas sauf `--force`.

## Installation

```powershell
uv venv
uv pip install -e ".[test]"
```

`uv` est **obligatoire** (pas `pip` seul) : `pyproject.toml` déclare sous
`[tool.uv] override-dependencies` un contournement qui force un seul paquet
OpenCV installé (`opencv-contrib-python`) — `mediapipe` et `scenedetect` en
réclament chacun un différent, et `pip` seul ignore ce réglage.

Ou lance `tools/setup.ps1`, qui fait tout ça et vérifie les prérequis (uv,
Python 3.11, ffmpeg, `claude`, `ank`, GPU optionnel, Google Chrome pour
[publier sur TikTok](#publier-sur-tiktok)).

Depuis la release (sans cloner le dépôt) : télécharge le `.whl` de la
[dernière release](docs/releases/v0.1.0.md), `uv pip install
clipper-0.1.0-py3-none-any.whl` puis `clipper init` (écrit `config.toml` et
`rubric.toml` — la grille par défaut, embarquée dans la wheel — dans le
dossier courant). La commande `clipper` s'ajoute à `python -m clipper`.

**Prérequis** : Python 3.11 (géré par uv), [ffmpeg](https://ffmpeg.org/)
(et `ffprobe`) dans le PATH, [Claude Code CLI](https://docs.claude.com/claude-code)
(`claude`) connecté (backend LLM par défaut). Pilote NVIDIA optionnel pour
accélérer transcription et rendu ; sans GPU, tout tourne sur CPU.

## Démarrage rapide

```powershell
cp config.example.toml config.toml   # mode "review" par defaut
python -m clipper -v run <url-youtube-ou-twitch>
python -m clipper serve              # console web : http://127.0.0.1:8000
```

En mode `review`, l'interface web (ou `python -m clipper decide`) sert à
accepter/refuser/ajuster chaque moment proposé, puis `python -m clipper
render <video_id>` (ou le bouton « rendre » de l'interface) termine le clip.
Voir [`docs/GUIDE.md`](docs/GUIDE.md) pour le détail des commandes.

## Formats

- **letterbox** (défaut, `[reframe] format = "letterbox"`) — aucune
  détection de visage : image source zoomée et centrée, fond flou de la
  même vidéo, titre d'écran dans la bande floue du haut, sous-titres dans
  celle du bas.
- **stream** (`layout = "stream_auto"`) — pour les vidéos avec facecam :
  facecam fixe agrandie en haut, jeu en bas, jamais de bascule de mise en
  page au sein d'un même clip.

Contrat de sortie complet (zones sûres TikTok, style des sous-titres...) :
`SPEC-6a47` et `SPEC-3a88` dans `AGENTS.md`.

## Preset par chaîne et CTA abonnement

Un fichier de config par chaîne active des réglages spécifiques sans
toucher `config.toml` :

```powershell
python -m clipper run <url> --config presets/ma-chaine.toml
```

L'appel à l'abonnement est **désactivé par défaut** ; sans configuration
explicite, le rendu, le sidecar et la légende restent identiques. Pour
l'activer dans un preset :

```toml
[render]
cta_enabled = true
cta_handle = "twitch.tv/ma-chaine"   # obligatoire si cta_enabled
cta_seconds = 2                       # duree de la carte de fin (s)
```

`cta_enabled` sans `cta_handle` est une erreur explicite, jamais un rendu à
moitié activé.

## Modes review/auto

- **review** (défaut) — rien n'est publié sans validation humaine des
  moments proposés (accepter / refuser / ajuster les bornes), via
  l'interface web ou `python -m clipper decide`.
- **auto** — le pipeline va jusqu'au bout tout seul ; le contrôle qualité
  (étape `qa`) remplace la revue humaine, et un échec transitoire (Claude
  indisponible, quota, réseau) remet la vidéo en file d'attente au lieu
  d'abandonner ou de produire un résultat dégradé en silence.

## Interface web : Console de gestion web (v2)

`python -m clipper serve` lance la console (`http://127.0.0.1:8000`) et le
worker qui traite une file de vidéos, une à la fois. Huit écrans : Accueil,
Vidéos, Revue des moments, Clips, Chaînes (presets en surcouche, éditeur
d'agencement, aperçu des sous-titres), Publication (calendrier de créneaux),
Statistiques et Réglages ; progression en temps réel, surveillance des VOD
d'une chaîne, notifications du navigateur. La page est statique (HTML/CSS/JS,
sans étape de build) et ne fait aucun traitement vidéo, audio ou LLM.

Pour l'ouvrir depuis un téléphone du réseau local :
`python -m clipper serve --host 0.0.0.0`, ce qui exige `[web] token` dans
`config.toml`. Pas de TLS : ne pas exposer le port sur Internet sans reverse
proxy TLS. Détails dans [`docs/GUIDE.md`](docs/GUIDE.md).

## Publier sur TikTok

La publication passe par un **vrai Chrome visible** piloté par Playwright, avec
un profil par compte rangé dans `state/browser/<compte>/` (ignoré par git,
jamais copié hors de `state/`). Le programme ne saisit **jamais** ton
identifiant ni ton mot de passe : tu te connectes à la main, une fois, dans un
**Chrome normal** (voir ci-dessous).

1. **Relier un compte** — dans la console, écran **Comptes**, ajoute le compte
   TikTok (libellé, plateforme) ; dans l'écran **Chaînes**, ouvre la chaîne et
   choisis ce compte dans `tiktok_account` (ou écris `tiktok_account = "<id>"`
   dans la table `[channel]` du preset). Un identifiant inconnu est refusé.
2. **Se connecter une fois** — bouton **Se connecter dans le navigateur** du
   compte (console ouverte sur `127.0.0.1`/`localhost` seulement), ou
   `python -m clipper browser login <compte>` (`--url` pour une autre page,
   TikTok par défaut). Un **Chrome normal** (lancé comme un programme
   ordinaire, sur le profil du compte, jamais par Playwright) s'ouvre sur la
   page de connexion : connecte-toi, puis ferme la fenêtre. La connexion ne
   passe pas par Playwright parce que TikTok refuse un Chrome piloté (faux
   message « Nombre maximal de tentatives atteint ») ; une fois connecté,
   Playwright réutilise la session du profil pour publier. L'écran Comptes
   affiche l'état du profil (absent ou présent, avec la date).
3. **Prérequis** — Google Chrome installé (trouvé dans le `PATH` ou aux
   emplacements usuels ; sinon règle `[browser] chrome_path = "C:\\...\\chrome.exe"`
   dans `config.toml`) et la dépendance `playwright` (installée par
   `tools/setup.ps1` ou `uv pip install -e ".[test]"`). Sans Chrome, la
   connexion échoue avec un message explicite ; sans Playwright, la publication
   échoue avec la commande à lancer (`playwright install chrome`) : aucun
   navigateur de remplacement n'est utilisé.

**Risques assumés** : piloter TikTok par un navigateur n'est pas prévu par ses
conditions d'utilisation ; le compte peut subir un captcha, une vérification
ou une restriction. **Captcha, vérification ou page inattendue = arrêt
immédiat** : le programme ne résout ni ne contourne jamais un captcha, il
laisse la main à l'utilisateur et remonte l'échec.

### Publication automatique (worker)

Le worker (`python -m clipper worker`, lancé par `serve`) publie, une à la
fois et un compte à la fois, les clips **dus** de `state/publish/<chaîne>.json`
(statut `scheduled`) avec le mp4, la légende et les hashtags du sidecar. Deux
modes, réglés par `[tiktok] publish_mode` (ou par clip) :

- `immediate` (défaut) : publié quand le créneau est atteint (le PC doit être
  allumé) ;
- `scheduled` : programmé côté TikTok à la date du créneau, dès qu'elle est à
  moins de `schedule_max_days` jours (10 : la limite de TikTok Studio) ; au-delà
  ou à moins de `schedule_min_minutes` du créneau, la programmation est refusée
  explicitement.

Le succès enregistre l'URL ou l'id du post dans l'entrée et le sidecar. **Tout
arrêt** (captcha, vérification, connexion expirée, élément absent, page
inattendue) met le clip en `failed` avec la raison et une capture d'écran sous
`state/browser/<compte>/captures/`, arrête les publications de ce compte et
notifie la console : bouton **Réessayer** dans l'écran Publication. Les
sélecteurs de la page TikTok Studio vivent dans
`clipper/assets/tiktok_selectors.toml` : relevés sur la vraie page d'envoi le
2026-10-01 (l'en-tête du fichier dit ce qui est vérifié en réel, et ce qui ne
l'est pas : la confirmation après publication) ; à confirmer avec
`CLIPPER_TIKTOK_REAL=1 pytest tests/integration/test_tiktok_real.py`, qui
publie en privé sur un compte de test.

Détails du pilotage de TikTok Studio :

- la légende (pré-remplie du nom du fichier) est vidée puis tapée touche par
  touche ;
- en mode `scheduled`, la date et l'heure se règlent par les sélecteurs de
  TikTok (calendrier, flèches de mois, liste des heures) ; les minutes sont
  arrondies au pas proposé par TikTok (journalisé, noté dans l'entrée) ;
- avant le clic final, le programme attend le résultat de la **vérification de
  contenu** de TikTok : « Aucun problème constaté » → il continue ; problème
  signalé ou délai `[tiktok] content_check_timeout_s` (900 s par défaut)
  dépassé → arrêt explicite, rien n'est publié ;
- les fenêtres connues (`[popups]` du fichier : « Activer les vérifications
  automatiques du contenu ? » → **Annuler**, « Nouvelles fonctionnalités
  d'édition ajoutées » → **J'ai compris**) sont fermées et journalisées ; toute
  autre fenêtre modale est un arrêt, jamais un clic au hasard.

Rythme (`[tiktok]`, étude `docs/tiktok-cadence.md` §3.1) : délais aléatoires
entre actions, plafond de posts par jour et écart minimal par compte ; un
dépassement reporte le clip au prochain créneau libre, journalisé. Les défauts
sont ceux d'un **compte neuf** ; pour un **compte établi** (après 14 jours,
vues stables) :

| Réglage | Compte neuf (défaut) | Compte établi |
|---|---|---|
| `max_posts_per_day` | 1 | 3 |
| `min_gap_minutes` | 480 | 240 |
| `min_action_delay_s` | 1 | 1 |
| `max_action_delay_s` | 3 | 3 |

```toml
[tiktok]
max_posts_per_day = 3
min_gap_minutes = 240
min_action_delay_s = 2
max_action_delay_s = 8
```

## Cookies YouTube

Pour télécharger une vidéo qui exige d'être connecté (âge, abonnés...), yt-dlp
lit les cookies d'un profil du navigateur de clipper plutôt que ceux de
Firefox :

1. connecte le profil à YouTube : `python -m clipper browser login <compte>
   --url https://www.youtube.com` (connexion à la main, puis fermeture de la
   fenêtre) ;
2. dans `config.toml`, règle `[download] cookies_profile = "<compte>"`.

Au téléchargement, les cookies YouTube/Google du profil sont exportés vers
`state/browser/<compte>/cookies.txt` (format Netscape, lisible par toi seul ;
les cookies TikTok n'en sortent pas) et passés à yt-dlp. `cookies_profile`
prime sur `cookies_from_browser` ; le combiner avec `cookies_file` est une
erreur. Profil absent ou sans cookie YouTube : le téléchargement s'arrête avec
un message, sans repli.

## Coûts et performances

Mesures détaillées (VRAM, durée par étape, coût LLM, choix du modèle
whisper) sur RTX 3050 4 Go : [`docs/benchmarks/rtx3050.md`](docs/benchmarks/rtx3050.md).
Banc dédié whisper `small` vs `large-v3-turbo` :
[`docs/bench-whisper-vitesse.md`](docs/bench-whisper-vitesse.md).

## Configuration

Chaque étape du pipeline (module `clipper/x.py`) déclare son propre dict
`CONFIG_DEFAULTS` : c'est lui qui rend une table `[x]` de `config.toml`
valide (clé absente refusée, section sans module ou sans `CONFIG_DEFAULTS`
refusée). Copie `config.example.toml` vers `config.toml` et ajuste au
besoin ; les réglages retenus après le banc RTX 3050 y sont documentés en
commentaire.

## Documentation

- [`docs/GUIDE.md`](docs/GUIDE.md) — guide utilisateur : les 12 étapes du
  pipeline, modes, formats, console de gestion, configuration complète, consommation du quota
  Claude, dépannage.
- [`AGENTS.md`](AGENTS.md) — conventions du dépôt et décisions ratifiées
  (ADR/SPEC), pour qui contribue au code.
- [`CHANGELOG.md`](CHANGELOG.md) — historique des versions.
- [`docs/releases/v0.1.0.md`](docs/releases/v0.1.0.md) — notes de la
  pré-version 0.1.0.

## Développement

```powershell
pytest
```

Tout le pipeline doit tourner sur CPU pour les tests (ADR-fb9b) : aucun test
n'a besoin d'un GPU pour passer. Ce qui a réellement besoin du réseau, d'un
vrai modèle ou du vrai Claude est un test optionnel, sauté par défaut
(`skipif`), jamais lancé en CI ni par défaut en local.

Les tâches et décisions du dépôt vivent dans `.ank/`, gérées par la CLI
[`ank`](https://github.com/haksolot/ank) (`ank context`, `ank claim`, `ank
show`, `ank done`...) — voir `AGENTS.md` pour les règles complètes.

## Limites et feuille de route

- Le format `crop` (suivi de visage) reste une option figée, moins
  travaillée que `letterbox`.
- Sans GPU, le pipeline tourne mais plus lentement (transcription et rendu
  en CPU).
- Le mode `auto` dépend de la disponibilité de Claude ; une panne prolongée
  met les vidéos en file d'attente plutôt que de les abandonner.
- Aucun contenu ni capture vidéo tiers n'est utilisé dans ce dépôt ou sa
  documentation ; un futur GIF de démonstration viendra d'une vidéo sous
  licence libre (voir l'emplacement commenté ci-dessus).
