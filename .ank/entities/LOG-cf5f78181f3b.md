---
id: LOG-cf5f78181f3b
type: log
title: Decouverte pendant le run reel (PATH reduit a System32, donc 'claude' introuvable -> branche
created: 2026-10-04T01:55:10Z
author: w-4f1d7d1ee341
scope:
  - installer/**
  - tools/build_portable.py
  - tests/test_build_portable.py
  - tests/test_installer.py
  - tests/test_installer_real.py
  - docs/INSTALLATION.md
  - tests/test_docs_installation.py
about: TASK-4f1d7d1ee341
seq: 4
schema: 4
version: 1
---

 installation reelle jamais exercee avant ce task) : Invoke-Step5-Claude plante sur 'Invoke-Expression (Invoke-WebRequest ...).Content' quand le contenu recu est un System.Byte[] plutot qu'une String (ParameterBindingException, CannotConvertArgument). Hors des 16 points c1-m6, mais bloque directement le run reel mandate par le critere (jamais exercee avant car le PATH complet du PC de dev trouvait toujours 'claude' et sautait cette branche -- meme categorie de masquage que C1/C2). Corrige dans le meme fichier (installer/install.ps1, Invoke-Step5-Claude) : decode explicitement en UTF8 si Content est un byte[].
