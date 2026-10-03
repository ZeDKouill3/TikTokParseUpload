---
id: TASK-5d378e43fda0
type: task
slug: installeur-ffmpeg-pingl-sur-une-version-immuable
title: "Installeur : ffmpeg épinglé sur une version immuable (l'URL BtbN « latest » change chaque jour, le sha256 casse)"
created: 2026-10-03T23:53:52Z
author: nicoc@zedk_ordi
status: open
scope:
  - installer/install.ps1
  - tests/test_installer.py
blocked_by: []
done_criteria: |
  Tests verts, sans réseau par défaut : install.ps1 télécharge ffmpeg depuis une URL qui désigne une version FIGÉE (ex. GitHub Release GyanD/codexffmpeg tag de version, archive essentials ou full win64, ou une release BtbN datée et non « latest »), avec son sha256 réel ; l'URL et le sha256 sont deux constantes en tête de fichier, avec le mode d'emploi pour les renouveler. Le sha256 est obtenu en téléchargeant une fois l'archive pendant la tâche (seul usage réseau autorisé, noté dans ank log avec la taille et la commande). L'archive extraite fournit ffmpeg.exe et ffprobe.exe sous app\ffmpeg\bin (adapter l'extraction à la structure réelle de l'archive choisie, vérifiée sur l'archive téléchargée). Test : l'URL ne contient ni « latest » ni « master », et le --dry-run affiche cette URL ; tests installer existants verts.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Relevé par l'orchestrateur à la relecture de TASK-b82e : FFMPEG_URL = .../releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip ; les builds « latest » de BtbN sont reconstruits chaque jour, donc le sha256 épinglé devient faux en un jour et l'installation échoue pour tout le monde. ADR-ad2e : l'échec reste explicite (pas de repli sans vérification du hash).
