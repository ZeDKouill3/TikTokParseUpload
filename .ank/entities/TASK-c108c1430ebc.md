---
id: TASK-c108c1430ebc
type: task
slug: apprentissage-3-4-coach-des-prompts-sur-d-clench
title: "Apprentissage (3/4) : coach des prompts sur déclencheur (coach_min_new_cases, coach_min_interval_days) consigné dans state/learning/coach.json, jamais appliqué seul ; GET /api/learning, Adopter (écrit la perspective dans config.toml) / Refuser, section « Apprentissage » de l'écran Statistiques, GUIDE et CHANGELOG (SPEC R6-R7)"
created: 2026-10-07T10:27:51Z
author: w-learnplan
status: done
scope:
  - clipper/learning.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_learning.py
  - tests/test_web.py
  - docs/GUIDE.md
  - CHANGELOG.md
blocked_by: [TASK-7136ef90f0b4]
done_criteria: |
  tests/test_learning.py prouve avec clipper.llm.fake.FakeBackend (llm.use_backend) et des fixtures tmp_path (journal outcomes, sync.json, sidecars avec transcript, moments.json avec traces) : (1) learning.coach_if_due(now, config=) ne fait aucun appel LLM (FakeBackend jamais sollicité) si moins de [learning] coach_min_new_cases (défaut 10) clips scored sont nouveaux depuis coach.json.last_run, ou si moins de [learning] coach_min_interval_days (défaut 7) se sont écoulés depuis last_run (jamais tourné : seul le premier critère compte) ; (2) sinon il appelle jury_coach.propose avec cases = {"video_id", "moment_id", "text": transcript du sidecar, "context": source_title + screen_title, "trace"} pour les clips scored avec trace, judges = perspectives actives de jury, et consigne chaque entrée rendue dans state/learning/coach.json.runs[] {at, cases, judges: [{judge, accepted, reason, version, path, metric, status "proposed" si accepted sinon "rejected", decided_at null, decided_by null}]} et last_run ; (3) ni config.toml, ni clipper/jury.py, ni state/jury_weights.json ne sont modifiés par coach_if_due ; (4) learning.run_if_due enchaîne coach_if_due après le recalibrage, et une CoachError y est écrite dans sync.json.last_error et journalisée une fois. tests/test_web.py prouve : (5) GET /api/learning rend {enabled, links, sync, weights (contenu de state/jury_weights.json ou null), coach: [propositions proposed/adopted/refused avec judge, version, metric, perspective_proposed (lue dans prompts/jury/<juge>/vN.md), perspective_current (config jury), status, decided_at]} ; (6) POST /api/learning/coach/{judge}/{version}/adopt écrit la perspective proposée dans [jury.judges.<juge>].perspective de config.toml par config.write_config (commentaires préservés ou refus explicite comme PUT /api/settings), marque la proposition adopted (decided_at, decided_by "web") et rend la proposition ; .../refuse la marque refused ; proposition inconnue 404, déjà décidée 409, juge conformite 409 ; (7) aucune route de learning ne lance un calcul ni un appel LLM (FakeBackend jamais sollicité, learning.sync jamais appelé). L'écran Statistiques porte une section « Apprentissage » (état de la boucle : dernier versement, dernière erreur en rouge, clips reliés / non reliés par raison, comptes exclus avec la raison ; poids par juge avec accord, cas, raison ; propositions du coach avec métrique avant → après, perspectives en place et proposée, boutons Adopter et Refuser, toast de réponse) : test du JS statique (chargement sans erreur, rendu des trois blocs sur une réponse fabriquée) comme pour les autres écrans de tests/test_web.py. docs/GUIDE.md décrit la section et la validation humaine ; CHANGELOG.md [Non publié] porte l'entrée. python -m pytest -q tests/test_learning.py tests/test_web.py vert ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/14c77c29ab12@c1d31c1
    tree: scope/05db98de0194
    criteria: 8828bb1d6651
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

ADR-c260 point 7 et SPEC associée R6-R7. `clipper/jury_coach.py` (TASK-6595) existe, n'est appelé de nulle part, écrit ses propositions adoptables dans `prompts/jury/<juge>/vN.md` et dit lui-même que « l'adoption réelle du prompt reste un acte séparé » : cette tâche est cet acte, humain, dans l'interface. Les perspectives des juges viennent de `clipper/jury.py` (défauts `_RETENTION`, `_SPECTATEUR`, `_MONTEUR`, `_AVOCAT`, `_CONFORMITE`) surchargées par `[jury.judges.<nom>].perspective` dans `config.toml` : adopter = écrire cette clé, par `config.write_config` comme `PUT /api/settings` (`clipper/web/app.py`, `_settings_merge`, préservation des commentaires).

Coût borné par construction (ADR-c260) : un passage au plus par `coach_min_interval_days`, et seulement avec `coach_min_new_cases` nouveaux cas mûrs ; par passage, un appel « coach » par juge non exclu + le rejeu de `lessons_per_call` cas × 2 versions (règles de `jury_coach`, inchangées). Au rythme mesuré le 2026-10-07 (une dizaine de posts Clipper par semaine sur le compte qui a des vues), le premier passage ne peut pas arriver avant que `min_cases` (5) et `coach_min_new_cases` (10) cas mûrs existent.

Lectures : `clipper/jury_coach.py` (`propose`, forme des `cases`, retour), `clipper/jury.py` (`judges` actifs et perspectives), `clipper/web/app.py` (routes stats, `put_settings`, `write_config`), `clipper/web/static/screens/stats*.js` (écran Statistiques), SPEC-c100 (règles de l'interface), ADR-09ad (aucune logique LLM dans le web). Aucun nom réel dans les tests.
