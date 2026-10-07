---
id: TASK-52a07da9ae7e
type: task
slug: jury-action-3-6-tape-action-passages-d-action-pa
title: "Jury action 3/6 : étape action (passages d'action par pics audio et densité de plans, images de scenes décrites par le LLM, coût plafonné), audio avant scenes dans pipeline.STEPS (SPEC-b0f3 R4-R9)"
created: 2026-10-07T13:11:47Z
author: w-juryplan
status: open
scope:
  - clipper/action.py
  - clipper/pipeline.py
  - clipper/scenes.py
  - clipper/llm/__init__.py
  - clipper/assets/config.example.toml
  - tests/test_action.py
  - tests/test_pipeline.py
  - tests/test_scenes.py
  - tests/test_config.py
  - tests/test_llm.py
  - CHANGELOG.md
blocked_by: [TASK-151c500b4625]
done_criteria: |
  Règles R4 à R9 de SPEC-b0f3d20f4191 tenues à la lettre, prouvées par tests sans réseau ni GPU (fixtures synthétiques : audio.json, scenes.json avec frames JPEG minuscules générées par le test, transcript.json, meta.json ; FakeBackend pour le LLM) : (1) clipper/action.py : CONFIG_DEFAULTS avec toutes les clés et défauts de R5, chaque borne invalide refusée par une ActionError qui nomme la clé ; run(video_id, workspace_dir, *, config, force) -> Path ; n'importe aucune autre étape ni clipper.web (test qui inspecte ses imports). (2) Détection R6 : un test avec des pics audio et des coupes concentrés sur deux zones trouve exactement ces deux passages (bornes, score, signaux), fusionne les fenêtres contiguës, coupe un passage trop long à max_passage_seconds, applique le plafond max_passages_per_hour avec la raison dans rejected ; aucun passage : action.json avec passages vide, aucun appel LLM. (3) Images R7 : frames_per_passage images choisies dans scenes.json aux instants prévus, frames_missing quand aucune image n'est dans le passage (WARNING journalisé, aucune extraction ffmpeg : aucun subprocess lancé, test par monkeypatch), plafond max_images_per_hour avec la raison dans rejected. (4) LLM R8 : une planche par lot (clipper.montage), un seul fichier image par appel, usage « action » (ajouté à clipper.llm CONFIG_DEFAULTS usages, modèle fast), schéma validé (index manquant ou en double = SchemaError), lots en parallèle jusqu'à parallel, reprise par action_partial.json, dossier temporaire supprimé même en échec, LLM indisponible = rien d'écrit. (5) Sortie R9 exacte ; enabled = false écrit le fichier vide sans lire audio/scenes ni appeler le LLM ; résultat présent non refait sauf force. (6) pipeline.STEPS = R4 (audio avant scenes, action entre scenes et moments) ; _Run a une méthode action ; un pipeline.json antérieur sans la clé steps.action est relu sans erreur (étape pending) ; tests/test_pipeline.py (PRE_REVIEW, ordre des appels) et le commentaire de clipper/scenes.py mis à jour (audio tourne avant : les pics hors parole sont décodés ; test qui prouve qu'un pic hors parole d'audio.json élargit les fenêtres décodées). (7) config.example.toml documente [action] ; CHANGELOG [Non publié]. (8) python -m pytest -q tests/test_action.py tests/test_pipeline.py tests/test_scenes.py tests/test_config.py tests/test_llm.py vert et pytest complet vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Implémente ADR-4e5789e22495 (ordre des étapes, nouvelle source de candidats) et R4-R9 de SPEC-b0f3d20f4191. Attend la bibliothèque montage (TASK-151c). Détection déterministe, LLM seulement pour décrire les planches ; aucune extraction d'image dans cette étape (scenes voit désormais audio.json). Les workspaces existants gardent leur scenes.json.
