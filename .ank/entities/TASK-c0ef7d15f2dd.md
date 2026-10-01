---
id: TASK-c0ef7d15f2dd
type: task
slug: console-v2-corrections-du-quatri-me-tour-ancres
title: "console v2 : corrections du quatrième tour (ancres de Réglages, échecs actionnables, vignettes des vidéos, statistiques par chaîne)"
created: 2026-10-01T12:17:59Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - clipper/pipeline.py
  - clipper/render.py
  - tests/test_web.py
  - tests/test_pipeline.py
  - tests/test_render.py
blocked_by: []
done_criteria: |
  Tests ciblés, aucun réseau ni GPU, prouvent : (1) Réglages : les liens de section font défiler jusqu'à la section sans changer d'écran (aujourd'hui href=#set-general est lu comme un écran par le routeur app.js et renvoie au tableau de bord) : test statique (aucun href=#set- interprété comme route, gestionnaire de clic qui fait scrollIntoView, ou routeur qui ignore ces ancres) ; (2) tableau de bord, bloc Échecs (dashProblemRow) : le lien mène à la fiche #/videos/<id>, la ligne affiche le titre de la vidéo (identifiant si pas de titre), et propose « Relancer » (POST /api/videos/{id}/retry existant) et « Retirer » ; « Retirer » est une nouvelle route qui sort la vidéo des échecs et des compteurs (À débloquer) sans effacer son dossier workspace en silence (état explicite « retirée » dans son pipeline.json ou sous state/, réversible) ; mêmes actions sur la fiche vidéo ; tests API + statique ; (3) vignettes des VIDÉOS : pipeline.video_thumbnail(config, video_id) (même schéma que clip_thumbnail, le web ne traite jamais de vidéo, ADR-09ad) extrait une image JPEG de largeur <= 360 px de workspace/<id>/<id>.mp4 vers 10 % de la durée, en cache tant que la source n'a pas changé de mtime ; une route GET la sert ; si la source n'existe pas, la route répond 404 avec raison explicite et l'interface affiche une vignette neutre « pas d'image » ; vignettes affichées <img loading=lazy> dans la liste Vidéos, la fiche vidéo et les lignes du tableau de bord (en cours, échecs, file) ; test avec ffmpeg simulé + statique ; (4) Statistiques : un filtre de chaîne (Toutes / Sans chaîne / chaque chaîne) appliqué par l'API (paramètre channel) à tous les blocs (résultats par clip, coûts LLM, durée par étape, vidéos par statut), et le tableau Résultats par clip triable par clic sur l'en-tête (dont une colonne Chaîne) ; tests API + statique ; (5) tests existants verts. python -m pytest -q tests/test_web.py tests/test_pipeline.py tests/test_render.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Quatrième tour de la console v2, utilisation réelle par l'utilisateur (2026-10-01). Voir les 4 points du critère.
