---
id: LOG-6d86aed0fc59
type: log
title: "Vert: 72 tests de tests/test_web_veille.py (calendrier, frise, liste tel, panneau, courbe, colonnes"
created: 2026-10-07T10:15:36Z
author: w-4944
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/veille.js
  - clipper/web/static/screens/veille.css
  - clipper/web/static/screens/settings.js
  - tests/test_web_veille.py
  - docs/GUIDE.md
  - CHANGELOG.md
about: TASK-49449b4fa6d4
seq: 8
schema: 4
version: 1
---

 Ce qui monte, KPI, apercu reglages, settings.js). Classe frise renommee cal-frise (.frise global existe dans style.css). Ecarts assumes: 0 point de courbe -> 'aucune mesure' (pas '1 jour de mesure', faux); liste tel: jours vides seulement ENTRE deux jours avec sortie.
