---
id: LOG-f3b8d9a0b2fc
type: log
title: "Vert: 22 tests transcribe + suite complete 140 passed. Test d'integration tiny ecrit (skipif"
created: 2026-09-25T11:41:56Z
author: w-0cae
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
about: TASK-0caecdbe981e
seq: 4
schema: 4
version: 1
---

 CLIPPER_WHISPER_INTEGRATION!=1, CLIPPER_WHISPER_CLIP optionnel pour un vrai extrait parle) mais non execute ici : le proxy refuse huggingface.co (Systran/faster-whisper-tiny). Compatibilite verifiee par introspection : transcribe() accepte word_timestamps/beam_size/vad_filter/language/initial_prompt/hotwords, champs Segment/Word/TranscriptionInfo conformes. Choix : correction = liste {i, word} par index local a la tranche, schema additionalProperties=false et i borne -> nombre et timecodes intouchables par construction ; mot corrige contenant un espace = TranscribeError. Vocab demande AVANT de charger whisper, correction APRES liberation (jamais un LLM local et whisper ensemble). Mutation: retirer le reset explicite des references ne rougit pas le test de liberation, car le cadre de _run_whisper meurt au retour ; c'est la structure qui garantit la liberation.
