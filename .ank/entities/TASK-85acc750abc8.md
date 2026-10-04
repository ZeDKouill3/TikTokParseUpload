---
id: TASK-85acc750abc8
type: task
slug: release-v0-4-1-installeur-portable-windows-calen
title: "Release v0.4.1 : installeur portable Windows + calendrier Jour/Semaine/Mois (version, changelog complet, feuille de route, README)"
created: 2026-10-04T10:50:13Z
author: nicoc@zedk_ordi
status: open
scope:
  - pyproject.toml
  - clipper/__init__.py
  - CHANGELOG.md
  - docs/versions.md
  - README.md
  - tests/test_release_docs.py
  - tests/test_readme_assets.py
blocked_by: []
done_criteria: |
  Tests verts (tests/test_release_docs.py, tests/test_readme_assets.py, tests/test_packaging.py, tests/test_docs_installation.py), sans réseau : (1) version 0.4.1 dans pyproject.toml et clipper/__init__.py ; (2) CHANGELOG.md : section [Non publié] vide puis [0.4.1] - 2026-10-04, UNE section longue et complète (pas de fichier de notes séparé) vérifiée contre git log v0.4.0..HEAD : installeur portable (ADR-e1da et SPEC-38f7 ratifiées, zip Clipper-portable-0.4.1.zip à télécharger depuis la Release GitHub, Installer.bat / Desinstaller.bat, dossiers app et données, GPU auto, ffmpeg figé, clipper doctor, clipper models prefetch, extra [cuda], mise à jour par relance, corrections de la relecture), calendrier de publication (vues Jour / Semaine / Mois, toutes les publications du jour en Semaine, nombre par jour en Mois, légende en couleurs), message de série quand une série ne tient pas dans N, tests dépendants de l'heure rendus déterministes, test réel de l'installeur ; sections Keep a Changelog (Ajouté, Modifié, Corrigé...) ; liens de comparaison en bas ([Non publié] -> v0.4.1...HEAD, [0.4.1] -> v0.4.0...v0.4.1) ; (3) docs/versions.md : ligne v0.4.1 « Installeur portable Windows et calendrier Jour/Semaine/Mois » (publiée), v0.5.0 inchangée ; (4) README : badge 0.4.1, renvoi section [0.4.1], et la section d'installation sans outils de développement pointe vers le zip de la Release ; nom de wheel d'exemple en 0.4.1.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Choix utilisateur 2026-10-04 : publier le zip portable dans une v0.4.1. Après merge : l'orchestrateur construit le zip en local (python tools/build_portable.py -> dist/), l'utilisateur pose le tag v0.4.1 et crée la pré-release GitHub avec la section [0.4.1] comme texte et le zip en pièce jointe.
