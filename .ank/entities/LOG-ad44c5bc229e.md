---
id: LOG-ad44c5bc229e
type: log
title: "Repro confirmee : test_usage_makes_one_real_call[layout] echoue de facon intermittente (1 echec sur"
created: 2026-09-30T08:17:46Z
author: w-0d30201398b8
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
  - tests/integration/test_smoke_real.py
about: TASK-0d30201398b8
seq: 2
schema: 4
version: 1
---

 ~5 essais reels), sur plan.tracks=[] (aucun visage detecte). Reponse reelle (research/smoke/smoke.log) : answer={'layout':'single','face':0,'camera':{'x':0,'y':0,'w':0,'h':0},'reason':'Aucun visage detecte...'} -- le modele hallucine face=0 malgre son propre raisonnement disant qu'il n'y a aucun visage. Mesure cle : geometry.single(plan, face) fait required = [tr for tr in plan.tracks if tr.id == face], donc quand plan.tracks est vide, la valeur de face n'a AUCUN effet sur la geometrie produite (required est toujours []). Cause : _check_answer valide face not in ids meme quand ids=[] (aucun visage a choisir), rejetant une reponse sans consequence geometrique reelle -- une contrainte qui ne s'applique pas quand il n'y a rien a valider contre. Fix : clipper/reframe.py _check_answer, guard 'if answer[layout] != facecam_gameplay and ids' avant les checks sur face, au lieu de valider face contre une liste d'ids vide. Le check ignore/camera reste inchange (aucune mesure ne montre le meme probleme dessus). Pas une valeur de secours ADR-ad2e : aucun remplacement silencieux d'un echec, juste une contrainte qui ne s'applique qu'en presence d'au moins un visage candidat -- le comportement geometrique est identique avec ou sans ce guard. Regression test ajoute : tests/test_reframe.py::test_single_with_hallucinated_face_on_an_empty_plan_is_not_a_schema_error, verifie rouge sans le fix (meme erreur SchemaError visage #0 inconnu) puis vert avec. Suite tests/test_reframe.py : 94 passed, 1 skipped.
