---
id: TASK-15c12de2d29f
type: task
slug: calibration-des-poids-des-juges-partir-des-r-sul
title: Calibration des poids des juges à partir des résultats réels
created: 2026-09-25T18:38:17Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/jury.py
  - clipper/jury_calibration.py
  - tests/test_jury_calibration.py
blocked_by: [TASK-5c16c59954ca, TASK-a374cfe6d0a1]
done_criteria: |
  clipper.jury_calibration calcule, pour chaque juge, l'accord entre ses notes (trace du jury) et les résultats réels du journal des résultats sur une fenêtre configurée, et en déduit un poids borné (défaut 0,5 à 1,5), lissé, seulement au-delà d'un nombre minimal de clips (sinon poids 1) ; le juge conformité garde toujours le poids 1 ; les poids datés sont écrits dans state/jury_weights.json ; clipper.jury les applique (médiane pondérée) quand le fichier existe ; tests avec données synthétiques (juge bon prédicteur -> poids > 1, mauvais -> < 1, bornes, minimum de clips, conformité fixe) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/787b6b9187d8@286e388
    tree: scope/f8fc842908cf
    criteria: 22df58883a19
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Met en œuvre le point 2 de ADR-1cf0 (proposé). Jamais l'accord entre juges comme vérité.
