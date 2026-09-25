---
id: TASK-dfe5902ed5cc
type: task
slug: claude-cli-trouver-claude-sous-windows-raccourci
title: "claude_cli : trouver claude sous Windows (raccourci npm claude.cmd)"
created: 2026-09-25T16:52:18Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/llm/claude_cli.py
  - tests/test_llm.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 : sous Windows, subprocess.run(['claude', ...]) lève FileNotFoundError car claude est installé par npm sous forme de raccourci claude.cmd. Le backend claude-cli résout la commande configurée via shutil.which ; si elle aboutit à un raccourci npm .cmd/.bat qui lance un exécutable (node_modules/@anthropic-ai/claude-code/bin/claude.exe à côté du raccourci), il appelle directement cet exécutable, sans passer par cmd.exe (les arguments comme --system-prompt et les chaînes vides ne doivent pas être réinterprétés) ; si rien n'est trouvé, l'erreur actuelle 'introuvable' est conservée ; un chemin complet configuré est utilisé tel quel ; tests sans réseau ni vrai Claude, en simulant l'arborescence npm et la plateforme ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
