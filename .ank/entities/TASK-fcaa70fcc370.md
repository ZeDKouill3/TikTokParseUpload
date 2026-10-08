---
id: TASK-fcaa70fcc370
type: task
slug: moments-un-passage-d-action-dont-la-vraie-parole
title: "Moments : un passage d'action dont la vraie parole commence trop tard est rejeté (parole mesurée sur les mots horodatés, mots géants hallucinés ignorés)"
created: 2026-10-08T22:24:56Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/moments.py
  - tests/test_moments_action.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat réel 08/10 (research/reviews/retention-avis.md §1 et §4 A′) : clip v2894088024/07 publié sur ClippTVFR, 6,5 % regardé (avg_watch_s 2,91 s sur 45 s, 692 vues). Candidat d'action a64 (workspace/v2894088024/action.json, speech_ratio 0,68 calculé sur les segments whisper) alors que les mots horodatés de workspace/v2894088024/transcript.json montrent un seul « mot » de 420 caractères « Tantantan… » (hallucination whisper sur la musique) puis la première vraie parole à +31,4 s du début du clip (4,6 s de parole sur 45 s). (1) clipper/moments.py, construction d'un candidat d'action (_action_candidate ~l.810) : la parole du passage est mesurée sur les MOTS horodatés du transcript (pas les segments) ; un mot sans espace de plus de [moments] action_word_max_chars caractères (CONFIG_DEFAULTS, défaut 40) est ignoré dans ce calcul. (2) Si le passage contient de la parole mais que le premier mot retenu arrive après [moments] action_max_silent_start_s (CONFIG_DEFAULTS, défaut 5) secondes du début du passage, le candidat est rejeté avec une raison explicite nommant le délai, visible dans la liste des rejetés de moments.json et journalisée (ADR-ad2e, aucun repli silencieux). (3) Un passage SANS AUCUN mot retenu garde la règle SPEC-b0f3 R11 (candidat sans parole, hook = description de l'image) : il n'est pas rejeté par cette règle. (4) clipper/action.py et action.json inchangés (speech_ratio garde sa sémantique SPEC-b0f3 R6). (5) Réglages invalides (négatifs, non numériques) = MomentsError explicite. (6) Tests sans réseau (FakeBackend, fixtures de tests/test_moments_action.py) : fixture reproduisant a64 (mot de 400 caractères à +17 s, vraie parole à +31 s sur 45 s) -> rejeté avec raison ; même passage avec parole dès +1 s -> accepté ; passage sans aucun mot -> candidat R11 inchangé ; candidates = "transcript" -> sorties identiques (test témoin existant vert). CHANGELOG [Non publié] Corrigé (réglages nommés).
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/4256d4f6f1a0@3462abf
    tree: scope/74c585836530
    criteria: acde7d038ca2
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
