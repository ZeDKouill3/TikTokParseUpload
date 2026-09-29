---
id: LOG-0a20c1e5fede
type: log
title: "Clause 2 (prefixe jury) : le schema (--json-schema) est desormais insere dans le prompt AVANT la"
created: 2026-09-29T21:23:32Z
author: w-b0faec889d31
scope:
  - clipper/llm
  - clipper/jury.py
  - clipper/transcribe.py
  - tests/test_llm.py
  - tests/test_llm_claude_cli.py
  - tests/test_jury.py
  - tests/test_transcribe.py
about: TASK-b0faec889d31
seq: 3
schema: 4
version: 1
---

 consigne de role (_schema_block, dans _round1_prompt/_round2_prompt), et rendu identique pour tout juge d'un meme modele configure (_model_veto_flags) : un juge sans veto dont le modele partage un juge a veto (ex. spectateur/conformite, tous deux 'fast' par defaut) repond aussi sur veto/veto_reason, ignores par _ask sauf pour le vrai juge a veto. test_only_veto_judges_are_asked_for_a_veto renomme/adapte (le veto est demande par groupe de modele, plus par juge seul) ; ScriptedJury (test_jury.py) et fixed_jury (test_jury_calibration.py) lisent desormais request.schema plutot que le nom du juge pour savoir s'il faut repondre sur veto. Clause 3 (usage_log depuis les threads transcribe) : test ecrit (test_llm_usage_log_captures_calls_made_from_fix_threads), VERT des le premier passage sans modification de code -- le module-global _usage_log_path (deja concu pour etre visible d'un thread, cf. docstring de clipper.llm) propage deja correctement depuis _fix_chunks (ThreadPoolExecutor) vers llm.ask() ; aucune regression trouvee sur ce point precis en test unitaire. Suite pytest complete : 952 passed, 8 skipped.
