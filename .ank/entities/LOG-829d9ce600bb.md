---
id: LOG-829d9ce600bb
type: log
title: "Lecture faite : ADR-b16b limite l'import aux *etapes* pipeline"
created: 2026-10-03T23:04:34Z
author: w-c68fe39d5bcf
scope:
  - clipper/doctor.py
  - clipper/models.py
  - clipper/__main__.py
  - tests/test_doctor.py
  - tests/test_models.py
  - docs/GUIDE.md
about: TASK-c68fe39d5bcf
seq: 3
schema: 4
version: 1
---

 (download/transcribe/scenes/reframe/moments/qa/render/captions/publish...), pas aux modules utilitaires (clipper.browser, clipper.gpu, clipper.config) ni aux libs tierces (faster_whisper, huggingface_hub). Design retenu : (1) clipper/models.py expose mediapipe_model_path(config)/whisper_model_name(config) en lisant config._sections brut (jamais config.section(name), qui importerait le module de l'etape) ; defauts dupliques a l'identique de reframe/transcribe (documentes dans SPEC-38f7 R5 et AGENTS.md). (2) prefetch(config, whisper_factory, face_model_fetch) : whisper_factory(name, local_files_only) et face_model_fetch(local_files_only) suivent le contrat faster_whisper.utils.download_model(local_files_only=...) : prefetch sonde d'abord local_files_only=True (echec => pas present) et ne rappelle qu'alors avec local_files_only=False (download reel, erreur propagee en ModelsError) ; deja present => la fabrique n'est rappelee qu'une fois (jamais une 2e fois). (3) clipper/doctor.py fait son propre chargement de config.toml (ne reutilise pas le Config deja charge par __main__, pour rapporter config.toml absent/invalide comme un point parmi d'autres au lieu de planter avant dispatch) ; 'clipper doctor' est donc gere avant load_config dans main(), comme 'init'. (4) claude : connecte/non lu via le code de sortie de 'claude auth status' (le format texte reel de cette commande n'est pas documente dans le depot, aucune source fiable pour le parser) ; which('claude') absent -> manquant direct. (5) Chrome, GPU, dossiers de donnees ecrivables = avertissement seulement (R7 : seuls ffmpeg, claude connecte, config, modeles determinent le code de sortie).
