---
id: LOG-b70b516c1ef1
type: log
title: "pourquoi le rectangle visage (h142) < boite detectee (~164px, cf. task) : _stable_face (tolerance"
created: 2026-09-29T15:41:36Z
author: w-65192877dbe0
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-65192877dbe0
seq: 5
schema: 4
version: 1
---

 centre 40px) fusionne dans le meme support des detections de tailles tres differentes au meme endroit -- ex. keyframes WVjOSRFWm4c t=10s [1565,74.5,1700.5,202.5] h=128 (toute la fenetre facecam encadree) vs t=25s [1578.5,126,1668.5,216] h=90 (visage seul dans la photo) vs t=30s [1586,224.5,1651.5,290] h=65.5 : centres distants de ~40px, a la limite de la tolerance, donc parfois regroupes dans le meme 'visage stable'. Le median par coordonnee (np.median) sur ce melange de boites de tailles differentes donne un rectangle (h=71 ici) qui ne correspond a aucune detection reelle et sous-estime la taille typique -- d'ou bh=71*2=142 (stream_face_height=0.5), trop petit. Non corrige ici (hors done_criteria, qui ne demandait qu'une verification) : avec le correctif de cette tache, ce chemin de repli n'est de toute facon plus emprunte pour WVjOSRFWm4c (les bords sont maintenant trouves directement). Reste un defaut potentiel pour une video qui tomberait en repli complet (3+ bords manquants) : a traiter dans une tache separee si observe en pratique.
