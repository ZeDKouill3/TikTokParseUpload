---
id: TASK-fc6f2bff0aa8
type: task
slug: web-radar-cart-au-d-coupage-parts-json-rejected
title: "web : radar « écarté au découpage » (parts.json rejected) + cartes du calendrier lisibles (2 lignes, info-bulle)"
created: 2026-10-02T19:46:27Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Test API : parts.json avec rejected [{id: 0, reason: ...}] -> /api/videos/{id}/jury marque le moment 0 écarté au découpage avec la raison ; sans parts.json -> sortie inchangée. Test statique : jury-radar.js contient le libellé « écarté au découpage » ; la carte du calendrier porte le titre complet dans un attribut title ; style.css applique un line-clamp 2 au titre des cartes. node --check passe sur chaque JS modifié. Tests unitaires seulement, sans réseau.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

## 1. Radar du jury : « retenu puis écarté au découpage »
Fiche vidéo, radar du jury (`clipper/web/static/screens/jury-radar.js`, données de `GET /api/videos/{id}/jury` = `_jury_view` dans `clipper/web/app.py`, ~l. 340). Aujourd'hui un moment retenu par l'étape moments (`retained: true`) s'affiche « Retenu » même si l'étape parts l'a ensuite écarté : `workspace/<id>/parts.json` a une liste `rejected` d'entrées `{"id", "start", "end", "duration", "reason"}` (ex. `{"id": 0, "start": 244.6, "end": 286.43, "duration": 41.83, "reason": "duree 41.8 s : ni clip unique (60-120 s) ni 2 a 12 parties ..."}`), `id` = id du moment de moments.json.
À faire : `_jury_view` lit parts.json s'il existe et marque ces moments (ex. `cut_rejected: "<raison>"`, nouveau genre `decoupage` dans le libellé `JR_KIND_LABEL`) ; le radar affiche « Retenu par le jury, écarté au découpage : <raison> » dans la liste (groupe Retenus ou groupe propre, au choix, mais visiblement distinct d'un vrai retenu) et dans le détail (`dt`/`dd` l. ~130). parts.json absent (étape pas encore faite) : comportement actuel inchangé.

## 2. Publication, calendrier : cartes trop étroites
Écran Publication, calendrier de la semaine (`.cal`, grille 64px + 7 colonnes, `screens/publish.js` ~l. 155-200, `style.css` ~l. 930). Les titres des clips dans les cartes de créneau sont tronqués à quelques lettres (« Le pl… », « Co… »). À faire : titre sur 2 lignes (line-clamp 2, coupure de mot) + titre complet en info-bulle (`title`) sur la carte ; pas de débordement horizontal de la grille, lisible à 1280 px de large.
