---
id: LOG-a5c45bcd8c6f
type: log
title: "Repro: LLMRequest n'a aucun champ cache_prefix, et claude_cli n'ecrit jamais cache_control nulle"
created: 2026-09-29T22:50:12Z
author: w-2cbb09ebef58
scope:
  - clipper/jury.py
  - clipper/llm
  - tests/test_jury.py
  - tests/test_llm_claude_cli.py
about: TASK-2cbb09ebef58
seq: 2
schema: 4
version: 1
---

 part (grep vide sur clipper/). Hypothese: le prompt caching Anthropic marque des BLOCS de contenu (cache_control), pas un prefixe textuel a l'interieur d'un seul bloc ; en texte pur (--output-format json, stdin brut), tout le prompt est un seul bloc, donc meme un prefixe identique octet pour octet (deja acquis par TASK-b0fa) ne peut jamais produire un cache hit partiel puisqu'aucune frontiere de bloc n'existe pour le marquer. Source : strings sur claude.exe (npm global) montre la sequence litterale cache_control: {type: ephemeral} et une doc vendee mentionnant qu'un cache_control top-level s'auto-place sur le dernier bloc cacheable -- coherent avec le fait que --input-format stream-json (deja utilise pour les images) transmet des blocs de contenu bruts au format API Anthropic, ou cache_control est un champ par bloc. 2 tests rouges ecrits dans test_jury.py (LLMRequest.cache_prefix inexistant, AttributeError), confirmant que rien ne permet aujourd'hui de marquer une frontiere de cache.
