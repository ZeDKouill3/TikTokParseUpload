---
id: TASK-ae99a2c2f1ce
type: task
slug: publish-py-file-de-publication-par-cha-ne-approu
title: "publish.py : file de publication par chaîne (approuver/refuser, créneaux automatiques, séries, déplacer, marquer publié, éditions du sidecar)"
created: 2026-09-30T20:43:37Z
author: w-plan-web
status: open
scope:
  - clipper/publish.py
  - tests/test_publish.py
blocked_by: [TASK-585e54dc6eab]
done_criteria: |
  tests/test_publish.py prouve, sur des fixtures output/<id>/<clip>.json et presets/ma_chaine.toml : (1) approve(video_id, clip_id, channel) écrit une entrée SPEC-fc0c §4.1 dans state/publish/<chaine>.json (atomique) ; avec des slots, status scheduled et slot_at = prochain créneau libre après now (injecté) ; les parties d'une série prennent des créneaux consécutifs dans l'ordre des parties ; sans slots, status approved ; (2) approve d'un clip dont le sidecar dit ready=false lève PublishError nommant le clip ; (3) reject d'une partie passe toute la série en rejected ; (4) move(clip, slot_at) refuse un créneau déjà pris (PublishError) et un créneau hors des slots de la chaîne ; (5) mark_published et unschedule (retour à approved) ; (6) edit_caption(video_id, clip_id, description, hashtags) réécrit ces champs et edited_at dans le sidecar, refuse sur une entrée scheduled/published ; (7) list_pending(channel) renvoie les clips ready absents du fichier ; (8) une entrée invalide dans le fichier lève PublishError qui nomme le champ. python -m pytest -q tests/test_publish.py vert, aucun réseau.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

SPEC-fc0c §4, ADR-4f6e §3. Bibliothèque : n'importe aucune étape ni clipper.web (ADR-b16b) ; lit les sidecars SPEC-6a47 et les créneaux via clipper.channel.next_slots. Le re-rendu du titre d'écran n'est pas ici : c'est l'API qui met en file (worker) une action render ciblée sur le clip (voir la tâche pipeline). L'autopost TikTok n'existe pas encore : aucun appel réseau, published seulement par action humaine.
