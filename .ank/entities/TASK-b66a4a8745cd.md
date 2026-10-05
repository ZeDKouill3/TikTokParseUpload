---
id: TASK-b66a4a8745cd
type: task
slug: relev-des-stats-tiktok-la-liste-des-publications
title: "Relevé des stats TikTok : la liste des Publications s'arrête aux ~8 premières vidéos (le défilement ne charge pas la suite)"
created: 2026-10-05T18:50:32Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - tests/test_tiktok.py
blocked_by: []
done_criteria: |
  Test rouge puis vert, sans réseau par défaut : constat réel 2026-10-05 : chaque relevé de stats (state/stats/tiktok/<compte>/*.json) contient exactement 8 posts, les plus récents (souvent des programmés futurs), alors que les comptes ont une vingtaine de vidéos en ligne ; list_posts croit la liste finie après un défilement window.scrollTo(body) sans nouvelle ligne. (1) Cause relevée sur la vraie page TikTok Studio (Chrome normal sur le profil state/browser/1ab74eb871e0 avec --remote-debugging-port=9222, connect_over_cdp, LECTURE et défilement seulement, rien d'autre ; méthode research/tiktok-inspect/dump_cdp.py) : conteneur qui défile réellement, chargement paresseux, éventuel nombre total affiché ; consignée dans ank log. (2) Correctif : défilement qui charge vraiment la suite (ex. scrollIntoView de la dernière ligne ou défilement du bon conteneur), fin de liste seulement après 2 tours consécutifs sans nouvelle ligne avec attente suffisante, ou quand le total affiché est atteint ; liste tronquée = arrêt journalisé comme aujourd'hui (R7). (3) Tests avec la fausse page : liste qui ne grandit qu'au 2e tour, liste de 25 posts chargés par paquets de 8, total affiché respecté. (4) Un vrai relevé de contrôle sur un compte (lecture seule) lit toutes les vidéos du compte : nombre noté dans ank log.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/7e16ff2d63f4@9145e80
    tree: scope/6a68b26109c4
    criteria: 8b8692072c18
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Signalé par l'utilisateur 2026-10-05 : « tu ne fais pas le tour de toutes les vidéos quand tu scannes ». Conséquence : la détection des vidéos restreintes (TASK-4777) ne voit pas les vidéos déjà en ligne.
