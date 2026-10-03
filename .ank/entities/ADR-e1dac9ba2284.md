---
id: ADR-e1dac9ba2284
type: adr
slug: installeur-portable-windows-zip-d-amor-age-uv-ex
title: "Installeur portable Windows : zip d'amorçage (uv.exe + wheel), programme sous %LOCALAPPDATA%\\Clipper\\app, données sous Documents\\Clipper"
created: 2026-10-03T22:47:34Z
author: plan-portable
status: proposed
scope:
  - pyproject.toml
  - clipper/gpu.py
  - clipper/__main__.py
  - README.md
  - docs/versions.md
  - Clipper.bat
  - AGENTS.md
constraint: |
  L'installation pour un utilisateur sans outils de développement passe par un seul zip d'amorçage (uv.exe, la wheel clipper, les scripts installer/, l'icône ; jamais Python ni site-packages dedans) dont Installer.bat installe tout le programme sous un dossier app (par défaut %LOCALAPPDATA%\Clipper\app : Python 3.11 et dépendances via uv, ffmpeg, lanceur) et toutes les données sous un dossier distinct (par défaut %USERPROFILE%\Documents\Clipper : config.toml, rubric.toml, workspace/, output/, state/, logs/) que ni une mise à jour (relance d'un zip plus récent, qui remplace app) ni la désinstallation par défaut ne touchent ; CUDA (extra clipper[cuda]) n'est installé que si un GPU NVIDIA est détecté ; Chrome et le CLI claude restent externes (claude installé par l'installeur officiel natif et connecté par l'utilisateur lui-même, Chrome seulement vérifié) ; tout prérequis manquant ou étape échouée est un arrêt explicite en français avec le remède, jamais un repli silencieux (ADR-ad2e) ; aucun test par défaut ne télécharge quoi que ce soit.
schema: 4
version: 2
---

## Contexte
Critère n°1 de la v1.0.0 (docs/versions.md) : sur un PC neuf, arriver à un premier clip sans aide. Aujourd'hui l'installation suppose uv, Python 3.11, ffmpeg, `claude`, `ank` et un dépôt cloné (tools/setup.ps1, README). Un utilisateur sans outils de développement n'y arrive pas.

Mesures sur l'arbre courant (2026-10-03, c41b8e4) : `.venv` = 2,7 Go dont 2,0 Go de paquets nvidia (cublas, cudnn, nvrtc : nécessaires à faster-whisper en CUDA, non déclarés dans pyproject, leurs dossiers `bin` doivent être dans le PATH au lancement) ; ~700 Mo sans CUDA. Modèles téléchargés au premier run : mediapipe (230 Ko, `~/.cache/clipper/`), faster-whisper `small` (~500 Mo, cache Hugging Face). Chrome : vrai Chrome exigé (`channel chrome`, SPEC-9225 R1), jamais un Chromium embarqué. `claude` : CLI à connecter à un compte ; `claude auth login` et `claude auth status` existent (2.1.281). ffmpeg : cherché dans le PATH, aucune clé de config. Tous les chemins de données (config.toml, workspace/, output/, state/, logs/) sont relatifs au dossier courant : lancer clipper avec le dossier de données comme dossier courant suffit, sans changer le code.

## Options écartées
- Zip autonome complet (Python embarqué + site-packages + ffmpeg) : 1 à 3 Go, à reconstruire à chaque release, et Chrome/claude restent externes de toute façon.
- setup.exe (Inno Setup) : seulement un emballage autour de la même logique, SmartScreen sans signature, un outil de build de plus.
- Mise à jour automatique depuis la console, entrée « Programmes et fonctionnalités » : remis à plus tard, non nécessaires au premier clip.

## Décision
- Zip d'amorçage léger (< 150 Mo) construit par `tools/build_portable.py` à chaque release et attaché à la GitHub Release : `uv.exe`, la wheel `clipper-<version>-py3-none-any.whl`, `installer/` (Installer.bat, install.ps1, Desinstaller.bat, desinstaller.ps1, gabarit du lanceur, PREMIER-CLIP.txt), `tools/clipper.ico`, `version.txt`.
- `Installer.bat` (PowerShell 5.1, sans élévation) : vérifie et installe les prérequis, crée `app` et le dossier de données, écrit le lanceur `Clipper.bat` et le raccourci Bureau, exécute `clipper init` dans les données (jamais d'écrasement), précharge les modèles, lance `clipper doctor`, ouvre la console.
- Dossier app jetable, remplacé par une mise à jour ; dossier de données jamais touché sauf demande explicite à la désinstallation.
- CUDA : extra `clipper[cuda]` déclaré dans pyproject, installé seulement si `nvidia-smi` répond (forçable `--cpu` / `--cuda`) ; `clipper.gpu` ajoute les dossiers `bin` des paquets nvidia présents dans le venv au chargement, ce qui rend le lanceur indépendant du PATH.
- Les règles détaillées (contenu du zip, étapes, messages, mise à jour, désinstallation, tests) sont dans la SPEC « Installeur portable Windows ».

## Conséquences
- `tools/setup.ps1` reste l'installation développeur (dépôt cloné, tests, ank) ; l'installeur ne demande jamais `ank` ni git.
- Le critère n°1 de la v1.0.0 devient vérifiable par un test réel optionnel (construction du zip + installation dans des dossiers temporaires), sauté par défaut.
- Tout changement des dossiers de données (noms, emplacement) est un changement de ce contrat : migration explicite (critère n°3 de la v1.0.0).
