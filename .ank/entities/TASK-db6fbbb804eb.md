---
id: TASK-db6fbbb804eb
type: task
slug: transcribe-une-tranche-de-correction-bloqu-e-ne
title: "transcribe : une tranche de correction bloquée ne fait plus tout recommencer (tranches réussies gardées, délai par tranche, 1 re-essai de la tranche)"
created: 2026-10-03T11:27:51Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/transcribe.py
  - clipper/llm/**
  - tests/test_transcribe.py
  - tests/test_llm*.py
blocked_by: []
done_criteria: |
  Tests unitaires verts (FakeBackend, sans réseau) : 1) chaque tranche corrigée réussie est écrite tout de suite sous workspace/<id>/ (clé = hash du texte de la tranche + version du prompt/schéma) et un nouveau passage de l'étape ne redemande que les tranches manquantes (preuve : nombre d'appels au fake) ; 2) délai par tranche réglable ([transcribe] fix_timeout_s, défaut 360 s) passé à clipper.llm sans changer le délai global des autres usages ; 3) une tranche en échec transitoire est relancée une fois tout de suite, seule ; au second échec l'étape échoue explicitement comme avant (TransientLLMError, re-essai planifié), jamais de texte non corrigé substitué en silence ; 4) la transcription Whisper (transcript_raw.json) déjà faite n'est pas refaite au re-essai (le vérifier, corriger si besoin). Réglages dans CONFIG_DEFAULTS.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Constat réel 2026-10-03, vidéo MS5J5C-0qKQ (76 min, 11 758 mots, 4 tranches de 3000 mots, fix_parallel 4) : 3 tranches corrigées en 55 s, 107 s, 175 s ; la 4e (claude -p sonnet) n'a jamais répondu, coupée à 900 s (timeout global llm) -> TransientLLMError, étape transcribe entière en échec, re-essai 5 min plus tard qui refait les 4 tranches (0,62 $ et 15 min perdus). Objectif : perdre au plus une tranche, et la détecter en ~6 min au lieu de 15.
