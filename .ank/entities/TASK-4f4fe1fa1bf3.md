---
id: TASK-4f4fe1fa1bf3
type: task
slug: parts-parties-de-60-120-s-qui-se-suivent-chacune
title: "parts : parties de 60-120 s qui se suivent, chacune reprend ~3 s de la précédente"
created: 2026-09-28T20:09:26Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/parts.py
  - tests/test_parts.py
blocked_by: [TASK-7758e6074dc6]
done_criteria: |
  SPEC-1557 (règle 3). parts lit max_parts dans rubric.toml [durations] (clé obligatoire, ajoutée par TASK-7758) et CONFIG_DEFAULTS gagne part_overlap_seconds = 3, part_overlap_min = 1, part_overlap_max = 8. Pour un moment multipart, la fin de la partie k est une fin de phrase cut_k (comme aujourd'hui) et la partie k+1 commence avant cut_k : au début de phrase situé dans [cut_k - part_overlap_max, cut_k - part_overlap_min] le plus proche de cut_k - part_overlap_seconds ; à défaut, au début de mot le plus proche de cut_k - part_overlap_seconds dans cette fenêtre ; à défaut, au dernier début de mot avant cut_k (reprise de moins de part_overlap_min) ; à défaut, au premier mot après cut_k (reprise nulle, journalisée) : jamais au milieu d'un mot ni sur un silence de tête. Les phrases de parts portent leurs mots horodatés (transcript.json) pour ces replis. La partie 1 commence au début du moment, la dernière finit à sa fin. Chaque partie, reprise comprise, dure entre part_min - tolerance et part_max + tolerance, et le nombre de parties est entre min_parts et max_parts : part_count_range, le schéma de réponse (minItems/maxItems) et le choix des coupes tiennent compte de la reprise ; aucune suite possible = rejet motivé, jamais de découpage de secours (ADR-ad2e). Chaque partie de parts.json porte overlap (secondes reprises, 0 pour la partie 1) et hook_text = texte à partir de son propre début. Le prompt dit que les parties se suivent et que chaque partie reprend environ part_overlap_seconds s de la précédente, et parle de « Partie N ». Docstrings de parts.py : SPEC-1557 au lieu de SPEC-53f3. Tests : moment de 6 min -> chaque partie k+1 commence 1 à 8 s avant la fin de la partie k, sur un début de phrase quand il en existe un dans la fenêtre ; replis début de mot, reprise courte, reprise nulle ; durées reprise comprise dans les bornes ; 246 s -> 3 parties (2 ne tiennent pas reprise comprise) ; plafond max_parts respecté ; rejet motivé quand impossible ; clip unique inchangé (overlap 0) ; le test existant qui exige des parties bord à bord est réécrit pour la reprise ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/b92e7c119167@21b9cc5
    tree: scope/ee9571ff04c3
    criteria: ce11b2baae3f
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---
