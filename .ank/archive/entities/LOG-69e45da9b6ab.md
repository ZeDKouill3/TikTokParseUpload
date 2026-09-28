---
id: LOG-69e45da9b6ab
type: log
title: "Lectures prises : (1) ecart = spread des scores ponderes par juge (0-100) > threshold (defaut 20),"
created: 2026-09-25T18:35:41Z
author: w-5c16
scope:
  - clipper/jury.py
  - tests/test_jury.py
about: TASK-5c16c59954ca
seq: 2
schema: 4
version: 1
---

 pas par critere (5 perspectives divergent souvent sur un critere isole, c'est le score qui decide). (2) dissidence = juge dont le score final s'ecarte de la mediane des scores de plus de threshold. (3) quorum n'absorbe que les reponses invalides (SchemaError) ; TransientLLMError/LLMError remontent toujours ; le juge veto est toujours requis (sinon conformite sautee en silence, ADR-ad2e). (4) modele par juge : [jury.judges.<nom>].model injecte dans [llm.usages.jury_<nom>] via une vue de config passee a llm.ask, clipper/llm intouche. (5) debat : chaque juge voit ses notes/argument du tour 1 et les arguments seuls (pas les notes) des autres, anonymes et melanges.
