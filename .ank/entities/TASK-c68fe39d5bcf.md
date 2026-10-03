---
id: TASK-c68fe39d5bcf
type: task
slug: commandes-clipper-doctor-pr-requis-d-un-premier
title: Commandes « clipper doctor » (prérequis d'un premier clip, sondes injectables) et « clipper models prefetch » (whisper + mediapipe) (SPEC installeur R5, R7)
created: 2026-10-03T22:51:31Z
author: plan-portable
status: open
scope:
  - clipper/doctor.py
  - clipper/models.py
  - clipper/__main__.py
  - tests/test_doctor.py
  - tests/test_models.py
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  SPEC-38f7761891f6 R5 et R7 tenues, prouvées par tests sans réseau, sans vrai binaire ni modèle : (1) clipper/doctor.py (n'importe aucune étape du pipeline ni clipper.web) : une fonction qui produit un rapport (liste de points avec statut ok / avertissement / manquant, chemin trouvé, remède en français) couvrant Python et version clipper, ffmpeg et ffprobe, claude (présence + connexion lue dans la sortie de « claude auth status »), Chrome (mêmes candidats que clipper.browser.find_chrome, réutilisés sans dupliquer la liste), GPU (clipper.gpu.get_device, paquets nvidia présents ou non), modèle mediapipe et modèle whisper configuré (présents dans leurs caches ou non), config.toml lisible dans le dossier courant, dossiers de données écrivables ; toutes les sondes injectables (which, lanceur de sous-processus, chemins, dossier courant) ; (2) commande « clipper doctor [--json] » : texte une ligne par point, ou JSON ; code de sortie 0 si ffmpeg, claude connecté, config et modèles sont là, 1 sinon ; Chrome et GPU absents = avertissement seulement ; tests : tout présent -> 0, claude non connecté -> 1 avec remède « claude auth login », Chrome absent -> 0 avec avertissement, sortie JSON validée ; (3) clipper/models.py (n'importe aucune étape) : prefetch(config, whisper_factory, face_model_fetch) qui télécharge le modèle whisper de [transcribe] model et le modèle mediapipe dans leurs caches habituels, dit ce qui était déjà présent, et remonte toute erreur (code non nul), jamais de repli ; le câblage des vraies fabriques (celles de clipper.transcribe et clipper.reframe, sans les recopier) se fait dans clipper/__main__.py sous « clipper models prefetch » ; tests avec fabriques simulées (appelées avec le bon nom de modèle, déjà présent = non rappelé, échec propagé) ; (4) docs/GUIDE.md documente les deux commandes. python -m pytest -q tests/test_doctor.py tests/test_models.py tests/test_cli_init.py vert. (6) Une fois les fichiers créés, le scope d'ADR-e1dac9ba2284 et de SPEC-38f7761891f6 est étendu à clipper/doctor.py, clipper/models.py, tests/test_doctor.py et tests/test_models.py (ank amend <id> --scope ...), et ank check ne signale plus de scope mort pour ces deux entités.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Tâche 2 de SPEC-38f7761891f6 (ADR-e1dac9ba2284). L'installeur (install.ps1) appelle « clipper models prefetch » puis « clipper doctor » en fin d'installation ; doctor sert aussi à l'utilisateur quand quelque chose ne marche pas. Faits 2026-10-03 : « claude auth status » et « claude auth login » existent (Claude Code 2.1.281) ; le modèle mediapipe est téléchargé par clipper.reframe dans ~/.cache/clipper/blaze_face_short_range.tflite ; faster-whisper télécharge dans le cache Hugging Face à la construction de WhisperModel(name) (clipper.transcribe, fabrique model_factory) ; Chrome est cherché par clipper.browser.find_chrome. ADR-b16b : doctor.py et models.py ne sont pas des étapes et n'en importent aucune ; seul __main__ (comme pipeline) câble les vraies fabriques. Indépendante de la tâche GPU (T1) : doctor lit clipper.gpu tel qu'il est.
