---
id: SPEC-76dc6a1cbccb
type: spec
slug: agencement-stream-split-r-glable-webcam-haut-jeu
title: "Agencement stream 'split' réglable : webcam haut, jeu bas, badge de chaîne, style des sous-titres"
created: 2026-09-30T14:23:30Z
author: w-c42f0db91d65
status: superseded
scope:
  - clipper/reframe.py
  - clipper/render.py
  - clipper/subtitles.py
  - clipper/pipeline.py
references: [ADR-b16b71007578, ADR-fb9bcb1e98f5, ADR-ad2e562b1810, SPEC-6a867ae54f94]
supersedes: SPEC-8257564db9db
ratified: 68343eeb44f6
verified:
  - by: nicoc@zedk_ordi
    at: 2026-09-30T14:35:58Z
schema: 4
version: 3
---

## Objet
Succède à SPEC-8257 (choix du format stream par clip, sur la présence de la
webcam plutôt que sur la seule détection du visage) : reprend ses règles 1 et
2 à l'identique (ci-dessous) et ajoute un second agencement visuel pour les
clips en stream, choisi par config, à côté de celui de SPEC-3a88 qui reste le
défaut. Décision utilisateur 2026-09-30 : pour une streameuse Twitch,
reproduire le style de ses propres montages TikTok (webcam en haut sur
environ un tiers de la hauteur, jeu en bas sur le reste en pleine largeur,
badge de chaîne à la jonction, sous-titres gras majuscules blanc avec le mot
courant en violet et contour noir, sans titre d'écran ni carte de fin).
Maquette placée par l'utilisateur dans l'éditeur local
`research/madajel/editeur/editeur.html` (hors dépôt), JSON nettoyé
`research/madajel/agencement/madajel-tiktok.json`, rendus ffmpeg validés
`research/madajel/agencement/rendu-5400.png` et `rendu-2400.png` (fichiers
locaux, hors dépôt, cités pour mémoire — voir `research/BONNES-PRATIQUES.md`).

## Règles 1 et 2 (reprises à l'identique de SPEC-8257)
1. Localisation (une seule fois par vidéo) : le visage reste l'indice de
   départ, avec un seuil distinct de celui de la règle 2 et par défaut plus
   bas que 0,8 (réglable, `facecam_localize_min_share`, défaut 0,1) : le
   rectangle de la facecam est celui où un visage apparaît à la même
   position (tolérance `facecam_tolerance`) sur au moins ce seuil des images
   clés, dans une zone fixe de moins d'un quart de l'image
   (`facecam_max_area`) ; et/ou en retrouvant directement les bords d'une
   incrustation statique (gradient soutenu et constant sur les contours,
   `facecam_edge_*`), même quand le visage n'y est stable que sur une faible
   part des images clés. Le rectangle (et ses bords s'ils sont trouvés) est
   ensuite figé pour toute la vidéo.
2. Choix du format par clip (une seule fois, tout ou rien) : un clip est en
   stream si le rectangle de webcam y est présent et vivant sur au moins une
   part réglable de ses images clés (`facecam_clip_min_share`, défaut 0,8),
   SANS exiger la détection du visage sur ces images clés. Présent et vivant
   sur une image clé : (a) contenu non noir ; (b) bords retrouvés au même
   endroit qu'à la localisation ; (c) non figé (diffère de l'image clé
   précédente du même clip). Un clip où la webcam est absente, noire ou
   masquée sur plus que cette part reste entièrement en letterbox, raison
   journalisée (ADR-ad2e). Jamais de bascule entre formats à l'intérieur
   d'un clip.

Inchangé aussi de SPEC-8257 : pendant un clip stream, aucun suivi (le
rectangle source découpé ne zoome ni ne se déplace, règle 3) ; pas de
facecam détectée = letterbox, raison journalisée (règle 4) ; un seul modèle
de détection en VRAM à la fois, device via `clipper.gpu` (règle 5,
ADR-fb9b).

## Choix de l'agencement stream (nouveau)
Une fois qu'un clip est en stream (règles 1 et 2 ci-dessus), un réglage
choisit l'agencement visuel — deux axes de config bien séparés : lequel des
deux formats de sortie s'applique à un clip (letterbox ou stream,
`[reframe] layout`, inchangé) n'a rien à voir avec, une fois en stream,
lequel des deux agencements le dessine (`[reframe] stream_variant`,
nouveau) :

- `stream_variant = "top"` (défaut, comportement global inchangé) :
  agencement de SPEC-3a88, facecam agrandie en haut (~40 % de la hauteur),
  jeu en bas, titre d'écran au-dessus de la caméra, sous-titres dans la
  zone basse.
- `stream_variant = "split"` (nouveau, choisi par config) : agencement
  décrit ci-dessous.

`stream_variant` n'est lu que pour un clip déjà en stream ; il ne change
rien au choix stream/letterbox lui-même. Une valeur inconnue est une erreur
explicite au chargement de la config (ADR-ad2e).

## Agencement split
Canevas inchangé 1080x1920 (SPEC-6a47). Deux zones fixes qui se partagent
toute la hauteur sans se chevaucher, plus un badge optionnel à leur
jonction :

- **Webcam** (`split_webcam_dest`, `[reframe]`, défaut
  `{x: 20, y: 0, w: 1040, h: 640}`) : la webcam localisée (règle 1), agrandie
  en haut. Source recadrée (jamais étirée) au ratio de `split_webcam_dest`
  (1040:640 par défaut) en la centrant sur le rectangle détecté — si le
  rectangle localisé n'a pas ce ratio, on rogne symétriquement l'excédent
  (largeur ou hauteur selon le cas) autour de son centre, sans jamais sortir
  du cadre source.
- **Jeu** (`split_gameplay_dest`, `[reframe]`, défaut
  `{x: 0, y: 640, w: 1080, h: 1280}`) : le reste de l'image, en bas, pleine
  largeur. Source recadrée (jamais étirée) au ratio de `split_gameplay_dest`
  (1080:1280 par défaut), centrée horizontalement dans la largeur restante
  et excluant la zone source de la webcam quand c'est possible (recadrage
  décalé pour ne pas la recouvrir) ; si l'exclusion complète ne tient pas
  dans le cadre source au ratio demandé, recadrage centré normal (repli
  silencieux accepté ici : ce n'est pas un échec, juste un cadrage moins
  favorable, noté dans le plan).
- Les deux rectangles dest doivent tenir dans le canevas 1080x1920 et ne
  jamais se chevaucher entre eux ; une config qui les fait se chevaucher,
  déborder du canevas ou tomber à ratio nul est une erreur explicite au
  chargement (ADR-ad2e), jamais un rendu silencieusement tronqué.
- **Règle de ratio (les deux zones)** : jamais de déformation. Le rectangle
  source est toujours recadré (crop) pour correspondre exactement au ratio
  du rectangle dest, jamais mis à l'échelle de façon non uniforme.

## Badge de chaîne (optionnel)
`[render] badge_enabled` (booléen, défaut `false`). Une fois actif,
remplace visuellement le pseudo texte de l'appel à l'abonnement (SPEC-6a86,
`cta_handle`) sur ce clip : si `badge_enabled` et `cta_enabled` sont tous
deux actifs, le pseudo texte ne s'affiche pas (le badge le remplace), mais
la carte de fin (`cta_text`, désactivable séparément) n'est pas affectée.
`badge_enabled` ne dépend donc pas de `cta_enabled` et peut s'activer seul.

- `badge_logo` (chemin d'un PNG, requis si `badge_enabled`) : logo de la
  chaîne (ex. logo Twitch), dessiné sur fond noir dans un carré de taille
  fixe `badge_logo_size` (px, défaut `100`), le glyphe du logo lui-même
  réduit d'un facteur réglable `badge_glyph_scale` (défaut `0,65`) à
  l'intérieur de ce carré (marge visuelle autour du glyphe).
- `badge_name` (texte, requis si `badge_enabled`) : nom affiché à droite du
  logo, sur le même fond noir, taille `badge_font_size` (px d'em, défaut
  `40`).
- `badge_enabled` sans `badge_logo` ou sans `badge_name` (chaîne vide) est
  une erreur explicite (ADR-ad2e : jamais de rendu à moitié activé).
- `badge_dest` (`[reframe]`, `{x, y, w, h}`, défaut
  `{x: 330, y: 590, w: 420, h: 100}`) : position et taille du bandeau
  complet (logo + nom, fond noir), par défaut à cheval sur la jonction
  webcam/jeu (`split_webcam_dest.h` = 640, la bande par défaut va de y=590
  à y=690). Réglable indépendamment des deux zones vidéo.
- `badge_dest` doit tenir dans la zone sûre TikTok (ci-dessous) : en dehors,
  erreur explicite au rendu (jamais un chevauchement silencieux avec
  l'interface TikTok).

## Style des sous-titres (agencement split)
Réglages `[subtitles]`, préfixe `split_`, indépendants du style karaoke
existant (`primary_color`/`secondary_color`/`emphasis_color`) : ce style n'a
que deux couleurs, le mot en cours de prononciation et le reste, jamais de
fond.

- `split_font_name` (défaut `"Poppins ExtraBold"`, police déjà embarquée
  `clipper/assets/fonts`).
- `split_font_size` / `split_min_font_size` / `split_font_step` (px d'em,
  défauts `80` / `44` / `4`) : mêmes paliers de réduction que
  `letterbox_font_size` si le texte ne tient pas dans `split_subtitle_dest`.
- `split_uppercase` (booléen, défaut `true`).
- `split_text_color` (mots hors mot courant, défaut `"white"`).
- `split_current_word_color` (mot en cours de prononciation, défaut
  `"#9146FF"`, violet Twitch).
- `split_outline_color` (défaut `"black"`) et `split_outline` (épaisseur px,
  défaut `10`, plus épais que `letterbox_outline`).
- `split_shadow_enabled` (booléen, défaut `false`, style de référence sans
  ombre) ; si actif, `split_shadow_color` et `split_shadow_offset` (px,
  défaut `(2, 2)`).
- `split_subtitle_dest` (`[reframe]`, `{x, y, w, h}`, défaut
  `{x: 150, y: 710, w: 780, h: 150}`) : position et taille de la bande de
  sous-titres, entièrement dans la zone jeu, sans jamais recouvrir le badge.
  Comme `badge_dest`, doit tenir dans la zone sûre TikTok : en dehors,
  erreur explicite au rendu.
- Aucun fond derrière le texte (contrairement au titre d'écran letterbox).
  Mêmes règles de mesure et de repli par paliers que le reste du contrat
  (SPEC-6a47) : si le texte ne tient toujours pas à `split_min_font_size`,
  erreur explicite, jamais tronqué ni débordant en silence.

## Titre d'écran et carte de fin
`[render] title_enabled` (booléen, défaut `true`, nouveau réglage : jusqu'ici
le titre d'écran n'était pas désactivable). Dans ce modèle (agencement
split, streameuse Twitch), `title_enabled = false` : pas de titre d'écran.
La carte de fin reste gouvernée par `cta_enabled` (SPEC-6a86, défaut
`false`) ; dans ce modèle elle reste désactivée (défaut). Le pseudo texte
sous le titre (`cta_handle`) est sans objet ici puisque le badge le
remplace (section précédente) et que le titre est désactivé.

## Zone sûre TikTok (rappel, SPEC-6a47)
Aucun texte au-dessus de y=160 ni au-dessous de y=1520, ni à gauche de
x=150 ni à droite de x=930. S'applique aux éléments de texte/overlay
(badge, sous-titres) — pas aux rectangles vidéo (`split_webcam_dest`,
`split_gameplay_dest`), qui sont le contenu filmé lui-même. Les valeurs par
défaut ci-dessus respectent cette zone (badge : x330-750/y590-690 ;
sous-titres : x150-930/y710-860).

## Format stream actuel (défaut global, inchangé)
`stream_variant = "top"` reste le comportement par défaut : aucune config
existante n'est affectée par cette spec. `split` est un choix explicite.

## JSON (sidecar, SPEC-6a86)
Le champ `layout` d'un clip en agencement split vaut `"stream_split"`
(distinct de `"stream"` pour l'agencement `top` existant), pour que QA et
l'interface web distinguent les deux sans ambiguïté.

## Références
`research/madajel/agencement/madajel-tiktok.json` (valeurs de référence
ci-dessus), `research/madajel/agencement/rendu-5400.png` et `rendu-2400.png`
(rendus ffmpeg validés par l'utilisateur), `research/madajel/tiktok/*.png`
(montage original imité). Fichiers locaux, hors dépôt (`.gitignore`) — voir
`research/BONNES-PRATIQUES.md`. Ne jamais citer le nom réel de la chaîne
dans ce dépôt public : « une streameuse Twitch ».
