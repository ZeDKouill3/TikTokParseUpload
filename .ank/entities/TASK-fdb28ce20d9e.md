---
id: TASK-fdb28ce20d9e
type: task
slug: jury-la-re-notation-apr-s-vision-lit-la-grille-d
title: "Jury : la re-notation après vision lit la grille de moments.json, et l'exploration ne repêche plus un candidat éliminé par [gate]"
created: 2026-10-07T23:47:28Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/moments.py
  - tests/test_moments.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Revue r-pipeline 08/10 (research/reviews/pipeline.md, Important 1 et 2, scripts de preuve research/reviews/scratch-pipeline/repro_b.py et repro_gate_explore.py). (1) moments._rescore utilise la grille enregistrée dans moments.json (previous['rubric']['path'], déjà résolue, comme parts.rubric_path_of et vision._windows) et non settings['rubric_path'] du style : un style dont la grille a changé entre moments et vision ne provoque plus KeyError (cas réel : notes en builtin:gaming, style en builtin:gaming-action -> KeyError: 'action'). Grille enregistrée introuvable -> erreur explicite (MomentsError), jamais de repli sur la grille du style. (2) _select distingue les rejets éliminés par [gate] (SPEC-b0f3 R3, seuil éliminatoire) des autres rejets ; _explore ne puise jamais parmi les éliminés par [gate] (il garde les autres rejets, min_score compris, comme ADR-1cf0 point 4). (3) Tests : rejeu avec grille différente du style -> re-notation sans erreur avec la grille de moments.json ; grille enregistrée manquante -> MomentsError ; exploration avec un candidat gate-éliminé à forte dispersion -> jamais choisi, un candidat min_score à forte dispersion -> choisi. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
