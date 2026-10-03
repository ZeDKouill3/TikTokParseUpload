---
id: TASK-b82ee001ec52
type: task
slug: scripts-installer-installer-bat-install-ps1-11-t
title: "Scripts installer/ : Installer.bat + install.ps1 (11 étapes, --dry-run testable), Desinstaller.bat, lanceur Clipper.bat généré, PREMIER-CLIP.txt (SPEC installeur R2, R3, R6, R8)"
created: 2026-10-03T22:51:31Z
author: plan-portable
status: open
scope:
  - installer/**
  - tests/test_installer.py
blocked_by: [TASK-f6c495f901c0, TASK-c68fe39d5bcf]
done_criteria: |
  SPEC-38f7761891f6 R2, R3, R4 (côté installeur), R6, R8 tenues, prouvées par tests pytest qui exécutent les scripts en --dry-run (powershell -NoProfile -ExecutionPolicy Bypass, skipif powershell absent) sur des dossiers temporaires, sans réseau ni téléchargement : (1) installer/Installer.bat, installer/install.ps1 (Windows PowerShell 5.1 : ni &&, ni ??, ni opérateur ternaire ; sans élévation), installer/Desinstaller.bat, installer/desinstaller.ps1, installer/Clipper.bat.template, installer/PREMIER-CLIP.txt ; (2) install.ps1 implémente les 11 étapes de R3 dans l'ordre, options --app, --data, --cpu, --cuda, --sans-console, --dry-run ; en --dry-run il affiche une ligne par étape avec les chemins et décisions résolus et n'écrit ni ne télécharge rien (test : dossiers temporaires inchangés après le run) ; (3) tests de décision en --dry-run : sans nvidia-smi dans le PATH -> extra cuda non installé et ligne « CPU », avec un nvidia-smi simulé (script dans un dossier temporaire mis en tête du PATH) -> [cuda], --cpu l'emporte ; app\version.txt absent -> « première installation », présent avec version inférieure ou égale -> « mise à jour » et .venv listé en suppression, présent avec version supérieure -> refus explicite et code non nul ; data existant avec config.toml -> aucune ligne d'écriture sous data sauf PREMIER-CLIP.txt, clipper init non appelé ; (4) Clipper.bat.template, une fois rempli (fonction testée en --dry-run qui affiche le résultat), met app\ffmpeg\bin et app\.venv\Scripts en tête du PATH, se place dans data, lance clipper serve si le port 8000 n'écoute pas, ouvre http://127.0.0.1:8000 ; (5) desinstaller.ps1 --dry-run : liste app et Clipper.lnk, ne liste data qu'avec --donnees, refuse si le port 8000 écoute (test avec un socket local ouvert par le test) ; (6) chaque échec d'étape a un message en français qui nomme le remède (test : --dry-run avec --cuda ET --cpu -> message d'options incompatibles, code non nul) ; (7) PREMIER-CLIP.txt dit en français comment faire un premier clip depuis la console. python -m pytest -q tests/test_installer.py vert. (8) Une fois les fichiers créés, le scope d'ADR-e1dac9ba2284 et de SPEC-38f7761891f6 est étendu à installer/** et tests/test_installer.py (ank amend <id> --scope ...), et ank check ne signale plus de scope mort pour ces deux entités.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---

Tâche 3 de SPEC-38f7761891f6 (ADR-e1dac9ba2284), cœur de l'installeur. Lire d'abord tools/setup.ps1 (style PowerShell 5.1, vérifications de prérequis, candidats Chrome) et Clipper.bat (logique netstat / start / timeout à reprendre dans le gabarit). Le mode --dry-run est la preuve : il doit passer par le même code de décision que le vrai run (une seule fonction par étape, qui reçoit un drapeau DryRun), sinon les tests ne prouvent rien. Les étapes réseau (uv python install, uv pip install, ffmpeg, installeur claude, prefetch) ne sont jamais exercées par les tests par défaut ; le test réel unique est une autre tâche. Épingler l'URL et le sha256 de l'archive ffmpeg dans install.ps1 avec un commentaire disant comment les renouveler. Mise à jour : .venv supprimé puis recréé, python/ et ffmpeg/ gardés. Aucun nom de personne ni de chaîne réelle dans les fichiers (dépôt public).
