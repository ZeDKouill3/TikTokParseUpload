---
id: LOG-8e0cf8d51f4c
type: log
title: "Plan: jury_calibration.calibrate(traces, config=, now=) ; traces = [{video_id, moment_id,"
created: 2026-09-25T19:05:38Z
author: w-15c1
scope:
  - clipper/jury.py
  - clipper/jury_calibration.py
  - tests/test_jury_calibration.py
about: TASK-15c12de2d29f
seq: 2
schema: 4
version: 1
---

 candidate: entree de deliberate()['candidates']}] (l'etape moments/TASK-8e2f n'ecrit pas encore la trace, donc l'appelant fait le lien candidat->moment). Resultat par moment = moyenne des signaux 0-1 (qa passed/rejected, decision humaine, stats watched_full) ; accord = Spearman note finale du juge vs resultat ; cible 1 +/- corr vers bornes, lissage avec le poids precedent, clamp. Stats CSV (clip_id seul) reliees par les entrees 'result' qui portent le meme clip_id ; hypothese : clip_id unique dans le journal, sinon ambigu -> ecarte, journalise (logging + ignored_stats dans le fichier), jamais devine. 'au-dela d'un minimum' lu comme clips >= min_clips.
