---
id: TASK-aad32da87c1e
type: task
slug: web-tableau-de-bord-en-cours-file-checs-attente
title: "web : tableau de bord (en cours, file, échecs/attente, VOD à confirmer, clips à valider, prochaines publications, coût LLM, matériel)"
created: 2026-09-30T20:43:36Z
author: w-plan-web
status: open
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_web.py
blocked_by: [TASK-f753723ce754, TASK-ae99a2c2f1ce]
done_criteria: |
  tests/test_web.py prouve avec un workspace/state de fixtures : GET /api/dashboard renvoie running (vidéos running avec étape courante et progress), queue (entrées de state/queue.json), failed et queued (avec reason et retry_at), watch_pending (VOD à confirmer de state/watch/*.json, vide si absent), clips_to_review (nombre de clips ready absents de state/publish), next_publications (5 prochaines entrées scheduled toutes chaînes), llm_cost {today, week, by_usage} sommés depuis workspace/*/llm_usage.jsonl (recorded_at dans la fenêtre, fuseau local), hardware {device (clipper.gpu.get_device), vram_used_mb | null} ; une donnée introuvable est null avec une clé <champ>_error en français, jamais 0 muet ; l'écran dashboard de la page affiche chaque section avec état vide explicite et se met à jour sur événement SSE (chaînes de comportement présentes dans le JS). python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

SPEC-c100 E1, T2, T8. Le coût LLM vient du journal llm_usage.jsonl que pipeline écrit déjà (voir pipeline._usage_summary) ; l'agrégation vit dans clipper/web/app.py (lecture de fichiers, pas de logique LLM). L'état matériel lit clipper.gpu et, si torch.cuda est disponible, la mémoire utilisée ; sinon 'CPU' sans erreur.
