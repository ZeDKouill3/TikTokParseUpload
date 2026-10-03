---
id: LOG-a9d638e30a9e
type: log
title: "Smoke reel (sans mock) : clipper doctor/models prefetch dans %TEMP% ont debusque un vrai bug -"
created: 2026-10-03T23:17:22Z
author: w-c68fe39d5bcf
scope:
  - clipper/doctor.py
  - clipper/models.py
  - clipper/__main__.py
  - tests/test_doctor.py
  - tests/test_models.py
  - docs/GUIDE.md
about: TASK-c68fe39d5bcf
seq: 4
schema: 4
version: 1
---

 subprocess.run(['claude','auth','status']) echoue sur Windows (FileNotFoundError) car claude s'installe comme un raccourci npm .cmd, non resolu par un Popen direct. Fix : _check_claude reutilise clipper.llm.claude_cli.resolve_command (meme contournement que le backend claude-cli, jamais recopie) avant d'appeler 'run'. Verifie en reel ensuite : doctor tout vert avec claude connecte, chrome, gpu cuda, config, modeles whisper/mediapipe deja en cache (prefetch 'deja present' sur les deux, 0 reseau).
