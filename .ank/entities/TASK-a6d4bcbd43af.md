---
id: TASK-a6d4bcbd43af
type: task
slug: transcribe-correction-du-texte-par-grosses-tranc
title: "transcribe : correction du texte par grosses tranches en parallèle, et reprise sans refaire whisper"
created: 2026-09-25T17:16:52Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
blocked_by: []
done_criteria: |
  La correction transcript_fix découpe la transcription en tranches de fix_chunk_words mots (défaut relevé à 3000) et traite jusqu'à fix_parallel tranches en même temps (nouveau réglage, défaut 4), chaque tranche restant un appel clipper.llm validé contre son schéma ; le résultat est identique à un traitement séquentiel (mêmes mots corrigés aux mêmes positions, ordre des segments conservé), testé avec FakeBackend ; une tranche en échec fait échouer l'étape avec sa raison (pas de repli silencieux, ADR-ad2e) ; le résultat brut de whisper est enregistré (workspace/<video_id>/transcript_raw.json) avant la correction, et une relance après échec de la correction réutilise ce fichier sans relancer whisper (testé avec un whisper simulé qui compte ses appels) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/70bc254f24b3@d7c2f70
    tree: scope/2cd95ec7b957
    criteria: 4916db8a0292
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Essai réel 2026-09-25 (1 h 52, ~18 000 mots) : tranches de 400 mots en série = ~45 appels claude -p de ~25 s (dont ~5 s de démarrage fixe), soit ~20 min. Avec 3000 mots x4 en parallèle : ~2 min. Et un échec de correction obligeait à refaire 6 min de whisper.
