---
id: TASK-ad7de9950fca
type: task
slug: s-rie-auto-message-clair-quand-une-s-rie-valid-e
title: "Série auto : message clair quand une série validée ne tient pas dans N (pas de repli sur « aucun clip validé »)"
created: 2026-10-03T20:35:54Z
author: w-fc561e4dc7e9
status: done
scope:
  - clipper/publish.py
  - tests/test_publish.py
blocked_by: []
done_criteria: |
  Test rouge puis vert, sans reseau : preview_series (mode auto) distingue explicitement (1) aucun clip valide disponible (pool vide) -> message actuel 'aucun clip validé disponible : valide d'abord des clips dans l'écran Clips' inchangé ; (2) au moins un clip/serie valide existe mais aucun ne tient dans count (used reste 0 alors que le pool n'est pas vide, ex. seul clip valide = une serie de 8 parties, count=2) -> nouveau message explicite donnant le nombre de clips valides, leur taille en parties, et count, du type 'X clip(s) validé(s) en Y partie(s) ne tient/tiennent pas dans N places : passe à Y vidéos ou décoche « Parties ensemble »' ; le cas 'seulement N disponible sur M demandé' (used>0 mais used<count) reste inchangé. Cas réel rapporté 2026-10-03 (compte clippyqaniaque) : un seul clip validé, série de 8 parties, count=2, together=True -> l'ancien message ('aucun clip validé') était faux et trompeur.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/7c6deb71758f@66a937a
    tree: scope/87e070302897
    criteria: be27bdd85e0c
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Trouvé pendant TASK-fc561e4dc7e9 (coche Parties ensemble + max du champ Nombre de vidéos), hors de son scope car criterion deja frozen/done. Repro : clipper.publish.preview_series(mode='auto', count=2, ...) avec un seul clip valide = serie 8 parties (parts_total=8, toutes approuvees pour le compte) : _auto_series_units(pool, 2) saute la serie (8 > 2 places), used=0 -> insufficient_reason prend la branche 'used == 0' qui dit 'aucun clip validé disponible : valide d'abord des clips dans l'écran Clips' (clipper/publish.py, preview_series, vers la ligne insufficient_reason). Faux : il y a bien un clip valide, il ne tient juste pas. Distinguer : pool (avant _auto_series_units) vide vs pool non vide mais rien ne tient dans count. Voir TASK-fc561e4dc7e9 pour le contexte de auto_series_capacity / _auto_series_units.
