---
id: LOG-bfc7908869ba
type: log
title: "BUG trouvé par le vrai passage : Installer.bat et Desinstaller.bat référençaient %~dp0install.ps1 /"
created: 2026-10-04T00:33:21Z
author: w-a093c293ea3f
scope:
  - tests/test_installer_real.py
  - installer/**
  - AGENTS.md
about: TASK-a093c293ea3f
seq: 5
schema: 4
version: 1
---

 %~dp0desinstaller.ps1 au lieu de %~dp0installer\install.ps1 / %~dp0installer\desinstaller.ps1 (les .ps1 vivent sous installer/ dans le vrai zip R1, jamais testé par le fixture installer_dir qui met tout à plat). Corrigé + régression ajoutée (zip_layout_dir, 2 tests qui invoquent les .bat réels). Relance du vrai passage en cours ; port 8000 déjà occupé sur ce PC par un process python (pid 28348, démarré 2026-10-03 23:13, antérieur à ce test) : probablement la vraie console Clipper de l'orchestrateur — je ne la touche pas. Si la désinstallation finale échoue pour cette raison, ce sera un écueil environnemental documenté, pas un bug du code.
