---
id: LOG-0253aa7ef51b
type: log
title: "RÉSULTAT DU VRAI PASSAGE (tentative 5, après correction des 3 bugs) : build zip (vrai"
created: 2026-10-04T00:55:24Z
author: w-a093c293ea3f
scope:
  - tests/test_installer_real.py
  - installer/**
  - AGENTS.md
  - tests/test_installer.py
about: TASK-a093c293ea3f
seq: 10
schema: 4
version: 1
---

 téléchargement uv.exe) -> Installer.bat --cpu --sans-console --sans-raccourci -> présence clipper.exe/ffmpeg.exe/ffprobe.exe/Clipper.bat/install.json(cuda:false)/config.toml/rubric.toml -> clipper doctor exit 0 -> un seul paquet opencv (opencv_contrib_python) dans .venv -> relance Installer.bat (mise à jour) : 'mise a jour' affiché, config.toml identique (contenu + mtime inchangés) -- TOUT CELA A RÉUSSI EN VRAI, durée totale 184 s, app ≈ 913 Mo (CPU, un peu au-dessus des ~700 Mo estimés dans la tâche, probablement python+venv+ffmpeg+deps complets). Seul point non vérifié en vrai sur cette machine : Desinstaller.bat --donnees a refusé (port 8000 réellement occupé par E:\ClaudeRandom\TiktokParseUpload\.venv\Scripts\clipper.exe serve, pid 28856, démarré 2026-10-04 01:53 -- la vraie console du dépôt principal, pas un artefact de mon test) : comportement attendu et correct de R8 (jamais désinstaller sous une console active), pas un bug ; je n'ai pas arrêté cette console (hors de mon scope, process d'une autre session). app/data de ce passage nettoyés manuellement (research/installer-real/run-dyizkpzg supprimé) puisque Desinstaller n'a pas pu le faire. Écueils rencontrés et corrigés en route (voir logs précédents) : (1) Installer.bat/Desinstaller.bat pointaient %~dp0install.ps1 au lieu de %~dp0installer\install.ps1 (jamais testé car le fixture --dry-run mettait tout à plat) ; (2) 'uv pip install' sans --python a réellement pollué le venv de CE dépôt (remonte les dossiers pour trouver un .venv ambiant) -- réparé ensuite avec 'uv pip install -e .[test]' ; (3) app\version.txt jamais écrit par Step11-Finish, donc toute relance se croyait en première installation et 'uv venv' plantait sur l'ancien .venv. Les 3 sont corrigés avec régression (tests/test_installer.py, scope amendé). Suite rapide (tests/test_installer.py + test_build_portable.py + test_installer_real.py en mode sauté) : verte.
