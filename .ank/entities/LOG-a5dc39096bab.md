---
id: LOG-a5dc39096bab
type: log
title: "JS : pubCalendar eclate en pubCalendarDay/Week/Month, selecteur de vue (.seg data-range),"
created: 2026-10-03T22:56:05Z
author: w-ad4dfcebc0c6
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - clipper/web/static/style.css
  - tests/test_web.py
about: TASK-ad4dfcebc0c6
seq: 2
schema: 4
version: 1
---

 navigation data-week adaptee au pas (jour/semaine/mois via pubShift/pubShiftMonth), densite des boites (pubBoxClass), toutes les publications d'un jour via d.days (plus de grille heure x jour). Fixture de l'ancien test calendrier mise a jour au nouveau contrat (days[]). 63 tests publish/calendar verts. Reste : CSS boites + tests dedies aux nouvelles fonctions pures + vue Jour/Mois.
