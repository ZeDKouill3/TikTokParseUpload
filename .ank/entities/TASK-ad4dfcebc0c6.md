---
id: TASK-ad4dfcebc0c6
type: task
slug: calendrier-de-publication-vues-jour-semaine-mois
title: "Calendrier de publication : vues Jour / Semaine / Mois, toutes les publications du jour dans sa case avec leur nombre, boîtes mises à l'échelle"
created: 2026-10-03T22:41:22Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - clipper/web/static/style.css
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests verts, sans réseau, node --check sur publish.js : écran Publication, sélecteur de vue Jour / Semaine / Mois (Semaine par défaut, choix retenu pendant la session) avec navigation précédent / suivant / aujourd'hui adaptée à la vue. Semaine et Mois : une case par jour qui contient TOUTES les publications du jour (créneaux occupés, hors créneau, publiées, échecs, programmées sur le service), triées par heure de Paris, jamais une publication perdue quand deux tombent à la même heure (test avec 2 posts à la même minute et 10+ posts le même jour) ; en-tête de chaque jour avec le nombre de publications ; la taille des boîtes se réduit avec le nombre de posts du jour pour tenir dans la case (au-delà d'un seuil : boîtes compactes, la case ne déborde pas sur la page). Vue Jour : liste horaire détaillée de la journée (heure, compte, service, titre, statut). Les créneaux réguliers libres restent des cibles de dépôt (glisser un clip approuvé) en Jour et Semaine ; le glisser-déposer existant marche toujours. L'API /api/publish accepte la plage demandée (jour, semaine, mois ; paramètre explicite, refus 422 si invalide), calcule les bornes en Europe/Paris côté Python, renvoie le nombre par jour ; aucune date calculée dans le JS au-delà de l'affichage. Comportement de l'appel actuel (week=) inchangé.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/b876efe463a4@33e15d9
    tree: scope/7aeed30f966c
    criteria: 1a0cd71ed6e4
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-10-03 : « dans le calendrier, faut les publications par jour, et tu scale la taille des petites boîtes des posts dans la case de la journée, mets sur la semaine, le mois et la journée les différents affichages ». Aujourd'hui le calendrier (publish.js pubCalendar, app.py _publish_week_view) est une grille heure x jour : une seule publication par case (byOff écrase), et une ligne par heure distincte ; sans plafond par jour, ça devient illisible. Garder le style visuel actuel (classes cal-*, pubPost). Fuseau : toujours Europe/Paris, jamais l'heure du PC.
