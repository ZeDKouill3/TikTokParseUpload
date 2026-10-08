---
id: TASK-cc7ccc0f7e8c
type: task
slug: veille-le-bilan-des-choix-pass-s-transmis-claude
title: "Veille : le bilan des choix passés transmis à Claude compte les vrais clips produits (plus de « les choix AION passés n'ont donné aucun clip » alors qu'ils en ont donné des dizaines)"
created: 2026-10-08T10:48:21Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/veille.py
  - clipper/learning.py
  - tests/test_veille.py
  - tests/test_learning.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Constat réel 08/10 ~12:07 Paris (relevé du jour, état de la veille du 2026-10-08, champ skipped_note de la réponse de Claude) : « Les choix AION passés n'ont donné aucun clip ». Faux : les VOD AION 2 choisies par la veille le 07/10 ont produit des clips (v2894088024 Sartar : 23 clips QA passed, plusieurs publiés ; v2894033752 MrBarbuFriz, v2894384745 Shisheyu, v2894159858, v2894103366 pilote : clips rendus dans output/<video_id>/). (1) Diagnostiquer (ank-diagnose) d'où Claude tire cette info : bilan/historique des choix passés (seen.json, rapport de veille de clipper.learning.write_veille_report, prompt de clipper.veille) et pourquoi les clips de ces VOD n'y sont pas comptés (id source « twitch:2894… » vs id worker « v2894… », VOD encore en traitement au moment du bilan, clips non publiés comptés comme 0, champ absent…). (2) Corriger pour que le bilan distingue clairement : VOD encore en traitement / clips produits (nombre) / clips publiés (nombre) / vues à maturité quand elles existent ; jamais « aucun clip » pour une VOD qui en a produit ; une donnée manquante est dite manquante, jamais comptée 0 (ADR-ad2e). (3) Tests : VOD choisie (id source twitch:…) dont le worker a produit des clips sous v… -> comptée avec ses clips ; VOD en cours -> « en traitement » ; VOD sans clip -> 0 réel. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
