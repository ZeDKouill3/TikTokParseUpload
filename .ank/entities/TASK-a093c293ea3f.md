---
id: TASK-a093c293ea3f
type: task
slug: test-r-el-optionnel-de-l-installeur-clipper-inst
title: "Test réel optionnel de l'installeur (CLIPPER_INSTALLER_REAL=1) : zip construit, installé dans un dossier temporaire en CPU, doctor vert, mise à jour, désinstallation (SPEC installeur R9)"
created: 2026-10-03T22:51:34Z
author: plan-portable
status: open
scope:
  - tests/test_installer_real.py
  - installer/**
  - AGENTS.md
blocked_by: [TASK-9623bdba2126]
done_criteria: |
  SPEC-38f7761891f6 R9 (test réel) tenue : (1) tests/test_installer_real.py contient un seul test, sauté par défaut (skipif : variable d'environnement CLIPPER_INSTALLER_REAL absente, ou powershell/uv absents), jamais lancé en CI ; (2) quand il tourne : construit le zip par tools.build_portable.build (vrai téléchargement de uv.exe), le dézippe dans un dossier temporaire, lance Installer.bat --app <tmp>\app --data <tmp>\data --cpu --sans-console, vérifie code 0, présence de app\.venv\Scripts\clipper.exe, app\ffmpeg\bin\ffmpeg.exe et ffprobe.exe, app\Clipper.bat, app\install.json (cuda false), data\config.toml et data\rubric.toml, puis exécute clipper doctor depuis data avec le PATH du lanceur et vérifie code 0 et un seul paquet OpenCV dans le venv ; relance Installer.bat sur le même app (mise à jour) et vérifie que data\config.toml a le même contenu et la même date ; enfin Desinstaller.bat --donnees et vérifie que app et data ont disparu ; (3) le test ne touche jamais le Bureau de l'utilisateur ni %LOCALAPPDATA%\Clipper (option --sans-raccourci, à ajouter à install.ps1 si elle manque, ou raccourci écrit sous --app) ; (4) la commande exacte pour lancer ce test est documentée dans AGENTS.md (section Tests) ; (5) résultat d'un vrai passage sur ce PC consigné par ank log (durée, taille de app, écueils). python -m pytest -q tests/test_installer_real.py vert (sauté) par défaut.
criteria_by: creator
verify: [tests]
schema: 4
version: 2
---

Tâche 6 de SPEC-38f7761891f6 (ADR-e1dac9ba2284) : le seul test réseau du lot, réservé à un passage manuel sur un PC qui a déjà claude connecté (l'étape claude de install.ps1 ne doit alors rien installer ni ouvrir). Compter plusieurs minutes et ~700 Mo (CPU) ; ne pas le lancer en parallèle d'un autre travail lourd. Si install.ps1 doit gagner une option pour ne pas toucher le Bureau, l'ajouter ici avec son test --dry-run dans tests/test_installer.py (scope installer/** inclus pour cela).
