---
id: TASK-746b5e0ddca7
type: task
slug: transcribe-batchedinferencepipeline-batch-size-8
title: "transcribe : BatchedInferencePipeline batch_size 8 (x4,9 plus rapide, banc docs/bench-whisper-vitesse.md)"
created: 2026-09-29T20:07:50Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
  - tests/test_subtitles.py
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  transcribe utilise BatchedInferencePipeline avec batch_size de CONFIG_DEFAULTS (défaut 8), séquentiel si batch_size <= 1 (testé avec un faux modèle) ; test sous-titres sur texte peu ponctué vert ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/58517cf3f4f1@77ce5bb
    tree: scope/ef00c55df2ca
    criteria: cc2172250859
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

Appliquer la recommandation du banc TASK-be65 : faster-whisper BatchedInferencePipeline, batch_size=8, beam_size=5 inchangé, mêmes options (vad, word_timestamps, initial_prompt vocab). Nouveau réglage CONFIG_DEFAULTS (ex. batch_size = 8 ; 0 ou 1 = mode séquentiel actuel). Un seul modèle en VRAM (ADR-fb9b). Point de vigilance du banc : ponctuation/majuscules moins riches en batched ; vérifier que subtitles (découpe en lignes, ponctuation), transcript_fix et moments n'en dépendent pas d'une façon qui casse : ajouter un test sur une transcription peu ponctuée qui traverse la découpe des sous-titres. Lancement réel optionnel sur une vidéo de workspace/ (skipif par défaut, CLIPPER_REAL_MODELS=1).
