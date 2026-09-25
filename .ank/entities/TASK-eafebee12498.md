---
id: TASK-eafebee12498
type: task
slug: captions-compter-les-mots-de-l-accroche-sans-la
title: "captions : compter les mots de l'accroche sans la ponctuation isolée"
created: 2026-09-25T19:04:18Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 : 'La nouvelle mode : ils se volent entre eux' (8 mots) a été refusée comme '9 mots, 8 au plus' parce que le ':' isolé compte comme un mot. Le comptage des mots de l'accroche (et le message d'erreur renvoyé au modèle pour réparation) ignore les jetons faits uniquement de ponctuation (: ; ! ? … - – — « » etc.) ; les mots avec apostrophe ou trait d'union (l'heure, peut-être) comptent pour un ; test de régression avec cette phrase exacte et quelques cas de ponctuation française ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/a9592a872cfb@31e5531
    tree: scope/56fccc53a961
    criteria: 0ab8504b792f
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
