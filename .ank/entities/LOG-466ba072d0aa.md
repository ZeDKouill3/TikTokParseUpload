---
id: LOG-466ba072d0aa
type: log
title: "Repro : subprocess.run(['claude',...]) leve FileNotFoundError (Windows ne cherche que .exe pour un"
created: 2026-09-25T16:56:06Z
author: w-dfe5
scope:
  - clipper/llm/claude_cli.py
  - tests/test_llm.py
about: TASK-dfe5902ed5cc
seq: 2
schema: 4
version: 1
---

 nom sans extension). shutil.which('claude') trouve claude.CMD. Invoquer ce .cmd (bare ou chemin complet) marche pour --version MAIS passe par cmd.exe (CreateProcess lance cmd.exe /c pour un .bat/.cmd) : mesure sur un shim de test, argv 'a%PATH%b' devient la valeur de PATH expansee et 'a^b' devient 'ab' (caret mange), alors qu'un exe direct les laisse intacts. Chaine vide et guillemets ne sont PAS mangles dans ce cas simple, mais %VAR% et ^ le sont -- assez pour confirmer l'hypothese. claude.cmd reel (AppData\\Roaming\\npm\\claude.cmd) fait juste CALL :find_dp0 puis lance node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe %* -- l'executable existe a cote. Fix : resoudre command via shutil.which, si le resultat est un .cmd/.bat, appeler directement l'exe node_modules/@anthropic-ai/claude-code/bin/claude.exe trouve a cote plutot que le shim.
