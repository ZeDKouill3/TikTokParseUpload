---
id: LOG-5ee984b1f92f
type: log
title: "Fix : resolve_command() dans claude_cli.py -- shutil.which(command) ; si le resultat est un"
created: 2026-09-25T16:59:28Z
author: w-dfe5
scope:
  - clipper/llm/claude_cli.py
  - tests/test_llm.py
about: TASK-dfe5902ed5cc
seq: 3
schema: 4
version: 1
---

 .cmd/.bat, appelle directement node_modules/@anthropic-ai/claude-code/bin/claude.exe trouve a cote (jamais cmd.exe, qui developpe %VAR% et avale ^) ; rien trouve -> command inchangee, meme erreur 'introuvable' qu'avant ; chemin complet configure deja resolu -> inchange. build_command() utilise resolve_command(self.command). Tests : 3 nouveaux (shim->exe direct, shim sans exe voisin -> repli sur le shim, chemin complet configure inchange), verifies rouges sans le fix puis verts avec. fake_run mocke shutil.which->None pour rester deterministe (independant du poste). Suite complete : 418 passed, 5 skipped.
