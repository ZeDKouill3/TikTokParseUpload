# clipper

[![Release](https://img.shields.io/badge/release-v0.1.0--pré--version-blue)](https://github.com/ZeDKouill3/TikTokParseUpload/releases/tag/v0.1.0)

Pipeline qui transforme une vidéo YouTube longue (live, podcast, reportage...)
en clips verticaux (9:16) sous-titrés, prêts à publier sur TikTok. Une vidéo
de plusieurs heures est découpée en moments forts, chaque moment devenant un
clip (ou plusieurs parties s'il est trop long), sous-titré mot par mot,
recadré pour garder les visages dans le cadre.

Résultat pour un moment retenu : `output/<video_id>/<clip_id>.mp4` (vertical,
letterbox par défaut — zoom fixe, titre d'écran en haut, sous-titres dans la
bande floue du bas) accompagné d'un `.json` avec titre, légende, hashtags et
le rapport du contrôle qualité. Voir `docs/GUIDE.md` pour le détail du format.

Le pipeline tourne en local : transcription (faster-whisper), détection de
scènes/visages, rendu (ffmpeg) sur ta machine ; seules les étapes qui
demandent du jugement (choix des moments, points de coupe, titres/légendes,
contrôle qualité...) passent par Claude via `clipper.llm`.

Deux modes :
- **review** : rien n'est publié sans que tu aies validé les moments proposés
  (accepter / refuser / ajuster les bornes) via `python -m clipper decide` ou
  l'interface web (`python -m clipper serve`).
- **auto** : le pipeline va jusqu'au bout tout seul ; le contrôle qualité
  (étape `qa`) remplace la revue humaine, et un échec transitoire (Claude
  indisponible, quota, réseau) remet la vidéo en file d'attente au lieu
  d'abandonner ou de produire un résultat dégradé en silence.

## Prérequis

- **Python 3.11** géré par [uv](https://docs.astral.sh/uv/).
- **[ffmpeg](https://ffmpeg.org/)** (et `ffprobe`) dans le PATH — extraction
  audio, rendu, contrôle qualité.
- **[Claude Code CLI](https://docs.claude.com/claude-code)** (`claude`) dans
  le PATH et connecté — backend LLM par défaut (`clipper.llm`, backend
  `claude-cli`).
- **Pilote NVIDIA** (optionnel) pour accélérer la transcription
  (faster-whisper/CTranslate2) et le rendu (NVENC) sur GPU. Sans GPU, tout le
  pipeline tourne sur CPU (plus lentement, voir `clipper.gpu`).
  Pour que faster-whisper utilise le GPU sous Windows, les DLL cuBLAS/cuDNN
  doivent être trouvables : voir *Pièges* dans `AGENTS.md`.

## Installation

```powershell
uv venv
uv pip install -e ".[test]"
```

`uv` est **obligatoire** (pas `pip` seul) : `pyproject.toml` déclare sous
`[tool.uv] override-dependencies` un contournement qui force un seul paquet
OpenCV installé (`opencv-contrib-python`, sur-ensemble d'`opencv-python`) —
`mediapipe` et `scenedetect` en réclament chacun un différent, et installer
les deux écraserait le module `cv2` de l'un par l'autre. `pip` seul ignore ce
réglage `[tool.uv]` et peut installer les deux.

Ou lance `tools/setup.ps1`, qui fait tout ça et vérifie les prérequis
(uv, Python 3.11, ffmpeg, `claude`, `ank`, GPU optionnel).

## Démarrage rapide

Copie `config.example.toml` vers `config.toml` (réglages par défaut : mode
`review`), puis :

```powershell
python -m clipper run <url-youtube>    # jusqu'a la revue (review) ou jusqu'au bout (auto)
python -m clipper serve                # interface web locale : http://127.0.0.1:8000
```

En mode `review`, l'interface web (ou `python -m clipper decide`) sert à
accepter/refuser/ajuster chaque moment proposé, puis `python -m clipper
render <video_id>` (ou le bouton "rendre" de l'interface) termine le clip.

Voir `docs/GUIDE.md` pour toutes les commandes, les modes, les formats, la
configuration détaillée et le dépannage.

## Où sont les sorties

- `workspace/<video_id>/` : état de travail par vidéo (transcript, moments,
  plans de recadrage, `pipeline.json`...), pas versionné.
- `output/<video_id>/<clip_id>.mp4` + `.json` : clips prêts à publier.

`workspace/` et `output/` sont gitignorés : ce sont des dossiers de travail
par machine, pas des artefacts à versionner.

## Tests

```powershell
pytest
```

Tout le pipeline tourne sur CPU pour les tests (ADR-fb9b) : aucun test n'a
besoin d'un GPU pour passer. Voir `AGENTS.md` pour ce que la suite couvre et
ce qu'elle saute par défaut.

## Documentation

- `docs/GUIDE.md` — guide utilisateur : les 12 étapes du pipeline, modes,
  formats, configuration complète, consommation du quota Claude, dépannage.
- `AGENTS.md` — conventions du dépôt et décisions ratifiées (ADR/SPEC),
  pour qui contribue au code.
- `CHANGELOG.md` — historique des versions.
- `docs/releases/v0.1.0.md` — notes de la pré-version 0.1.0.
