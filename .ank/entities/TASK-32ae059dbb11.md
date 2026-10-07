---
id: TASK-32ae059dbb11
type: task
slug: apprentissage-1-4-rattacher-apr-s-relev-les-post
title: "Apprentissage (1/4) : rattacher après relevé les posts TikTok aux clips Clipper sans id de post (programmés, lien introuvable) : clipper/learning.py (link_posts, link_if_due), publish.attach_post, appel par le worker, raisons visibles dans state/learning/links.json"
created: 2026-10-07T10:24:36Z
author: w-learnplan
status: done
scope:
  - clipper/learning.py
  - clipper/publish.py
  - clipper/worker.py
  - tests/test_learning.py
  - tests/test_worker.py
  - tests/test_publish.py
blocked_by: []
done_criteria: |
  Nouveau module clipper/learning.py (bibliothèque : n'importe ni clipper.web ni une étape ; CONFIG_DEFAULTS avec au moins state_dir = "state/learning", enabled = true, link_window_h = 12). tests/test_learning.py prouve sur tmp_path (sidecars, state/stats/tiktok/<compte>/*.json et file de publication fabriqués, aucun réseau ni navigateur) : (1) learning.link_posts(account, config=) relie un sidecar output/<video_id>/<clip_id>.json dont tiktok_post.account vaut le compte et tiktok_post.id est null au post relevé du compte (tiktok.read_history + merged_posts) dont la légende correspond selon la règle de tiktok.find_post_link (légende + hashtags du sidecar et légende relevée compactées par tiktok._squash, l'une commençant par l'autre) et dont posted_at est à moins de link_window_h heures de tiktok_post.publish_at : id et url du post écrits dans le sidecar (tiktok_post.id, tiktok_post.url, tiktok_post.linked_by = "stats", tiktok_post.linked_at ISO 8601, note conservée) et dans l'entrée de publication par la nouvelle fonction publique publish.attach_post(video_id, clip_id, channel, post_url=, post_id=, state_dir=) qui refuse (PublishError) d'écraser un post_id déjà renseigné différent ; (2) zéro candidat ou deux candidats et plus : sidecar et entrée intacts, et state/learning/links.json porte pour ce clip {"video_id", "clip_id", "account", "reason": "none" | "ambiguous", "matches": [post_id...], "checked_at"} ; (3) un post déjà porté par l'id d'un autre sidecar du même compte n'est jamais candidat, et un sidecar dont tiktok_post.id est déjà renseigné n'est jamais modifié ; (4) après rattachement, tiktok.list_videos(account) rend pour ce post clip = {video_id, clip_id} et outside_clipper = False ; (5) un sidecar illisible est une learning.LearningError qui nomme le fichier, jamais ignoré ; (6) learning.link_if_due(now, config=) ne traite que les comptes TikTok dont le dernier fichier de relevé est plus récent que links.json.last_run[compte] (ou jamais traités), écrit last_run, et rend la liste des rattachements faits ; (7) le retour de link_posts et links.json comptent reliés / non reliés par raison. tests/test_worker.py prouve que Worker.tick appelle learning.link_if_due à chaque tour (point d'appel injectable comme stats_fetcher), qu'une LearningError y est journalisée une fois (log.error) sans arrêter le worker, et que [learning] enabled = false ne fait rien. python -m pytest -q tests/test_learning.py tests/test_worker.py tests/test_publish.py tests/test_tiktok.py vert ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/44be637a5dcf@c18fb09
    tree: scope/3c87854ee0c0
    criteria: ce9d0e46f436
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Prérequis de toute la boucle d'apprentissage (ADR proposé « Boucle d'apprentissage branchée sur les relevés réels », SPEC associée R1) : sans lien post → clip, aucune statistique n'est exploitable.

Mesure du 2026-10-07 (orchestrateur, lecture seule du dépôt) : 94 sidecars portent `tiktok_post`, 81 avec un id de post retrouvé dans `state/stats/tiktok/`, 13 sans id (11 « post programmé : son adresse publique n'existe pas encore », 2 « publication réussie mais lien du post introuvable sur la page Publications »). Sur le seul compte qui a des vues, 10 posts depuis le 2026-10-01 viennent de Clipper : 2 reliés, 8 non reliés ; l'écran Statistiques les montre `clip = null`, `outside_clipper = true`.

Cause : `tiktok.result()` cherche le lien juste après la publication (`find_post_link`) ; un post programmé n'a pas encore d'adresse, et le lien d'un post immédiat n'est parfois pas encore affiché ; rien ne rattache après coup, alors que le relevé des Publications (SPEC-47e2) voit ces posts quelques heures plus tard avec leur id et leur légende.

Lectures : `clipper/tiktok.py` (`find_post_link`, `_squash`, `_published_posts`, `_clip_links`, `read_history`, `merged_posts`, `list_videos`), `clipper/publish.py` (`mark_published`, `_read_sidecar`/`_write_sidecar`, `_locked`), `clipper/worker.py` (`tick`, `_stats_due`, `stats_fetcher` injectable), ADR-b16b (bibliothèque, pas une étape), ADR-ad2e (jamais deviné : ambigu = non relié, raison écrite), ADR-35b7 (état en JSON sous state/, écriture atomique `channel_mod.atomic_write_json`).

Hors périmètre ici : versement dans outcomes, calibration, coach, bilan de veille (tâches 2/4 à 4/4). Aucun nom réel de compte ou de chaîne dans les tests.
