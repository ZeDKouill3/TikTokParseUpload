---
id: TASK-fc561e4dc7e9
type: task
slug: s-rie-programm-e-nombre-de-vid-os-plafonn-au-poo
title: "Série programmée : nombre de vidéos plafonné au pool disponible + coche « Parties ensemble » (ON par défaut) pour les clips découpés"
created: 2026-10-03T20:11:18Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/publish.py
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - tests/test_publish.py
  - tests/test_worker.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests rouges puis verts, sans réseau : (1) l'API rend le nombre de posts disponibles pour le compte choisi (mode auto : clips validés du compte, une partie = un post) ; le champ « Nombre de vidéos » a ce max, l'incrémenteur s'arrête au max, une saisie au-delà est ramenée au max avec un message ; 0 disponible -> champ désactivé + message « valide d'abord des clips ». (2) Coche « Parties ensemble » dans le formulaire série, cochée par défaut. ON (comportement actuel) : une partie n'est jamais programmée sans toutes ses sœurs, à la suite et dans l'ordre (auto : série sautée si elle ne tient pas ; manuel : cocher une partie ajoute les autres, soudées) ; le max du nombre ne compte que des séries entières. OFF : chaque partie est une unité indépendante (auto et manuel) ; les entrées créées portent parts_together=false et le worker ne leur applique pas l'attente « partie N-1 non publiée » (TASK-2456) ; avec ON (ou champ absent, entrées existantes) l'attente reste. (3) preview/create : même valeur de la coche dans l'aperçu et la création ; refus explicites inchangés ; tout ou rien conservé. node --check du JS.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Demande utilisateur 2026-10-03 : « bloque l'incrémenteur de vidéos d'une programmation si on atteint le max du pool ; gère aussi les vidéos en parties : on ne peut pas poster/programmer une partie sans tous ses copains, mais en faire une coche, ON par défaut ».
