---
id: TASK-b20fa3da6834
type: task
slug: transcribe-faster-whisper-plante-no-position-enc
title: "transcribe : faster-whisper plante « No position encodings ... >= 448 » sur ivl0nxa3C7o"
created: 2026-09-28T23:18:31Z
author: orch-main
status: done
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
blocked_by: []
done_criteria: |
  ADR-ad2e, ADR-fb9b. Défaut constaté 2026-09-29 : clipper run https://www.youtube.com/watch?v=ivl0nxa3C7o (podcast LEGEND, ~1 h, 1080p, déjà téléchargé dans workspace/ivl0nxa3C7o/ du dépôt principal E:/ClaudeRandom/TiktokParseUpload) échoue à l'étape transcribe : RuntimeError: No position encodings are defined for positions >= 448, but got position 448 (faster-whisper 1.2.1, CTranslate2 4.8.2, modèle small, beam 5, vad). Le décodeur Whisper a 448 positions ; hypothèse à vérifier en premier (ank-diagnose, cause avant correctif) : _run_whisper passe le vocabulaire LLM à la fois en initial_prompt ET en hotwords, faster-whisper tronque chacun à ~223 tokens, prompt + génération dépassent 448 quand le vocabulaire est long ; autres pistes : boucle d'hallucination, condition_on_previous_text. Attendu : la cause est établie et écrite dans le journal de la tâche (avec la longueur réelle en tokens du prompt construit pour ivl0nxa3C7o, mesurée avec le tokenizer, sans GPU) ; transcribe ne dépasse jamais la fenêtre du décodeur quelle que soit la taille du vocabulaire (prompt borné, borne dans CONFIG_DEFAULTS) ; aucune valeur de secours silencieuse : si le vocabulaire est raccourci, c'est journalisé ; un test de régression (modèle factice, sans GPU ni réseau) échoue avant le correctif et passe après ; toute la suite pytest reste verte. Le GPU est occupé par un lot de rendus : aucun passage réel de faster-whisper sur GPU dans cette tâche, l'essai réel sur ivl0nxa3C7o est fait par l'orchestrateur après merge.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/1d058f9bdbfa@31c031a
    tree: scope/2062d45e1b79
    criteria: a9f03bababf0
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---
