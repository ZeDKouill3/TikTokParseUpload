---
id: TASK-3b9c141ef2b1
type: task
slug: web-cran-clips-galerie-9-16-sidecar-qa-dition-de
title: "web : écran Clips (galerie 9:16, sidecar, QA, édition description/hashtags, titre d'écran avec re-rendu, approuver/refuser, télécharger, copier)"
created: 2026-09-30T20:44:55Z
author: w-plan-web
status: open
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_web.py
blocked_by: [TASK-f753723ce754, TASK-ae99a2c2f1ce]
done_criteria: |
  tests/test_web.py prouve (publish et worker simulés) : GET /api/clips?channel=&video_id=&status= renvoie chaque clip avec son sidecar, video_url, qa_status, issues, et son statut de publication (à valider | approved | scheduled | published | failed | rejected) ; POST /api/clips/{video_id}/{clip_id}/approve et /reject appellent publish.approve/reject (PublishError donne 409 avec detail) ; PATCH /api/clips/{video_id}/{clip_id} {description, hashtags} appelle publish.edit_caption ; PATCH avec screen_title met en file (worker.enqueue) une action render ciblée sur le clip avec force_steps [render, qa] après confirmation ; POST .../rerender fait de même sans changer le titre ; GET /media/clip/... reste ; l'écran clips de la page contient la galerie 9:16 avec lecteur, le panneau sidecar (titre, description, hashtags, partie N/M, QA), les boutons approuver/refuser (refus d'une partie = confirmation 'toute la série'), télécharger (lien download) et copier description + hashtags (clipboard), l'édition en place avec toast 'Annuler'. python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

SPEC-c100 E4, T4 ; SPEC-fc0c §4.5. Les champs du sidecar sont ceux de SPEC-6a47 (screen_title, description, hashtags, series/part, qa). L'API ne touche jamais un mp4 ni le sidecar elle-même : publish.edit_caption pour le texte, la file pour le rendu.
