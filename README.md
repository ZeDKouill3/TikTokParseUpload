# clipper

Pipeline qui transforme une vidéo YouTube longue (live, podcast, reportage...)
en clips verticaux (9:16) sous-titrés, prêts à publier sur TikTok. Une vidéo
de plusieurs heures est découpée en moments forts, chaque moment devenant un
clip (ou plusieurs parties s'il est trop long), sous-titré mot par mot,
recadré pour garder les visages dans le cadre.

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
  pipeline tourne sur CPU (plus lentement).
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
`mediapipe` et `scenedetect` en réclament chacun un différent, et les deux
s'installer écraserait le module `cv2` de l'autre. `pip` seul ignore ce
réglage `[tool.uv]` et peut installer les deux.

Ou lance `tools/setup.ps1`, qui fait tout ça et vérifie les prérequis.

## Utilisation

```powershell
python -m clipper run <url-youtube>              # jusqu'a la revue (review) ou jusqu'au bout (auto)
python -m clipper render <video_id>               # reprend apres la revue (ou un echec) jusqu'au bout
python -m clipper decide <video_id> <moment_id> accepted|rejected|adjusted [--start S] [--end S] [--comment C]
python -m clipper status <video_id>               # etat courant (JSON)
python -m clipper queue [--watch] [--interval S]  # reprend les videos en file d'attente
python -m clipper serve [--port P]                # interface web locale (FastAPI, 127.0.0.1)
```

`--config chemin.toml` (defaut `config.toml`) et `-v`/`--verbose` sont
disponibles sur toutes les commandes. Une video en cours produit son etat
sous `workspace/<video_id>/` ; une etape dont le resultat existe deja n'est
pas relancee, sauf `--force`.

## Configuration

Copie `config.example.toml` vers `config.toml` puis ajuste :

```toml
mode = "review"          # ou "auto"
workspace_dir = "workspace"
output_dir = "output"

[llm]
backend = "claude-cli"
```

Chaque étape du pipeline (un module `clipper/<etape>.py`) déclare son propre
`CONFIG_DEFAULTS` : une table `[<etape>]` dans `config.toml` (ex. `[llm]`,
`[transcribe]`, `[render]`, `[web]`...) est validée contre ce dict — une clé
absente de `CONFIG_DEFAULTS` est refusée, une section sans module
`clipper.<etape>` ou sans `CONFIG_DEFAULTS` aussi. Regarde `CONFIG_DEFAULTS`
dans le module concerné pour la liste des clés disponibles et leur sens.

`workspace/` et `output/` sont gitignorés : ce sont des dossiers de travail
par machine, pas des artefacts à versionner.

## Tests

```powershell
pytest
```

Voir `AGENTS.md` pour ce que la suite couvre et ce qu'elle saute par défaut.
