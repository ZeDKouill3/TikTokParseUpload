---
id: LOG-441ec62d4cad
type: log
title: Critere contradictoire, verifie par rendu ffmpeg/libass reel (Poppins ExtraBold, Fontsize 120 = em
created: 2026-09-28T18:06:41Z
author: w-a62e
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - clipper/pipeline.py
  - tests/test_pipeline.py
about: TASK-a62ee1d6777a
seq: 4
schema: 4
version: 1
---

 68, \q2\an8, MarginV 1246, 'HEHE\NHEHE') : lignes d'encre 1275-1322 et 1395-1442, soit un pas de 120 px entre lignes. libass (set_font_metrics + FT_SIZE_REQUEST_TYPE_REAL_DIM) avance chaque \N de winAscent+winDescent = Fontsize = 1,762 em, pas de 1,15 em ; aucune balise ASS ne regle l'interligne (\fscy echelle aussi asc/desc ; line_spacing du renderer non expose par le filtre ass de ffmpeg). Donc avec \N explicites, 2 lignes a 68 em occupent 2 x 120 = 240 px (+contour) > 202 px de la zone subtitles (1246-1448) : boite jusqu'a 1486, encre des capitales ligne 2 jusqu'a 1449 avec contour, virgules/Q/J/C cedille jusqu'a ~1465, dans la zone part (1464). La clause 'hauteur (2 x interligne 1.15 + contour) dans y1-y0' et le test 'deux lignes a la taille par defaut tiennent dans la zone par defaut' sont vrais sur le papier et faux a l'ecran (viole SPEC-6127 : aucun texte ne deborde, mesure avec la vraie police).
