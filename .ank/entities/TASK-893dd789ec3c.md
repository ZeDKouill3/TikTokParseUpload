---
id: TASK-893dd789ec3c
type: task
slug: reframe-recaler-les-bords-du-rectangle-webcam-ch
title: "Reframe : recaler les bords du rectangle webcam choisi par Claude sur la vraie incrustation (Hctuan décentré, TheGuill bande d'overlay)"
created: 2026-10-06T10:54:49Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
  - tests/fixtures/reframe/**
blocked_by: []
done_criteria: |
  Défaut constaté 2026-10-06 (utilisateur) : Claude choisit le BON rectangle candidat (SPEC-4a9b, candidats numérotés), mais ce candidat est mal découpé dès la détection, donc le crop final est approximatif : Hctuan v2888230655 webcam pas centrée (candidats 'visage' avec edge_reason « bords introuvables : rectangle centré sur le visage conservé », workspace/v2888230655/facecam.json + facecam/period_*.jpg) ; TheGuill v2887364910 fine bande de texte de l'overlay visible sous la webcam (crop un peu trop haut/grand). Correctif choisi par l'utilisateur (option A, déterministe, sans appel LLM supplémentaire) : APRES le choix de Claude, affiner le rectangle retenu en recalant chacun de ses 4 bords sur le vrai bord de l'incrustation dans une bande autour du rect (contraste/gradient du cadre, et/ou zone qui bouge entre images clés vs fond d'overlay fixe), sans jamais déplacer un bord au-delà d'une marge bornée réglable dans CONFIG_DEFAULTS de reframe ; si aucun bord fiable n'est trouvé d'un côté, ce côté reste tel quel et la raison est journalisée (pas de repli silencieux, ADR-ad2e). Le rect affiné et le rect d'origine sont écrits dans facecam.json (champ distinct, ex. refined_rect + refine_reason). Méthode ank-diagnose : mesurer d'abord en LECTURE SEULE sur les images réelles de v2888230655 et v2887364910 (workspace/, jamais y écrire ; copies sous research/ si besoin) l'écart en px entre rect choisi et vraie webcam, chiffres dans ank log ; après correctif, remesurer et loguer (objectif : bords à quelques px près, plus de bande d'overlay, webcam centrée). Tests : non-régression avec images synthétiques (overlay + webcam décalée de quelques px) ou crops réduits en fixture légère < 200 Ko, rouges avant le correctif ; ne pas casser test_reframe existant (contrôle par clip TASK-53e3, éviction TASK-baa8). Aucun réseau, aucun vrai Claude, CPU seulement.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/919d6aff2598@0b10300
    tree: scope/7e82032c9c15
    criteria: 687d9f21ab05
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
