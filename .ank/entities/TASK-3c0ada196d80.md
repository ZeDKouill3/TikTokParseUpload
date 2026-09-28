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
  SPEC-1557 (règles 1 et 5). Défaut constaté 2026-09-28 sur sZi-qJ-5ptA : le connecteur « Donc » (2428.38-2428.54 s, mot suivant « est » à 2428.54 s) est retiré par moments, mais la borne start publiée est arrondie au dixième vers le bas (2428.5) : la fin de « Donc » reste dans le clip 03 et le sous-titre affiche « DONC EST-CE NORMAL » (qa : starts_mid_sentence) ; idem clip 05. Attendu : les bornes publiées de moments.json sont au centième (règle 5) ; quand un connecteur est retiré, start = début exact du mot qui suit le connecteur (jamais avant la fin du connecteur) ; la relecture des bornes publiées (_restore, utilisée par la re-notation après vision) retrouve ces bornes au centième sans erreur ; et subtitles n'affiche jamais un mot dont le début précède le début du clip de plus de 0,05 s. Tests de régression avec ces horodatages : start = 2428.54 et premier mot sous-titré « est » ; re-notation après vision d'un moments.json dont un moment a perdu son connecteur -> pas d'erreur, bornes inchangées ; un mot qui commence avant le début du clip n'est pas sous-titré ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 3
---
