---
id: TASK-a5f1355da66a
type: task
slug: moments-plancher-min-moments-cap-d-faut-3-sous-l
title: "moments : plancher min_moments_cap (défaut 3) sous le plafond par heure (SPEC-4063 règle 4)"
created: 2026-10-03T12:00:50Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/moments.py
  - rubric.toml
  - tests/test_moments.py
blocked_by: []
done_criteria: |
  tests/test_moments.py vert : plafond = max(min_moments_cap, ceil(max_moments_per_hour x heures)) ; vidéo de 7,5 min avec 4 candidats >= min_score sans chevauchement -> 3 retenus (le 4e écarté avec la raison plafond, qui cite min_moments_cap) ; min_moments_cap = 1 redonne l'ancien comportement ; vidéo de 2 h inchangée (12) ; always_keep_score inchangé ; rubric.toml : min_moments_cap = 3 avec commentaire, validé au chargement (entier >= 1, sinon erreur explicite). Tests unitaires, FakeBackend, sans réseau.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/e53e0d71ddd5@609b9c0
    tree: scope/f0bb2f1d8ebd
    criteria: 72145c12adb8
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Décision utilisateur 2026-10-03 : vidéo j_3Z-KdHRPg (Artus, 7,5 min) n'a gardé qu'1 moment sur 3 bons (64,6 / 61,7 / 61,0) à cause du plafond ceil(6 x 0,125) = 1. Spec : SPEC-40630b2ef66d (successeur de SPEC-0eec), seule la règle 4 change.
