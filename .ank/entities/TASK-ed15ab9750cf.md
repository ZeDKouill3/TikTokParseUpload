---
id: TASK-ed15ab9750cf
type: task
slug: web-cran-cha-nes-liste-cr-ation-dition-d-un-pres
title: "web : écran Chaînes (liste, création/édition d'un preset par formulaire avec valeurs héritées, validation au champ, suppression)"
created: 2026-09-30T20:44:56Z
author: w-plan-web
status: open
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_web.py
blocked_by: [TASK-f753723ce754]
done_criteria: |
  tests/test_web.py prouve (channel simulé ou presets/ temporaire) : GET /api/channels/{name} renvoie le preset brut (ce qui est redéfini), les valeurs effectives fusionnées et, pour chaque section, les CONFIG_DEFAULTS du module (clé, défaut, commentaire de la ligne précédente dans le source si présent) ; PUT /api/channels/{name} passe par channel.save_channel : un ConfigError donne 422 avec detail nommant section et clé ; POST /api/channels crée (nom invalide = 422) ; DELETE demande confirm=true ; GET /api/channels/{name}/slots renvoie les 10 prochains créneaux ; l'écran channels de la page contient la liste (nom, source, surveillance, mode, prochains créneaux), le formulaire par sections ([channel], reframe/agencement, render titre/CTA/badge, subtitles, moments/grille) où chaque champ non redéfini affiche sa valeur héritée grisée avec 'redéfinir', l'erreur au champ, et l'enregistrement avec toast. python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

SPEC-c100 E5 (hors éditeur visuel et aperçu, tâches séparées), SPEC-fc0c §1. Les commentaires des CONFIG_DEFAULTS servent d'aide contextuelle : extraits par inspect.getsource du module, jamais évalués. Le logo de la chaîne ([channel] logo, PNG) s'envoie par POST multipart vers presets/<name>.png.
