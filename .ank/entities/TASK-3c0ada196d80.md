---
id: TASK-3c0ada196d80
type: task
slug: un-clip-ne-fait-entendre-ni-n-affiche-le-connect
title: "un clip ne fait entendre ni n'affiche le connecteur retiré (Donc...) : borne de début arrondie vers le bas"
created: 2026-09-28T20:09:38Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/moments.py
  - tests/test_moments.py
  - clipper/subtitles.py
  - tests/test_subtitles.py
blocked_by: [TASK-7758e6074dc6]
done_criteria: |
  SPEC-ef7c (règle 1). Défaut constaté 2026-09-28 sur sZi-qJ-5ptA : le connecteur « Donc » (mot 2428.38 s, mot suivant « est » à 2428.54 s) est retiré par moments, mais la borne start est arrondie au dixième vers le bas (2428.5) : la fin de « Donc » reste dans le clip 03 et le sous-titre affiche « DONC EST-CE NORMAL » (qa l'a rejeté en starts_mid_sentence) ; idem clip 05. Attendu : quand moments retire un connecteur, la borne start du moment n'est jamais antérieure à la fin du dernier mot du connecteur et ne dépasse pas le début du mot suivant (arrondi au dixième choisi dans cet intervalle ; si l'intervalle ne contient aucun dixième, le début exact du mot suivant) ; et subtitles n'affiche jamais un mot dont le début précède le début du clip de plus de 0,05 s. Test de régression reproduisant les horodatages ci-dessus (connecteur retiré, mot suivant 0,16 s après) : start dans l'intervalle et premier mot sous-titré = « est » ; un mot qui commence avant le début du clip n'est pas sous-titré ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 2
---
