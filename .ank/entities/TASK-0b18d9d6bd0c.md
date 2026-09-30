---
id: TASK-0b18d9d6bd0c
type: task
slug: cta-abonnement-spec-6a476ca57f39-pseudo-de-cha-n
title: "CTA abonnement (SPEC-6a476ca57f39) : pseudo de chaîne permanent + carte de fin « Abonne-toi ! » + ligne d'appel en description"
created: 2026-09-30T09:33:30Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/render.py
  - clipper/captions.py
  - clipper/subtitles.py
  - clipper/qa.py
  - tests/test_render.py
  - tests/test_captions.py
  - tests/test_subtitles.py
  - tests/test_qa.py
  - docs/GUIDE.md
  - AGENTS.md
blocked_by: []
done_criteria: |
  Implémente SPEC-6a476ca57f39 point par point (critères de la spec recopiés dans ank log et cochés un à un) ; réglages dans les CONFIG_DEFAULTS des modules concernés, désactivés par défaut (rendu par défaut identique octet pour octet au comportement actuel : test qui le prouve) ; letterbox et stream/facecam_gameplay couverts ; textes mesurés avec la vraie police, zone sûre respectée, erreur explicite si ça ne tient pas (ADR-ad2e) ; sidecar indique la présence du CTA ; tests unitaires ; 1 rendu réel de contrôle par format (letterbox et stream) avec capture PNG d'une image du milieu et d'une image de la carte de fin dans research/cta/ (chemins dans ank log) ; docs/GUIDE.md montre un exemple de preset (fichier --config) ; AGENTS.md : SPEC-6a476ca57f39 remplace SPEC-6127 dans la liste des décisions.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/eeb3623cbc22@8f1a708
    tree: scope/9978cf2e7482
    criteria: af46db9b72a5
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Spec ratifiée par l'utilisateur 2026-09-30 (b797953). Contexte : preset par chaîne pour une streameuse Twitch (Madajel, jeu d'horreur FR) : `clipper run https://www.twitch.tv/videos/<id> --config presets/<chaine>.toml`. Choix utilisateur : pseudo `twitch.tv/<handle>` discret sous le titre d'écran tout le clip + encadré « Abonne-toi ! » les 2 dernières secondes dans la bande du bas (remplace les sous-titres pendant ces secondes) + ligne d'appel et hashtags dans la description. Lire la spec en entier (ank show SPEC-6a476ca57f39), SPEC-3a88ee9c2eb9 (format stream) et ADR-ad2e. Pour les rendus réels de contrôle, utiliser une vidéo déjà dans workspace/ (ex. 7VaA8XUKrAY letterbox, WVjOSRFWm4c stream) sans relancer le pipeline complet ni appeler de LLM.
