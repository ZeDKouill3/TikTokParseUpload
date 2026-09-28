---
id: LOG-8d0da45a1b17
type: log
title: "Clauses: (1) server.py lance un serveur stdlib servant la page; (2) tâches groupées"
created: 2026-09-25T09:51:51Z
author: UP60041549@wl0023729
scope:
  - tools/ank-viz/**
about: TASK-7aca619df8f4
seq: 2
schema: 4
version: 1
---

 en_cours/prêtes/bloquées/faites/fermées avec titre,id,porteur,critère; (3) ADR+specs avec statut; (4) graphe blocked_by en lanes façon git log --graph; (5) branches git locales+distantes, dernier commit, avance/retard sur main, liées à la tâche si le nom contient l'id; (6) données seulement via ank --json et git (runner injecté, testé); (7) auto-refresh; (8) parsing testé sur sorties enregistrées. Découverte: chaque appel ank ~2.5s -> collecte en thread de fond, ank show en parallèle, cache par hash corpus. Python local 3.8 -> stdlib, pas de FastAPI.
