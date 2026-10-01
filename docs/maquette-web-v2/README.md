# Maquette console Clipper

Ouvrir `index.html` dans le navigateur (double-clic, `file://` suffit). Aucune
étape de build, aucun CDN : polices (Barlow, Barlow Condensed, JetBrains Mono,
OFL) et icônes (Lucide, ISC) sont embarquées. Données factices dans `js/data.js`.

Navigation par hash : `#/tableau`, `#/videos`, `#/videos/<id>`, `#/revue/<id>`,
`#/clips`, `#/publication`, `#/chaines`, `#/chaines/<id>?tab=layout|subs|title|rubric|source`,
`#/stats`, `#/reglages`.

Raccourcis : `Ctrl K` palette, `N` ajouter une vidéo, `G` puis `D/V/C/R/P/S`,
en revue `A` `R` `J` `K` `[` `]` `Espace` `Ctrl Z`, flèches dans l'éditeur.

Paramètres utiles (après `?` dans le hash) : `shot=1` coupe les animations
(captures), `theme=light|dark`, `add=<url>`, `palette=1`, `notifs=1`,
`selftest=1` parcourt tous les écrans et écrit `SELFTEST OK` dans la console.

Captures et outils : `../captures/` (`shoot.sh`, `mobile.html` pour 390×844,
`cdp-selftest.mjs` pour l'autotest en temps réel).
