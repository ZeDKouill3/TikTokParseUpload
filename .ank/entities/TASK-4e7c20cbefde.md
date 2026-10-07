---
id: TASK-4e7c20cbefde
type: task
slug: veille-d-duire-le-jeu-d-une-vod-youtube-depuis-s
title: "Veille : déduire le jeu d'une VOD YouTube depuis son titre et ses tags (correspondance stricte avec les jeux connus du jour)"
created: 2026-10-07T07:09:23Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/veille_sources.py
  - clipper/veille.py
  - clipper/web/static/screens/veille.js
  - tests/test_veille.py
  - tests/test_veille_sources.py
  - tests/test_web_veille.py
  - CHANGELOG.md
blocked_by: [TASK-9d012498479b]
done_criteria: |
  Tests verts, sans réseau : une VOD YouTube candidate sans jeu reçoit un jeu SEULEMENT si son titre ou ses tags (snippet.tags, s'ils sont relevés) contiennent le nom normalisé (casse, accents, ponctuation) d'un jeu déjà connu du relevé du jour (Twitch, Steam, IGDB si présent), en mot(s) entier(s) ; plusieurs jeux trouvés : le nom le plus long gagne s'il contient les autres (« Minecraft Dungeons II » avant « Minecraft »), sinon ambiguïté = aucun jeu ; nom de moins de [veille] youtube_game_min_chars caractères (CONFIG_DEFAULTS, défaut 5) ignoré ; jamais de jeu inventé ni d'appel LLM pour ce choix. Le candidat porte game_source = "titre" et la carte de la Veille affiche « jeu déduit du titre » ; sans correspondance : jeu non identifié comme aujourd'hui. Les signaux de tendance du jeu (Steam, Twitch, sorties) sont alors donnés à Claude pour cette VOD comme pour une VOD Twitch. Entrée CHANGELOG [Non publié].
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Relevé réel 2026-10-07 : la note de Claude dit « Les VOD YouTube n'ont pas de jeu identifié, donc la tendance est inconnue » : aucune VOD YouTube n'est proposée, alors que Twitch ne se télécharge plus depuis ce PC (10054 sur usher). Utilisateur inquiet des erreurs : correspondance stricte, pas de devinette.
