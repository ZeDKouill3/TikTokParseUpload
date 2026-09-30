---
id: LOG-15fd8c8d7abb
type: log
title: "MESURE (repro_400.py, --debug api --debug-file, 4 appels reels) : le 400 'Found 5' N'EST PAS lie a"
created: 2026-09-30T08:48:05Z
author: w-b384
scope:
  - clipper/llm
  - clipper/jury.py
  - tests/test_llm.py
  - tests/test_jury.py
about: TASK-b3846f023498
seq: 3
schema: 4
version: 1
---

 une race MCP residuelle. Chaque appel opus reel (avec ou sans cache_prefix, avec ou sans --system-prompt-snapshot off) declenche systematiquement au 1er essai un 400 DIFFERENT et jusqu'ici jamais documente : {'type':'invalid_request_error','message':'thread: a maximum of 3 blocks with cache_control may be provided when thread is set -- the fourth marker slot is reserved for the marker the server places on the conversation last cache-eligible block. Found 4.','error_code':'thread_unsupported_request'}. Le CLI capte cette erreur lui-meme (log [WARN] [tether] unsupported_request: resending this turn stateless) et REESSAIE seul en mode stateless -- comportement interne de claude -p, hors de notre code. --json-schema force un echange a 2 tours internes (engine turn 1 end, turns=2, stop=tool_use) meme SANS cache_prefix ni image (confirme aussi turns=3 sur un appel texte brut sans marqueur, pair nocache avocat-1). Sur CE 2e tour interne (deja stateless), le nombre total de blocs cache_control varie de facon non deterministe entre appels par ailleurs identiques : 4 (OK) ou 5 (400 permanent, plus de recuperation automatique, meme message que le bug historique). Preuve : test comparatif repro_400.py (avec notre marqueur cache_prefix -> cache_control, mode stream-json) vs repro_400_nocache.py (memes juges/prompts, SANS notre marqueur, stdin texte brut, --output-format json) : AVEC marqueur, 2 echecs 'Found 5' definitifs sur 2 paires testees (4/4 tentatives) ; SANS marqueur, 0 echec sur 5 paires (10/10 appels reussis), seul le 400 'thread' au 1er essai reste visible (1/10, toujours auto-recupere par le CLI). Conclusion : notre propre bloc cache_control (TASK-2cbb) est le +1 qui fait parfois deborder le budget de 4 blocs que Claude Code s'attribue lui-meme sur son 2e tour interne (mecanisme prive, non documente, hors de notre controle) -- cause hors de notre controle au sens du plan B de la tache. Confirme aussi par un run reel du smoke test AVANT tout correctif (code inchange) : CLIPPER_CLAUDE_INTEGRATION=1 pytest -k jury -v -s => 3 echecs sur 5 (avocat, conformite, monteur), taux d'echec bien pire que le 1/15 rapporte quand les appels s'enchainent vite (plusieurs deliberate() reels de suite dans le meme process).
