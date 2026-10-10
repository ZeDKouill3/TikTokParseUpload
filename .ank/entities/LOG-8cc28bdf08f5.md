---
id: LOG-8cc28bdf08f5
type: log
title: "green: deleted_post_ids ne retranche que les posts vus <= dernier complet ; pick_details saute"
created: 2026-10-09T23:11:11Z
author: w-e7b175ceb80c
scope:
  - clipper/tiktok.py
  - tests/test_tiktok.py
  - CHANGELOG.md
about: TASK-e7b175ceb80c
seq: 3
schema: 4
version: 1
---

 posted_at > now. Ajuste une assertion existante (fyf_eligible absent = inconnu, post pas lu) : meme intention, « jamais devine ».
