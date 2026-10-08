---
id: LOG-c7d856ed421f
type: log
title: "MESURE 08/10: write_veille_report recalcule sur donnees reelles (sans ecrire): v2894088024 Sartar"
created: 2026-10-08T10:51:10Z
author: w-cc7ccc0f7e8c
scope:
  - clipper/veille.py
  - clipper/learning.py
  - tests/test_veille.py
  - tests/test_learning.py
  - CHANGELOG.md
about: TASK-cc7ccc0f7e8c
seq: 2
schema: 4
version: 1
---

 clips_published=5 missing=immature; AION v2894033752/159858/232594/384745/103366 -> not_published (clips existent sous output/v...). bilan.json sur disque (computed_at 2026-10-10, perime) dit no_clips pour ces VOD. Jointure video_id OK (hypothese twitch:/v... REFUTEE). Causes: (a) write_veille_report appele seulement si releve TikTok plus recent que last_sync (run_if_due) -> bilan perime, ecrit avant que les clips existent; (b) bilan n'expose que clips_published, jamais clips produits ; _vod_missing melange 'pas de clip' et 'VOD en cours' ; prompt _bilan_lines montre clips_publies=0 + resultat inconnu (no_clips) -> Claude conclut aucun clip.
