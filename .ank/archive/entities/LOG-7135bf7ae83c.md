---
id: LOG-7135bf7ae83c
type: log
title: "Fix : _back_up (moments.py) recule la 1re phrase tant qu'elle s'ouvre sur un connecteur de"
created: 2026-09-28T17:10:52Z
author: w-3170
scope:
  - clipper/moments.py
  - tests/test_moments.py
about: TASK-317015cc3ee6
seq: 3
schema: 4
version: 1
---

 CONFIG_DEFAULTS['leading_connectors'] (casse/ponctuation/apostrophe courbe ignorees, 'que' couvre qu'), borne haute = _duration_bounds (tolerance comprise, comme _normalize) ; sinon rejet motive sans final_score. Applique dans _normalize (avant jury : le jury juge le texte recule, un rejete ne lui est jamais envoye) et dans _rescore (recul -> bonus complet recalcule + SponsorBlock reverifie, ou rejet ; before/after portent start si deplace). Regression : 27 tests rouges sur HEAD:clipper/moments.py, verts avec le fix ; suite complete 646 passed 8 skipped. Rejeu sur sZi-qJ-5ptA : #0 683.3->681.6 (44.4 s, accroche 'Ah'), #6 4878.2->4875.7 (21.7 s), #7 'C'est pour ca qu'on...' 5968.5->5963.2 (40.0 s), #10 3666.3->3662.3 (41.4 s). Observation hors scope : pour #6 la phrase d'avant est un fragment 'de l'orientation sexuelle de la victime.' car split_sentences coupe a chaque fin de segment whisper sans ponctuation.
