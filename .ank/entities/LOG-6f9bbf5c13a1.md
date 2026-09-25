---
id: LOG-6f9bbf5c13a1
type: log
title: "Lectures prises : (1) exploration AJOUTEE aux retenus normaux (SPEC-53f3 regle 4 : tout moment >="
created: 2026-09-25T19:20:53Z
author: w-022d
scope:
  - clipper/moments.py
  - tests/test_moments.py
about: TASK-022df869d255
seq: 2
schema: 4
version: 1
---

 min_score est garde, en remplacer un violerait la grille) ; nombre = arrondi au plus proche (demi vers le haut) de part x nb de retenus normaux, borne a 0. (2) dispersion = max - min des scores 0-100 des juges au dernier tour ou chacun a note (trace.rounds, tour 2 prime sur tour 1). (3) eligibles : candidats notes non retenus (sous min_score ou chevauchant un meilleur), non vetes, ne chevauchant aucun retenu ni autre exploration ; rejets de grille (SponsorBlock, duree) ne sont jamais candidats. (4) egalite de dispersion departagee par tirage a graine fixe [moments] exploration_seed. (5) reglage [moments] exploration_share (defaut 0.1, hors [0,1] = MomentsError). (6) seulement en selection jury ; re-notation apres vision refait la meme exploration. (7) moments.json garde un bloc exploration {share, seed, target, chosen} : un manque de candidats eligibles est visible, pas silencieux.
