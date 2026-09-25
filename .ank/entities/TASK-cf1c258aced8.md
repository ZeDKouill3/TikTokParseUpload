---
id: TASK-cf1c258aced8
type: task
slug: clipper-llm-r-paration-d-une-r-ponse-refus-e-err
title: "clipper.llm : réparation d'une réponse refusée (erreur renvoyée au modèle), appliquée à captions"
created: 2026-09-25T18:33:41Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/llm/__init__.py
  - tests/test_llm.py
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 (sZi-qJ-5ptA, auto) : captions a échoué sur 'texte d'accroche de 10 mots, 8 au plus', contrainte que --json-schema ne peut pas exprimer. llm.ask accepte un contrôle optionnel (callable qui lève SchemaError) appliqué après la validation du schéma ; quand le schéma ou ce contrôle refuse une réponse, ask renvoie au même modèle la demande d'origine, la réponse refusée et le message d'erreur exact, jusqu'à repair_attempts fois (réglage de [llm], défaut 1) ; la réponse réparée est validée de la même façon ; si elle échoue encore, la SchemaError remonte avec la dernière erreur (aucune valeur de secours, ADR-ad2e / ADR-b1c1) ; repair_attempts = 0 garde le comportement actuel ; captions passe ses contrôles (nombre de mots de l'accroche, hashtags) par ce mécanisme ; tests avec FakeBackend (réparation réussie, échec après réparation, message d'erreur transmis, aucun ré-essai sur erreur transitoire) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---

Les autres étapes à contrôles post-schéma (vision indices, parts, qa...) pourront adopter le même paramètre ensuite ; ne pas les modifier ici (autres tâches en cours sur moments/pipeline/jury).
