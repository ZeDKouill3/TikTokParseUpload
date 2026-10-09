---
id: TASK-fde2eb1e333a
type: task
slug: readme-refonte-compl-te-dans-le-m-me-style-jour
title: "README : refonte complète dans le même style, à jour du code réel (veille, apprentissage, formats, comptes), captures rafraîchies"
created: 2026-10-09T08:15:38Z
author: nicoc@zedk_ordi
status: done
scope:
  - README.md
  - docs/assets/readme/**
  - tests/test_readme_assets.py
  - tests/test_docs_installation.py
  - tests/test_release_docs.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Demande de l'utilisateur (09/10) : refonte complète du README.md, DANS LE MÊME STYLE que l'actuel (français, en-tête centré avec logo + badges + GIF, phrases courtes, sections illustrées par des captures clair/sombre en .webp dans docs/assets/readme/, tableaux, blocs de config commentés). (1) Contenu remis à jour sur le code réel de main (pas de fonctionnalité inventée, chaque affirmation vérifiable dans le code, la config ou CHANGELOG.md section 0.6.0 et [Non publié]) : pipeline et étapes (dont action et candidats d'action), styles twitch-gaming / letterbox-gaming et formats stream split / letterbox (SPEC-5b9a webcam par période), jury et grilles, veille (Twitch/YouTube/Steam/IGDB), publication TikTok multi-comptes et créneaux, statistiques, apprentissage (rétention à maturité, alerte 0 vue, fiche par clip), installeur portable, configuration, développement (uv obligatoire, pytest, ank). Plan clair, plus court qu'aujourd'hui (647 lignes) si possible sans rien perdre d'utile ; les détails techniques longs renvoient vers docs/. (2) Captures : réutiliser les existantes quand elles sont encore justes ; pour les écrans changés ou nouveaux (veille, fiche clip, rétention...), nouvelles captures clair ET sombre, .webp, mêmes dimensions/nommage que les existantes, prises en lecture seule sur la console déjà lancée http://127.0.0.1:8000 (Chrome headless Playwright, timezone Europe/Paris, uniquement des GET de pages, ne JAMAIS cliquer un bouton qui écrit, ne jamais lancer un autre serve). Le dépôt est PUBLIC : aucune capture ni texte ne montre d'e-mail, de mot de passe, de jeton, de cookie, ni le nom de la chaîne Twitch amie (Madajel) ; ne pas capturer l'écran Comptes s'il affiche des e-mails (flouter ou garder l'ancienne capture). (3) Tests existants des docs verts (tests/test_readme_assets.py, tests/test_docs_installation.py, tests/test_release_docs.py, tests/test_web.py) : si un test vérifie une phrase ou une image précise, garder ce qu'il exige ou l'adapter seulement s'il vérifie un contenu devenu faux, en le disant dans le commit. (4) Aucune modification de code de production. CHANGELOG [Non publié] Modifié (une ligne : README refondu).
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/ee75ba364a00@b67241f
    tree: scope/1d0bb05a79b0
    criteria: 781272a256cb
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
