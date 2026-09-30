---
id: TASK-bc92eb8bde5d
type: task
slug: badge-carre-du-logo-entierement-violet-echantill
title: "Badge : carre du logo entierement violet (echantillonne), sans noir"
created: 2026-09-30T16:59:20Z
author: w-37a3ee2b56c2
status: done
scope:
  - clipper/render.py
  - tests/test_render.py
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Nouveau reglage CONFIG_DEFAULTS badge_logo_fill (couleur, defaut = echantillonnee sur le bord de l'image du logo, ~#9146FF pour le logo Twitch) : le carre du logo (badge_logo_size) est rempli entierement de cette couleur (jamais de noir), glyphe reduit (badge_glyph_scale) centre dedans, que badge_background soit 'black' ou 'none'. Test unitaire : pixel du coin du carre == couleur de remplissage. Controle reel : nouvelles captures PNG dans research/madajel/badge/ (preset research/presets/madajel.toml) montrant le carre violet sans noir. GUIDE mis a jour.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/3b2c3ebb2bd0@47911e7
    tree: scope/b06410708cba
    criteria: 91d290c15bc8
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Retour utilisateur 2026-09-30 sur les captures de TASK-37a3ee2b56c2 (badge fond optionnel) : le carre du logo garde un fond noir autour du glyphe reduit ; l'utilisateur veut ce carre entierement violet (couleur du logo Twitch, echantillonnee dans l'image elle-meme plutot que codee en dur), sans aucun noir, independamment de badge_background.
