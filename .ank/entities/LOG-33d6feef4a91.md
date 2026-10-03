---
id: LOG-33d6feef4a91
type: log
title: "Complement constate 12:35, video 7.5min 1 tranche ~1000 mots : claude -p transcript_fix sans"
created: 2026-10-03T12:00:58Z
author: w-db6fbbb804eb
scope:
  - clipper/transcribe.py
  - clipper/llm/**
  - tests/test_transcribe.py
  - tests/test_llm*.py
about: TASK-db6fbbb804eb
seq: 1
schema: 4
version: 1
---

 reponse >6min alors que 'claude -p --model sonnet ok' repond en 9s, cause inconnue. Ajout demande : a l'expiration du delai, journaliser (worker.log/events) commande (sans le prompt), taille du prompt, duree, derniers ~2Ko stdout/stderr du sous-processus (lecture non bloquante ou communicate apres kill). Test unitaire avec faux sous-processus qui ne repond pas. Travaille dans le scope existant (clipper/llm/**), n'elargit pas les done_criteria geles.
