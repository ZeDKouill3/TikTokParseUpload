---
id: TASK-28dac454afef
type: task
slug: fiche-clip-historique-des-stats-sans-doublons-li
title: "Fiche clip : historique des stats sans doublons, libellé « Envoyé à TikTok le », valeurs qui ne débordent plus"
created: 2026-10-09T01:17:27Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/clip.js
  - clipper/web/static/style.css
  - tests/test_web.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat sur capture réelle 09/10 (fiche ynvgyqsaKPQ/01, #/clip/ynvgyqsaKPQ/01, 1400 px de large) : (1) l'historique des statistiques liste chaque relevé, dont des séries identiques à quelques minutes d'écart (06:06, 06:09, 06:12... mêmes vues/likes/commentaires ; 20:15, 20:20, 20:23, 20:28 tous à 1056 vues) : liste longue et illisible ; (2) « Publié le mar. 6 oct., 20:35 » s'affiche alors que le créneau est le 7 oct. 21:00 : published_at est l'heure où Clipper a envoyé/programmé le post sur TikTok, le libellé induit en erreur ; (3) le panneau Jury (et les autres panneaux) laisse ses valeurs déborder du bord droit (« inconnu » coupé). (1) Côté serveur (clipper/web/app.py, données de la fiche, pas de calcul dans la page, ADR-49cd/09ad) : l'historique renvoyé ne garde qu'un relevé par changement de valeurs : un relevé dont vues, likes et commentaires sont identiques au précédent gardé est omis ; le dernier relevé est toujours gardé ; ordre chronologique conservé ; aucune valeur inventée (null reste null). (2) clipper/web/static/screens/clip.js : libellé « Envoyé à TikTok le » au lieu de « Publié le » (le créneau reste « Créneau »). (3) Les valeurs des lignes de la fiche ne débordent jamais de leur panneau (retour à la ligne ou ellipse avec title), à 1400 px et à 390 px de large (CSS dans clipper/web/static/style.css, limité aux sélecteurs de la fiche). (4) Tests sans réseau dans tests/test_web.py : historique de 6 relevés dont 3 identiques consécutifs -> 4 lignes, dernier gardé ; libellé présent dans clip.js. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/be2fbd7e61b7@75e7219
    tree: scope/da92348938c3
    criteria: 5828792f00bc
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
