---
id: TASK-e7b175ceb80c
type: task
slug: tiktok-un-post-programm-vu-apr-s-le-dernier-rele
title: "TikTok : un post programmé vu après le dernier relevé complet n'est plus « supprimé », et un post futur n'est plus lu en détail"
created: 2026-10-09T22:52:41Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/tiktok.py
  - tests/test_tiktok.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat et preuve : research/reviews/perf-0910.md (local ; scripts de preuve sous research/reviews/scratch-perf-0910/). (Important 1) tiktok.deleted_post_ids = tous les post_id de l'historique moins ceux du dernier relevé complet : un post vu seulement dans un relevé opportuniste POSTÉRIEUR au dernier complet (ex. les publications programmées par Clipper) est déclaré supprimé -> caché de list_videos, video_detail lève « supprimée de TikTok », zero_view_alerts le saute (18 faux supprimés sur 21 le 09/10). Correctif : ne retrancher que les posts vus dans un relevé fait au plus tard au dernier relevé complet (un post vu après le dernier complet n'est jamais déclaré supprimé). (Mineur 4) pick_details lit en détail les posts programmés pas encore en ligne et stocke avg_watch_s 0.0, watched_full 0.0, new_followers 0 (mesure inventée, ADR-ad2e) : exclure de pick_details les lignes dont posted_at (heure de Paris naïve, comparer comme read_fyf_notice) est dans le futur. Tests CPU sans réseau : historique fixture (complet puis opportuniste avec un post nouveau) -> pas supprimé, list_videos le montre, video_detail le rend ; vraie suppression (vu avant le complet, absent du complet) toujours détectée ; post futur jamais choisi par pick_details. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
