This repo uses Ank: tasks and decisions live in `.ank/`.

## Setup

```powershell
uv venv
uv pip install -e ".[test]"
```

`uv` est obligatoire (pas `pip` seul) : voir `[tool.uv] override-dependencies`
dans `pyproject.toml`, qui force un seul paquet OpenCV installé. `tools/setup.ps1`
fait cette installation et vérifie les prérequis (uv, Python 3.11, ffmpeg,
`claude`, `ank`, GPU optionnel).

## Tests

```powershell
pytest
```

Tout le pipeline doit tourner sur CPU pour les tests (ADR-fb9b) : aucun test
n'a besoin d'un GPU pour passer. Ce qui a réellement besoin du réseau, d'un
vrai modèle ou du vrai Claude est un test optionnel, sauté par défaut via
`skipif` (binaire absent du PATH, ou variable d'environnement à positionner
explicitement, ex. `CLIPPER_CLAUDE_INTEGRATION=1`, `CLIPPER_REAL_MODELS=1`) —
jamais lancé en CI ni par défaut en local.

## Règles ank

- CLI ank seulement : jamais lire ou écrire `.ank/` à la main, cet état est
  opaque comme `.git/` (`ank show`/`ank find`/`ank context` savent lire).
- `ank accept` (ratifier un ADR) est réservé à un humain, sur la branche
  par défaut, signé — jamais un agent.
- Un worktree par agent, une branche par tâche coupée depuis la branche par
  défaut ; `ANK_AGENT` identifie la session (sinon `<user>@<hostname>`, un
  mode dégradé où deux sessions partagent une claim au lieu de se
  l'arbitrer).
- `ank done` doit trouver `ank` (et les outils de test) dans le PATH :
  ajoute `.venv\Scripts` en tête avant de le lancer, par exemple
  `$env:Path = "$PWD\.venv\Scripts;" + $env:Path; ank done`.

## Décisions ratifiées (ADR / SPEC)

- **ADR-b16b** — pipeline `clipper/` (Python >= 3.11) : une étape = un module
  qui lit ses entrées et écrit sous `workspace/<video_id>/` ; une étape déjà
  faite ne se relance pas sauf `--force` ; une étape n'importe jamais une
  autre étape ni `clipper.web` directement, seul `clipper.pipeline` enchaîne.
- **ADR-fb9b** — device résolu par `clipper.gpu` (jamais codé en dur) ; un
  seul modèle lourd en VRAM à la fois, libéré explicitement après usage.
- **ADR-b1c1** — tout appel LLM passe par `clipper.llm` (backends
  interchangeables, modèle par usage, réponse validée contre un schéma JSON).
  Texte et images fixes seulement, jamais vidéo/audio.
- **ADR-ad2e** — mode `review`/`auto` en config ; aucune valeur de secours
  silencieuse (légende générique, moments par défaut, backend dégradé) : un
  échec remonte, est journalisé, ou met la vidéo en attente.
- **ADR-09ad** — interface web (`clipper/web/`) : page statique servie par
  FastAPI, aucune logique de traitement vidéo/audio/LLM dedans.
- **SPEC-350f** — contrat de sortie d'un clip (`output/<video_id>/<clip_id>.mp4`
  + `.json` sidecar, champs obligatoires).
- **SPEC-53f3** — grille de notation des moments (`rubric.toml`), critères et
  règles de sélection.

## Conventions

- Les réglages d'un module vivent dans son `CONFIG_DEFAULTS` (dict au niveau
  module) ; c'est ce dict qui rend une table `[nom]` de `config.toml`
  valide — voir `clipper/config.py`. Ne pas ajouter de réglage ailleurs
  (variable globale, argument caché...).
- Device via `clipper.gpu.get_device()`, jamais `"cuda"`/`"cpu"` en dur.
- Tout accès à un LLM via `clipper.llm.ask(...)` ; dans les tests, brancher
  `clipper.llm.fake.FakeBackend` avec `llm.use_backend(fake)` — jamais le
  vrai Claude dans un test qui tourne par défaut.
- Aucun test n'utilise le réseau. Un test qui a besoin d'un vrai modèle, du
  GPU ou du vrai Claude est marqué `skipif` et sauté par défaut.
- Une étape (module `clipper/x.py`) n'importe jamais une autre étape ni
  `clipper.web` : l'enchaînement passe uniquement par `clipper.pipeline`.

## Pièges

- **Installer avec `uv`**, pas `pip` seul : `pip` ignore
  `[tool.uv] override-dependencies` et peut installer deux paquets OpenCV
  incompatibles (mediapipe veut `opencv-contrib-python`, scenedetect veut
  `opencv-python`, même module `cv2`).
- **faster-whisper en CUDA** a besoin des paquets `nvidia-cublas-cu12` et
  `nvidia-cudnn-cu12` (CTranslate2 ne les installe pas lui-même), et leurs
  dossiers `bin` doivent être dans le PATH au lancement — sinon CTranslate2
  ne voit pas le GPU et `clipper.gpu` retombe sur CPU en silence (ce n'est
  pas un bug, juste l'absence de CUDA détectée).
- Le modèle mediapipe (`blaze_face_short_range.tflite`) est **téléchargé au
  premier lancement** dans le cache utilisateur
  (`~/.cache/clipper/`, donc `%USERPROFILE%\.cache\clipper\` sous Windows) :
  premier `run` plus lent, et il faut le réseau une fois.
- `ank done` doit avoir `.venv\Scripts` en tête du PATH pour trouver `ank`
  et les outils de test qu'il lance (voir *Règles ank* ci-dessus).
