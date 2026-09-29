---
id: TASK-cb6172b095ca
type: task
slug: web-logo-clipper-favicon-et-en-t-te
title: "web : logo clipper (favicon et en-tête)"
created: 2026-09-29T08:28:43Z
author: orch-main
status: open
scope:
  - clipper/web/static/logo.svg
  - clipper/web/static/index.html
  - clipper/web/static/style.css
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Logo choisi par l'utilisateur le 2026-09-29 (piste C : un C orange #FF8A00 ouvert sur un triangle play blanc, sur carré arrondi #141412, SVG viewBox 512). Attendu : le logo est livré en clipper/web/static/logo.svg (SVG autonome, sans police ni ressource externe) ; index.html le déclare comme icône de la page (<link rel="icon" type="image/svg+xml" href="/static/logo.svg">) et l'affiche dans l'en-tête à gauche du titre Clipper (img avec alt vide, le titre texte reste) ; style.css aligne logo et titre sur une ligne, lisible en clair et en sombre. Aucune logique ajoutée à la page (ADR-09ad). Tests (tests/test_web.py, client de test FastAPI, sans réseau) : GET /static/logo.svg répond 200 avec un type image/svg+xml et un contenu SVG valide (racine svg, viewBox) ; la page / contient le lien icône vers /static/logo.svg et une img de ce logo dans le header. Toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
