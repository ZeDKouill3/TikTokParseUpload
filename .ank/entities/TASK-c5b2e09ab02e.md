---
id: TASK-c5b2e09ab02e
type: task
slug: reframe-un-cran-d-attente-dessin-ne-bloque-plus
title: "Reframe : un écran d'attente dessiné ne bloque plus la vidéo (faux visages, période unique)"
created: 2026-10-10T10:09:49Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: []
done_criteria: |
  Constat réel 10/10 : la VOD v2895819258 (28 moments) échoue au reframe avec « ReframeError: [reframe] Claude a repondu aucune webcam alors que plusieurs candidats visage stables et persistants existent ([4, 7]) : choix impossible sans deviner ». Planche réelle (lecture seule, ne rien écrire dans workspace/) : E:\ClaudeRandom\TiktokParseUpload\workspace\v2895819258\facecam\period_0.jpg et period_0_zoom.jpg : les 8 images de l'unique période (442 s à 597 s) montrent toutes l'écran d'attente dessiné « J'ARRIVE » (fond rose, nuages, chat dessiné), aucune webcam ; Claude a donc raison ; les candidats 4 et 7 sont des nuages roses que le détecteur de visage a pris pour des visages. Deux causes à établir dans ank log avant de corriger : (a) pourquoi une seule période, échantillonnée seulement sur l'écran d'intro (_find_periods / _period_candidates, ~reframe.py:1707-1900), alors que les moments couvrent toute la VOD ; (b) _stable_face_over_null (~reframe.py:2112) : avec une seule période, _persistent renvoie True par construction, donc deux faux visages stables contredisent Claude et bloquent la vidéo. Correctif dans le respect de SPEC-5b9a (webcam par période, garde-fous locaux journalisés, empty_webcam bloquant en stream_split, aucun repli silencieux ADR-ad2e) : l'échantillonnage d'une période ne doit pas reposer uniquement sur une séquence d'écran d'attente/intro quand des moments existent ailleurs (images prises dans les plages des moments ou réparties sur la vidéo), et/ou le garde-fou ne doit pas imposer une erreur bloquante quand la seule preuve est une période unique dont Claude dit « aucune webcam » ; chaque décision journalisée. Critère CPU (pas de GPU, pas de vrai Claude : FakeBackend) : test de régression rouge avant le correctif reproduisant le cas (candidats synthétiques équivalents ou images dérivées de la planche copiées en fixture réduite), vert après ; tests existants de reframe verts (cas webcam réelle retenue malgré « aucune » toujours couvert, plusieurs persistants sur plusieurs périodes toujours en erreur).
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/4d6762b30c04@a540681
    tree: scope/c415a6f661e4
    criteria: 71c91b7f7e66
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
