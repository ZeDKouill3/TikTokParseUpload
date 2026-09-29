---
id: TASK-be65d6df6225
type: task
slug: banc-vitesse-whisper-batched-vs-s-quentiel-vs-be
title: "banc vitesse whisper : batched vs séquentiel vs beam_size 1 (mesure, pas de changement de code)"
created: 2026-09-29T19:18:04Z
author: nicoc@zedk_ordi
status: open
scope:
  - docs/bench-whisper-vitesse.md
blocked_by: []
done_criteria: |
  docs/bench-whisper-vitesse.md contient le tableau (variante, temps, x temps réel, mots, trous, VRAM, WER vs A) sur l'extrait et sur la vidéo entière, les exemples de divergences et une recommandation argumentée ; aucun fichier de clipper/ modifié ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Transcrire va ~5 min/h de vidéo avec whisper small sur RTX 3050 4 Go. Mesurer, sur l'extrait de 10 min déjà utilisé dans research/bench-whisper/ (voir bench.py, bench_vocab.py pour la méthode et les métriques : temps, nb de mots, trous > 2 s, VRAM), ces variantes avec faster-whisper directement (script dans research/bench-whisper/, dossier local ignoré par git) : A = réglages actuels de clipper.transcribe (lire CONFIG_DEFAULTS : beam_size, vad, initial_prompt vocab) ; B = BatchedInferencePipeline batch_size 8 et 16 ; C = A avec beam_size 1 ; D = B + beam_size 1. Aussi un passage sur une vidéo entière (la plus courte de workspace/ ayant un transcript) pour A vs la meilleure variante. Comparer aussi la qualité : diff de mots avec A (WER approx) et 20 lignes d'exemples de divergences. Une seule charge GPU à la fois (ADR-fb9b). Ne modifie pas clipper/transcribe.py (une autre tâche y travaille).
