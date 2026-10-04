---
id: TASK-bdd5ada9abee
type: task
slug: vid-o-bloqu-e-en-cours-sans-traitement-r-el-tape
title: "Vidéo bloquée « en cours » sans traitement réel (étape running orpheline après arrêt du serveur/PC) : l'afficher interrompue, permettre Reprendre et Annuler"
created: 2026-10-04T11:03:31Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/web/static/screens/videos.js
  - tests/test_worker.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests rouges puis verts, sans réseau : cas réel 2026-10-04 : workspace/Zk_wshsmq5w/pipeline.json a transcribe = running, state/queue.json vide (worker tué par l'arrêt du serveur ou du PC) ; l'écran Vidéos affiche « en cours » et Annuler répond « aucune video en cours pour 'Zk_wshsmq5w' ». Attendu : (1) une étape running sans entrée running dans la file (ou dont le processus n'existe plus) est rapportée « interrompue » par l'API vidéos, jamais « en cours » ; (2) Annuler sur une vidéo interrompue réussit : l'étape orpheline repasse en pending (ou failed avec raison « interrompue »), journalisé, sans supprimer les étapes finies ; (3) Reprendre remet la vidéo dans la file et repart de l'étape interrompue (les étapes done ne sont pas refaites) ; (4) au démarrage du worker, les étapes running orphelines sont marquées interrompues (journal) ; (5) aucune valeur de secours silencieuse (ADR-ad2e).
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Vu par l'utilisateur 2026-10-04 : « Zk_wshsmq5w sans style, en cours, Annulation impossible aucune video en cours ». Le worker est un enfant de clipper serve : relancer le serveur ou éteindre le PC tue l'étape en cours.
