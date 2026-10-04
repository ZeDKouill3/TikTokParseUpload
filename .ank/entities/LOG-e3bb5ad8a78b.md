---
id: LOG-e3bb5ad8a78b
type: log
title: "Douteux du rapport (research/reviews/installeur.md) : verifies, non confirmes, non modifies. (1)"
created: 2026-10-04T01:46:23Z
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
seq: 1
schema: 4
version: 1
---

 claude introuvable juste apres son install officielle (PATH utilisateur vs $env:Path du process) : necessite un reseau reel + un PC neuf, non reproductible ici sans reseau -- laisse en l'etat, le code actuel cherche deja 'claude' via Get-Command apres l'install. (2) OneDrive Known Folder Move sur Documents : pas de redirection sur ce PC de dev, non verifiable sans un PC avec OneDrive KFM actif -- non modifie. (3) 'claude auth status' non connecte, code de sortie non nul : non observable sans compte deconnecte reel -- non modifie, le code gere deja ce cas (Fail explicite). (4) --cpu sur un PC avec GPU NVIDIA : le test reel (TASK-a093, LOG-0253aa) est deja passe sur un PC a GPU avec --cpu, coherent avec AGENTS.md (retombee silencieuse en CPU documentee comme non-bug) -- non modifie. (5) chemin se terminant par un guillemet (--data "C:\Mes Docs\") : limitation connue de l'analyse d'arguments Windows (cmd.exe puis PowerShell), pas specifique a install.ps1, non reproduit ici -- non modifie, a documenter si confirme plus tard sur un cas reel.
