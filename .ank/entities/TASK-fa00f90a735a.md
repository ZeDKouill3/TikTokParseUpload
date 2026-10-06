---
id: TASK-fa00f90a735a
type: task
slug: s-rie-programm-e-coche-heure-par-clip-date-et-he
title: "Série programmée : coche « Heure par clip » (date et heure libres pour chaque clip sélectionné)"
created: 2026-10-06T15:46:23Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/publish.py
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - tests/test_publish.py
  - tests/test_web.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts, sans réseau, node --check : formulaire « Programmer une série », mode Manuel : coche « Heure par clip » (décochée par défaut). Cochée : chaque clip sélectionné affiche son propre champ date et heure (datetime-local, heure de Paris), pré-rempli avec la date du rythme actuel (début + intervalle, ou à la suite de la dernière programmation), modifiable un par un ; l'aperçu et la création envoient à l'API la date de chaque clip (pas de calcul de créneau dans le JS au-delà du pré-remplissage) ; chaque date est validée côté Python clip par clip avec les refus explicites existants (fenêtre max, avance minimale, plafonds, créneau déjà pris sur le compte, deux clips à la même heure) et le refus s'affiche sous le clip concerné ; les parties d'un clip découpé gardent l'ordre (une date de partie antérieure à la partie précédente est refusée explicitement). Décochée : comportement actuel inchangé. Entrée CHANGELOG [Non publié].
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/0931bcb1ef0d@4e0f3f5
    tree: scope/6451ca673c5f
    criteria: 297c724b7809
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-10-06 : « il faudrait que si on veut, on coche, et pour chaque vidéo sélectionnée dans la liste on ait le choix sur la date et l'heure ». Base existante : Programmer une série (publish.js pubSeriesFormHtml, aperçu pubSeriesRenderPreview, TASK-8c48 après-dernière). Toute heure saisie est l'heure de Paris (pubParisInstant). Usage immédiat : 5 posts/jour programmés sur TikTok (publish_mode scheduled).
