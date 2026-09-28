---
id: TASK-4b1bb56e9f48
type: task
slug: qa-partie-2-d-une-s-rie-la-reprise-de-3-s-n-est
title: "qa : partie 2+ d'une série, la reprise de ~3 s n'est pas un début en milieu de phrase"
created: 2026-09-28T20:09:26Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/qa.py
  - tests/test_qa.py
blocked_by: []
done_criteria: |
  SPEC-1557 (règle 3 : le recouvrement entre parties est voulu). Pour un clip dont le sidecar a part >= 2 (série), starts_mid_sentence n'est plus demandé à l'IA (absent de l'enum du schéma et de la liste du prompt) et le prompt précise que le clip est la partie N d'une série et reprend volontairement les dernières secondes de la partie précédente. Partie 1 et clip unique : comportement inchangé. Se combine avec les exclusions letterbox existantes (face_cut, subtitle_on_face). Tests : sidecar part 2 -> schéma et prompt sans starts_mid_sentence, mention de la reprise ; part 1 -> starts_mid_sentence toujours demandé ; letterbox + part 2 -> les trois exclus ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/7c1343ffd09a@79afe08
    tree: scope/b6da8d6f273c
    criteria: 532d987b9193
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 6
---
