---
id: LOG-f9ff7efbd869
type: log
title: "Correctif applique : pyproject.toml ajoute pytest-xdist>=3 a [project.optional-dependencies].test"
created: 2026-09-30T19:27:35Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
about: TASK-42a46cb23f78
seq: 4
schema: 4
version: 1
---

 et addopts = "-n auto" dans [tool.pytest.ini_options] (ank done, qui lance juste python -m pytest -q, en beneficie sans changer sa commande). tests/conftest.py ajoute cv2.setNumThreads(1) au chargement (evite la double sursouscription decrite ci-dessus). Mesures : sur cette machine, plusieurs autres sessions agent (herdr/claude/NicoTask, visibles via Get-Process, CPU accumulee >1800s chacune) tournaient en parallele pendant tout le diagnostic, hors de mon controle (contrainte 'une seule execution a la fois' = respectee pour MES propres invocations pytest, mais ne m'isole pas des autres workers actifs sur ce PC). Selon la charge partagee observee au moment de la mesure, le temps total mesure a varie de 124.78s (n=8, faible charge, avant le fix cv2) a 180-300s (charge plus lourde, avec/sans le fix). Le mecanisme (baseline serie 275.64s -> parallele) va dans le sens attendu et le dernier run complet apres fix est propre (1166 passed, 25 skipped, 0 echec, 180.66s), mais je ne peux pas certifier <90s de facon fiable tant que d'autres sessions consomment le CPU de cette machine partagee : la mesure est correcte pour ce qu'elle est (charge concurrente reelle), pas une extrapolation. A reverifier sur machine desoeuvree si le chiffre exact <90s doit etre confirme formellement.
