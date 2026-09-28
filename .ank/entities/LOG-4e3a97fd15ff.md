---
id: LOG-4e3a97fd15ff
type: log
title: "Fix : bornes publiees de moments.json au centieme (SPEC-1557 regle 5), arrondi qui ne recule jamais"
created: 2026-09-28T21:53:57Z
author: w-3c0a
scope:
  - clipper/moments.py
  - tests/test_moments.py
  - clipper/subtitles.py
  - tests/test_subtitles.py
about: TASK-3c0ada196d80
seq: 5
schema: 4
version: 1
---

 (_round2, ceil) dans _public/_judge/_restore/_rescore (remplace floor1/ceil1 dixieme, asymetrique, pour ces sites) ; _span (affichage prompt) et parts[] (clipper/parts.py hors scope) laisses en dixieme, inchanges. subtitles.py : tolerance _WORD_START_TOLERANCE=0.05s dans _words_in_interval, un mot ne s'affiche jamais s'il commence plus de 0.05s avant le debut du clip. Regression tests ajoutes (rouge sans le fix, verifie par git stash, vert avec) : moments (connecteur colle au mot suivant, ne recule pas ; re-notation apres vision sans erreur, bornes inchangees) et subtitles (mot a cheval sur le debut du clip, exclu au-dela de la tolerance, inclus en-deca). ~45 assertions tenth-precision existantes mises a jour au centieme (regle uniforme : borne_dixieme +/-0.05 puisque les phrases de test sont deja alignees au centieme). Suite complete : 772 passed, 8 skipped.
