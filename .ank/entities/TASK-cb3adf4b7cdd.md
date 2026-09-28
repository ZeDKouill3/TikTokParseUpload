---
id: TASK-cb3adf4b7cdd
type: task
slug: captions-m-me-titre-de-publication-pour-toutes-l
title: "captions : même titre de publication pour toutes les parties, suffixé « (Partie N) »"
created: 2026-09-28T19:02:48Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: []
done_criteria: |
  Décision utilisateur 2026-09-28 : pour un moment multipart, le titre de publication (champ title de captions.json, texte posté sur TikTok, pas affiché dans la vidéo) est le même pour toutes les parties, suivi de « (Partie N) ». Même mécanique que screen_title (TASK-4078) : title est demandé à l'IA une seule fois, avec la partie 1 ; pour les parties suivantes, le schéma et le prompt ne le demandent plus (le prompt cite le titre déjà choisi comme contexte). Le titre de base est gardé, et chaque clip reçoit title = base + ' (Partie ' + str(part) + ')' (la partie 1 aussi). La longueur max demandée à l'IA pour la base tient compte du suffixe pour que le title final respecte title_max_chars. Clip unique (parts_total = 1) : aucun suffixe, comportement inchangé. caption, hashtags et hook_text restent demandés par partie. Aucune valeur de secours (ADR-ad2e). Tests (FakeBackend) : moment en 3 parties -> titles « X (Partie 1) », « X (Partie 2) », « X (Partie 3) » avec un seul appel dont le schéma exige title ; clip unique sans suffixe ; longueur finale <= title_max_chars ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
