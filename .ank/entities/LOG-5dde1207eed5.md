---
id: LOG-5dde1207eed5
type: log
title: "Implémenté : _validated_units (approved, slot_at None, pas en cours, compte matché ou aucun) +"
created: 2026-10-03T19:24:04Z
author: w-16eeaccfaf09
scope:
  - clipper/publish.py
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - tests/test_publish.py
  - tests/test_web.py
about: TASK-16eeaccfaf09
seq: 2
schema: 4
version: 1
---

 _eligible_units marqué validated=False ; available_series_clips combine les deux pools ; preview_series filtre le pool auto sur validated+compte, message clair si used==0 ; app.py expose 'validated' au GET manuel ; publish.js affiche le badge Validé et le nouveau texte du formulaire auto. 149 tests test_publish.py + 529 tests test_web.py verts (dont 678 au total avec les series).
