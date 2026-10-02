---
id: TASK-4e3afe89bb4b
type: task
slug: parts-d-couper-avec-la-grille-r-ellement-utilis
title: "parts : découper avec la grille réellement utilisée par moments (moments.json rubric.path), pas [parts] rubric_path"
created: 2026-10-02T19:45:16Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/parts.py
  - tests/test_parts.py
  - config.example.toml
blocked_by: []
done_criteria: |
  Test : moments.json avec rubric.path = grille gaming (30-90 s) et un moment single de 41,8 s -> parts le garde (aucun rejet de durée) ; même test avec grille standard -> rejet. Test : rubric.path absent ou fichier introuvable -> erreur explicite. Test : [parts] rubric_path dans la config -> erreur claire. Test de cohérence : pour chaque grille embarquée, une durée à la limite acceptée par moments (single_min - tolerance, single_max + tolerance, min_parts*part_min) est acceptée par parts. Tests unitaires seulement, CPU, sans réseau ni LLM réel.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

## Constat (tour 7, point 2)
Vidéo SRzMOzqN-ZM, chaîne `salur` dont le preset met `[moments] rubric_path = "builtin:gaming"` (SPEC-9216 : durées 30-90 s).
- moments.json : `rubric.path` = `clipper/assets/rubric-gaming.toml` ; moment 244,6-286,4 (41,8 s, single) retenu, valide pour la grille gaming.
- parts.json : `rubric.path` = `rubric.toml` (grille standard 60-120 s) ; ce moment est rejeté « durée 41.8 s : ni clip unique (60-120 s)... ».
Cause : `clipper/parts.py` lit sa propre clé `[parts] rubric_path` (défaut "rubric.toml") au lieu de la grille réellement utilisée par l'étape moments. Le preset de chaîne ne règle que `[moments] rubric_path`. Résultat : un moment valide prend une place du plafond par heure puis disparaît au découpage, et des candidats valides (52,8 s, 51 s) avaient été écartés par ce plafond.

## À faire
- parts.py prend la grille de `moments.json["rubric"]["path"]` (déjà résolue par moments, `builtin:*` compris) : une seule grille par vidéo, celle de moments. Pas d'import de clipper.moments (ADR-b16b : une étape n'importe pas une autre étape) ; moments.json est une entrée légitime.
- `rubric.path` absent de moments.json ou fichier introuvable : erreur explicite (ADR-ad2e), jamais de repli sur rubric.toml.
- Supprimer la clé `[parts] rubric_path` de CONFIG_DEFAULTS (et de la doc / config.example si elle y figure) ; si un config.toml la contient encore, erreur claire qui dit qu'elle est remplacée par la grille de [moments].
- Vérifier que la règle de durée de parts (single, série avec reprise de ~3 s, tolérance) n'est jamais plus stricte que celle de `_normalize` dans moments.py pour la même grille : un moment accepté par moments ne doit pas être rejeté par parts pour sa durée. Si elles divergent, aligner parts sur la règle de moments (SPEC-0eec règle 3).
