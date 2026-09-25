---
id: TASK-e116dad45d8f
type: task
slug: tape-qa-contr-le-qualit-du-clip-rendu-par-claude
title: "Étape qa : contrôle qualité du clip rendu par Claude"
created: 2026-09-25T09:39:47Z
author: claude-plan
status: open
scope:
  - clipper/qa.py
  - tests/test_qa.py
blocked_by: [TASK-7291d843d843, TASK-e4925237bef2]
done_criteria: |
  Pour chaque clip rendu, l'étape extrait quelques images (début, milieu, fin, une par changement de plan) et la transcription du clip, demande à clipper.llm (usage qa) les défauts (visage coupé, sous-titre sur un visage, début en milieu de phrase, accroche faible, écran noir) et écrit qa.status passed ou rejected avec issues dans le JSON du clip ; un clip rejeté n'est jamais marqué prêt (testé avec le backend fake) ; des vérifications mécaniques locales (durée, résolution, silence initial > 1 s) complètent l'avis du LLM.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
