---
id: TASK-2d9a5e523b5a
type: task
slug: mineurs-de-la-revue-du-08-10-relev-tiktok-de-l-c
title: "Mineurs de la revue du 08/10 : relevé TikTok de l'écran pris par l'apprentissage, modèle réel de la veille et du coach, llm_usage par vidéo, horodatage UTC du review.json mis de côté"
created: 2026-10-08T13:00:18Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/learning.py
  - clipper/veille.py
  - clipper/jury_coach.py
  - clipper/llm/__init__.py
  - clipper/pipeline.py
  - tests/test_learning.py
  - tests/test_veille.py
  - tests/test_jury_coach.py
  - tests/test_llm.py
  - tests/test_pipeline.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Mineurs vérifiés des revues du 08/10 (détail, fichiers et correctifs proposés : research/reviews/veille-stats.md M1, M2 ; research/reviews/adr.md M2, M3, M5 — gitignorés mais présents dans le dossier principal E:\ClaudeRandom\TiktokParseUpload\research\reviews\, lis-les là). (1) veille-stats M1 : un relevé TikTok lancé depuis l'écran et fini après un tour du worker n'est plus ignoré par l'apprentissage jusqu'au relevé suivant (clipper/learning.py link_if_due : comparaison sur l'instant d'écriture du relevé, pas fetched_at <= last_run). (2) veille-stats M2 : llm.model écrit dans l'état du jour de la veille est le modèle réellement utilisé (résolu comme clipper.llm le résout, via une fonction publique de clipper.llm si besoin, jamais lu à côté). (3) adr M2 : le rejeu du coach des prompts « comme en jugement réel » utilise le modèle du juge concerné. (4) adr M3 : un appel LLM de la veille ou du coach fait par le worker n'est plus compté dans llm_usage.jsonl de la vidéo en reprise (chemin de journal passé explicitement, pas d'état global de module). (5) adr M5 : _set_aside_review horodate en UTC explicite (suffixe Z), plus l'heure locale du PC. Respect ADR-b1c1 (tout LLM via clipper.llm) et ADR-b16b. Tests sans réseau pour chacun des 5 points, rouges avant. CHANGELOG [Non publié] Corrigé. Hors périmètre : adr M4 (réglages codés en dur), déjà M6 corrigé par TASK-6c69.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/fc41c3822b56@982eefb
    tree: scope/9f53b5054fd4
    criteria: ca72d7ca1127
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
