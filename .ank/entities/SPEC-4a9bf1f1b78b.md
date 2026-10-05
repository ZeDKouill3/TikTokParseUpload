---
id: SPEC-4a9bf1f1b78b
type: spec
slug: webcam-du-stream-trouv-e-par-p-riode-rectangles
title: Webcam du stream trouvée par période, rectangles candidats numérotés choisis par Claude (succède à SPEC-76dc)
created: 2026-10-05T22:20:19Z
author: w-57453bb1e834
status: proposed
scope:
  - clipper/reframe.py
  - clipper/render.py
  - clipper/subtitles.py
  - clipper/pipeline.py
  - clipper/llm/__init__.py
references: [ADR-b16b71007578, ADR-fb9bcb1e98f5, ADR-ad2e562b1810, ADR-b1c17749b528, SPEC-6a867ae54f94]
supersedes: SPEC-76dc6a1cbccb
schema: 4
version: 1
---

## Objet
Succède à SPEC-76dc (agencement stream `split` réglable) : reprend à
l'identique tout ce qui concerne l'agencement (choix `top`/`split`, agencement
split, badge, style des sous-titres, titre d'écran et carte de fin, zone sûre,
JSON, format stream `top`), et REMPLACE ses règles 1 et 2 (localisation de la
webcam une fois par vidéo, sur le visage ou les bords) par une webcam trouvée
PAR PÉRIODE du stream, avec Claude pour choisir parmi des rectangles candidats
numérotés (section suivante).

Constats réels du 2026-10-05 qui motivent ce remplacement : sur une VOD
(streamer à casque, petite webcam à gauche) le visage n'est reconnu que sur
7 % des images clés, donc tous les clips tombaient en letterbox ; sur une
autre (Just Chatting plein écran au début, puis petite webcam en bas à droite
pendant le jeu) une seule position valait pour toute la VOD, douteuse. Une
disposition change au fil d'un stream : la webcam se retrouve donc par
période, jamais mémorisée d'un stream à l'autre (décision utilisateur
2026-10-05 : la remettre en cause à chaque stream coûte autant que tout
refaire).

Maquette Madajel, décisions et références de SPEC-76dc : inchangées, voir les
sections reprises plus bas.

## Règles 1 et 2 (remplacent celles de SPEC-76dc/SPEC-8257)
Une fois par vidéo (`detect_facecam`, résultat dans `facecam.json`, pas
refait sauf `--force`), planches sous `facecam/period_<n>.jpg`. Tout le
calcul d'images est local ; un seul modèle lourd en VRAM à la fois, le
détecteur de visages est fermé avant le premier appel LLM (ADR-fb9b).

1. **Périodes (local).** Environ une image clé par minute
   (`facecam_period_step`, défaut 60 s) sur toute la vidéo. Le Just Chatting
   est repéré par un visage d'au moins `facecam_fullscreen_face_height` (0,25)
   de la hauteur de l'image : au moins `facecam_period_min_samples` (2) images
   consécutives avec un grand visage, qui commencent dans les premières
   `facecam_period_lead_share` (10 %) des images, suivies d'au moins autant
   sans grand visage (le jeu), donnent DEUX périodes ; la limite est affinée
   à l'image clé près (dichotomie sur les images clés de scenes.json). Sinon
   (transition pas nette) UNE seule période, avec la raison écrite : la
   majorité des images décide. Un grand visage qui revient plus tard dans le
   jeu (pause, discussion) reste dans la 2e période.
2. **Candidats (local).** Sur `facecam_candidate_frames` (24) images
   équiréparties de la période : (a) zones de visage à la même position
   (centre à moins de `max(facecam_tolerance, facecam_cluster_ratio` × hauteur
   du visage`)`) sur au moins `facecam_candidate_min_frames` (2) images,
   calées sur le cadre réel de l'incrustation quand il est trouvé
   (`facecam_edge_*`), sinon centrées sur le visage ; (b) rectangles à cadre
   net (traits fixes sur au moins `facecam_candidate_edge_share` des images,
   quatre côtés nets, un côté collé à un bord d'image comptant comme net)
   dont le contenu bouge (non figé, `facecam_frozen_*`). Chaque candidat est
   mis au format du panneau caméra et fait moins d'un quart de l'image
   (`facecam_max_area`) ; les autres sont écartés avec leur raison
   (`rejected` dans `facecam.json`). Au plus `facecam_candidate_max` (8)
   candidats, numérotés de 1 dans l'ordre de lecture, dessinés et numérotés
   sur une planche de `facecam_board_frames` (8) images de la période. Aucun
   candidat : pas d'appel, période sans webcam, raison écrite.
3. **Claude (clipper.llm, ADR-b1c1).** UNE planche par période, usage
   `facecam` (modèle rapide par défaut, `[llm.usages.facecam]`), réponse
   validée par schéma JSON `{"webcam": entier | null, "reason": texte}` : le
   numéro du rectangle qui est la webcam du streamer, ou null. Jamais de
   coordonnées demandées à Claude. Un numéro absent de la planche est une
   erreur explicite après la réparation prévue par clipper.llm (ADR-ad2e) :
   `facecam.json` n'est pas écrit à moitié. Aucune mémoire d'un stream à
   l'autre.
4. **Choix par clip (une seule fois, tout ou rien).** Un clip prend le
   rectangle de la période qui contient son début. Période sans webcam :
   letterbox, raison journalisée. Sinon le clip est en stream si ce rectangle
   y est présent et vivant sur au moins `facecam_clip_min_share` (0,8) de ses
   images clés, sans exiger de visage : (a) contenu non noir ; (b) bords
   retrouvés au même endroit (sauf si le rectangle a été centré sur le seul
   visage) ; (c) non figé. Sinon letterbox, raison journalisée. Jamais de
   bascule entre formats à l'intérieur d'un clip. La décision et sa raison
   sont écrites par clip : `facecam_decision` = `{period, candidate, reason}`
   dans `reframe/<clip_id>.json`.
5. **Contrôle de la zone webcam du clip rendu (qa) : aucun.** Mesure du
   2026-10-05 sur 12 clips réels : la règle « visage ou mouvement dans le
   rectangle » ne sépare pas les bons des mauvais cadrages (le mouvement vaut
   1,0 partout) ; un contrôle « visage seul » séparerait sur l'échantillon
   mais un seul vrai mauvais clip existe, trop peu pour fixer un seuil.
   Piste : avertissement (jamais un rejet, règle QA de l'utilisateur) quand
   d'autres mauvais clips réels auront été collectés.

Mesuré sur les deux VOD de référence (vrai Claude, 2026-10-05) : 2 appels par
VOD, environ 0,04 $ chacune, 7 à 11 s par appel ; la bonne webcam trouvée
dans la période de jeu des deux, « aucune » pendant le Just Chatting.

Inchangé de SPEC-8257 : pendant un clip stream, aucun suivi (le rectangle
source découpé ne zoome ni ne se déplace, règle 3) ; pas de webcam = letterbox,
raison journalisée (règle 4) ; un seul modèle de détection en VRAM à la fois,
device via `clipper.gpu` (règle 5, ADR-fb9b).

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
