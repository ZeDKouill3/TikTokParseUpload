---
id: TASK-a844a28cdbfe
type: task
slug: captions-l-gende-tiktok-sobre-sans-emoji-ni-supe
title: "captions : légende TikTok sobre (sans emoji ni superlatif clickbait par défaut), comme le titre d'écran"
created: 2026-10-01T07:54:41Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: []
done_criteria: |
  tests/test_captions.py (FakeBackend, aucun réseau) prouve : (1) nouveau réglage CONFIG_DEFAULTS["caption_allow_emoji"] = False : le prompt et la description du champ caption (et hook_text) dans le schéma JSON envoyé au LLM demandent un ton sobre, sans emoji ni mot d'emphase clickbait ; avec l'option à True, au plus 2 emojis simples autorisés, jamais obligatoires ; (2) une réponse LLM dont caption ou hook_text contient un emoji alors que l'option est False est refusée par une erreur explicite (pas de nettoyage silencieux, ADR-ad2e), comme pour screen_title ; (3) cta_line ajoutée en fin de caption n'est pas soumise à ce contrôle (texte fourni par l'utilisateur) ; (4) hashtags inchangés ; (5) les tests existants de test_captions.py restent verts. python -m pytest -q tests/test_captions.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

La légende TikTok (caption) reste kitsch : emojis, « rage totale », superlatifs. Le titre d'écran est déjà sobre (screen_title_allow_emoji, SPEC-6a86 proposée). Appliquer la même sobriété à caption et hook_text, réglable dans CONFIG_DEFAULTS de captions, sans toucher aux hashtags ni à cta_line/cta_hashtags.
