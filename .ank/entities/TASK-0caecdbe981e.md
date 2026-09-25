---
id: TASK-0caecdbe981e
type: task
slug: tape-transcribe-faster-whisper-mot-par-mot-vocab
title: "Étape transcribe : faster-whisper mot par mot + vocabulaire et correction par Claude"
created: 2026-09-25T09:39:37Z
author: claude-plan
status: open
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
blocked_by: [TASK-4ca09185579f, TASK-e4925237bef2]
done_criteria: |
  L'étape extrait l'audio et produit workspace/<video_id>/transcript.json : langue détectée, segments avec start/end et mots {word, start, end, probability} ; modèle whisper et device viennent de la config et de clipper.gpu, le modèle est libéré en fin d'étape ; avant transcription, un vocabulaire de noms propres est demandé à clipper.llm (usage vocab) depuis titre et description et passé en initial_prompt/hotwords ; après transcription, une correction via clipper.llm (usage transcript_fix) ne modifie que le texte des mots, jamais leurs timecodes ni leur nombre (testé) ; un test d'intégration optionnel (marqué, sauté par défaut) transcrit un court extrait avec le modèle tiny.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Sur 2-3 h, la correction se fait par tranches. Claude indisponible : ADR-ad2e562b1810, pas de repli silencieux (échec transitoire, ou vocab/correction désactivés explicitement en config).
