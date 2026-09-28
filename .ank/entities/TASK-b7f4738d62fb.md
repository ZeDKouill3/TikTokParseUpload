---
id: TASK-b7f4738d62fb
type: task
slug: render-titre-d-cran-avec-emoji-en-couleur-au-des
title: "render : titre d'écran avec emoji en couleur au-dessus de l'image, « Partie N » dessous (letterbox)"
created: 2026-09-28T17:26:39Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/render.py
  - tests/test_render.py
  - pyproject.toml
blocked_by: []
done_criteria: |
  SPEC-6127 : quand le plan de recadrage a layout letterbox, render (1) dessine screen_title (lu dans captions.json) pendant tout le clip, centré dans la bande floue au-dessus du panneau main, bas du bloc à title_gap px (CONFIG_DEFAULTS) au-dessus de l'image, au plus deux lignes (retour à la ligne automatique dans la largeur utile, taille réduite par paliers si ça ne tient pas, jamais tronqué), police Poppins ExtraBold + contour noir, l'emoji en couleur ; le titre est rasterisé en PNG transparent avec Pillow (police emoji couleur : emoji_font dans CONFIG_DEFAULTS, défaut C:/Windows/Fonts/seguiemj.ttf sous Windows, NotoColorEmoji sous Linux ; police absente ou emoji non rendu en couleur = RenderError explicite) puis incrusté par ffmpeg (overlay) ; Pillow ajouté aux dépendances de pyproject.toml ; (2) n'affiche pas l'accroche de 2 s ; (3) affiche « Partie N » sous l'image (part_margin sous le panneau main) seulement si parts_total > 1 ; (4) écrit screen_title et layout letterbox dans le JSON sidecar. Hors letterbox, rendu inchangé. screen_title absent de captions.json en letterbox = RenderError qui demande de relancer captions. Tests : filtre ffmpeg généré (overlay du PNG sur toute la durée, pas de drawtext d'accroche, drawtext Partie seulement si multi-parties) ; PNG du titre (fond transparent, pixels colorés présents à l'endroit de l'emoji, deux lignes pour un titre long) avec skipif si la police emoji est absente ; rendu ffmpeg réel d'un plan letterbox synthétique (skip si ffmpeg absent) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
