---
id: TASK-c8df7a5a7cf3
type: task
slug: jury-action-6-6-test-de-bout-en-bout-des-deux-st
title: "Jury action 6/6 : test de bout en bout des deux styles gaming action vs témoins, test réel optionnel sur un extrait court (CLIPPER_ACTION_REAL), documentation (SPEC-b0f3 R15, R17, R18)"
created: 2026-10-07T13:12:42Z
author: w-juryplan
status: open
scope:
  - tests/test_pipeline.py
  - tests/test_action_real.py
  - README.md
  - AGENTS.md
  - docs/**
  - CHANGELOG.md
blocked_by: [TASK-68b60853b195, TASK-45501314501d]
done_criteria: |
  (1) Test de bout en bout de tests/test_pipeline.py (FakeBackend, fixtures synthétiques, aucun réseau ni GPU) : un run en mode auto avec un preset [moments] rubric_path = "builtin:gaming-action", candidates = "transcript+action", [action] enabled = true enchaîne audio avant scenes, action avant moments, produit action.json puis un moments.json dont au moins un moment retenu a source « action » et dont le rejet d'un monologue porte la raison du seuil éliminatoire ; un second run avec un preset classic (builtin, candidates transcript, action désactivée) produit un action.json vide et un moments.json sans source « action » et sans appel « action » (compte des appels). (2) tests/test_action_real.py (SPEC-b0f3 R17) : sauté par pytest.mark.skipif tant que CLIPPER_ACTION_REAL != "1" ; lit CLIPPER_ACTION_REAL_VIDEO ; copie l'extrait dans un workspace temporaire, enchaîne audio, scenes, action puis moments en « transcript+action » avec la config réelle (vrai claude), vérifie action.json (au moins un passage avec images décrites, images_sent <= ceil(max_images_per_hour x durée/3600), llm_calls dans la borne de R18) et qu'au moins un candidat de source action est noté ; pytest -q par défaut le compte dans les skipped. (3) Documentation : README (étape action, réglages [action], [moments] candidates, grille gaming-action, les clés des deux presets de R15 en exemple, test réel optionnel) ; AGENTS.md : paragraphe du test réel optionnel (variables d'environnement, jamais par défaut) à côté de celui de l'installeur ; docs/ si une page liste les étapes ou les grilles ; CHANGELOG [Non publié]. (4) pytest complet vert, et python -m pytest -q tests/test_action_real.py affiche 1 skipped sans la variable.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Clôt SPEC-b0f3d20f4191 : preuve de bout en bout (FakeBackend) que les deux nouveaux styles produisent des candidats d'action et que les styles témoins ne changent pas, test réel optionnel jamais lancé par défaut (feedback utilisateur : preuves par tests unitaires, aucun run vidéo complet pour valider), documentation des clés des deux presets (R15) que l'orchestrateur crée localement. Ne touche à aucun fichier de clipper/ : tout le code est en amont.
