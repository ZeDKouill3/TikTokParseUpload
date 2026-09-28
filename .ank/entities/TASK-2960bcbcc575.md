---
id: TASK-2960bcbcc575
type: task
slug: qa-cran-noir-mesur-localement-un-fondu-court-de
title: "qa : écran noir mesuré localement, un fondu court de la source n'est pas un rejet"
created: 2026-09-28T17:14:44Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/qa.py
  - tests/test_qa.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 (sZi-qJ-5ptA clip 03) : qa rejette en black_screen un fondu au noir d'environ 0,4 s présent dans la vidéo source (transition de montage), parce que l'IA voit une image noire juste après le changement de plan. black_screen devient une vérification locale (source local) : ffmpeg blackdetect sur le mp4 rendu, rejet seulement si une plage noire dure au moins black_min_seconds (CONFIG_DEFAULTS, 1,0 s par défaut ; seuils de pixel et de part d'image aussi réglables et documentés) ; black_screen retiré de la liste des défauts demandés à l'IA (prompt et schéma) ; échec de ffmpeg = QAError, jamais un verdict de secours (ADR-ad2e) ; tests avec vidéos synthétiques générées par ffmpeg lavfi (fondu noir de 0,4 s -> pas de rejet ; noir de 1,5 s -> rejet black_screen local ; aucune image noire -> rien) marqués skip si ffmpeg absent ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/93bd0449499d@b3a2c74
    tree: scope/571ce9acc3a3
    criteria: 6bbaf23dde62
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
