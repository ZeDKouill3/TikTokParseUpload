---
id: TASK-4f1d7d1ee341
type: task
slug: installeur-portable-corriger-les-16-points-confi
title: "Installeur portable : corriger les 16 points confirmés de la relecture Fable (uv/clipper à nu, relance après échec, OpenCV, encodage, désinstallation...)"
created: 2026-10-04T01:23:20Z
author: nicoc@zedk_ordi
status: open
scope:
  - installer/**
  - tools/build_portable.py
  - tests/test_build_portable.py
  - tests/test_installer.py
  - tests/test_installer_real.py
  - docs/INSTALLATION.md
  - tests/test_docs_installation.py
blocked_by: []
done_criteria: |
  Tests verts, sans réseau par défaut : chaque point CONFIRMÉ de research/reviews/installeur.md (C1-C3, I1-I7, M1-M6) est corrigé selon son correctif proposé (ou mieux, justifié dans ank log) et prouvé par un test unitaire qui échouait avant (nommé d'après l'id du point, ex. test_c1_..., en --dry-run ou en lisant les fichiers générés) ; en particulier : uv.exe du zip et clipper.exe du venv installé appelés par leur chemin, jamais à nu (test avec un PATH réduit à System32) ; relance après une première installation interrompue réussit (uv venv --clear ou suppression du .venv) ; overrides OpenCV appliqués hors du dépôt (fichier d'overrides livré dans le zip et passé à uv pip install --override, un seul paquet OpenCV) ; lanceur écrit dans un encodage correct pour un chemin accentué ; message d'erreur visible en double-clic (pause) ; install.json relu à la relance ; désinstallation qui vérifie que app est bien une installation Clipper ; Desinstaller.bat copié dans app ; doc alignée sur le code. Les « douteux » du rapport : vérifiés, corrigés seulement si confirmés, verdict dans ank log. Puis tests/test_installer_real.py lancé UNE fois en vrai (CLIPPER_INSTALLER_REAL=1, autorisé, réseau OK) avec un PATH réduit à System32 + PowerShell (ni uv, ni clipper, ni .venv du dépôt) dans ses sous-processus, dossiers sous research/installer-real/ ; résultat (durée, taille, écueils) dans ank log. Le test réel lui-même impose ce PATH réduit.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Rapport : research/reviews/installeur.md (relecteur r-installeur, Fable, 2026-10-04, review-done 3/7/6). Le test réel de TASK-a093 était passé parce que le PATH du PC de dev contenait uv et le clipper du dépôt (C1, C2).
