---
id: SPEC-3a88ee9c2eb9
type: spec
slug: format-stream-facecam-fixe-agrandie-en-haut-jeu
title: "Format stream : facecam fixe agrandie en haut, jeu en bas, jamais de bascule dans un clip"
created: 2026-09-29T09:25:23Z
author: orch-main
status: proposed
scope:
  - clipper/reframe.py
  - clipper/render.py
  - clipper/pipeline.py
references: [SPEC-612781386e1d, ADR-fb9bcb1e98f5, ADR-ad2e562b1810]
schema: 4
version: 1
---

## Objet
Un troisième format de clip, `stream`, pour les vidéos où une facecam fixe occupe un petit coin d'une image de jeu ou d'écran (ex. SMYVmdpRMow, Squeezie : facecam ~526x296 en haut à gauche d'un 1920x1080). En letterbox, le visage y fait ~5 % de l'écran. S'ajoute aux formats de SPEC-6127 (letterbox par défaut, crop figé), dont le contrat de sortie (mp4 + sidecar json, champs obligatoires) reste inchangé. Décision utilisateur du 2026-09-29.

## Rendu
Image 1080x1920 en deux zones fixes : en haut, la facecam agrandie (rectangle source mis à l'échelle, ~40 % de la hauteur) ; en bas, le centre de l'image source hors facecam (le jeu) ; titre d'écran en haut et sous-titres entre les deux zones ou dans la zone basse, sans recouvrir le visage. Réglages (proportions, marges) dans CONFIG_DEFAULTS du module concerné.

## Règles
1. Détection une seule fois par vidéo : le rectangle de la facecam est celui où un visage apparaît à la même position (tolérance en px) sur au moins `facecam_min_share` des images clés (défaut 0,8), dans une zone fixe de moins d'un quart de l'image. Le rectangle est ensuite figé pour toute la vidéo.
2. Choix du format une seule fois par clip, tout ou rien : un clip est en stream si le visage est présent dans le rectangle sur au moins `facecam_min_share` de ses images clés ; sinon il est entièrement en letterbox. Jamais de bascule entre formats à l'intérieur d'un clip.
3. Pendant un clip stream, aucun suivi : le même rectangle source est découpé à chaque image, sans zoom avant/arrière ni déplacement, même si la détection de visage faiblit sur certaines images (tête tournée, main devant).
4. Pas de facecam détectée : la vidéo reste en letterbox, raison journalisée (le letterbox est le format par défaut de SPEC-6127, pas un repli silencieux, ADR-ad2e). Le layout du clip (`stream` ou `letterbox`) figure dans son plan de recadrage et son sidecar.
5. Un seul modèle de détection en VRAM à la fois, device via clipper.gpu (ADR-fb9b).
