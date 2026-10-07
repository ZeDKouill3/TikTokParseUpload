---
id: TASK-a35cd2d97f8a
type: task
slug: comptes-case-pr-t-publier-cliquable-pause-repris
title: "Comptes : case « Prêt à publier » cliquable (pause / reprise), « En pause (manuel) » dans Comptes, Clips et Publication, GUIDE et CHANGELOG (SPEC-f348 R5, R7.6)"
created: 2026-10-07T21:01:46Z
author: w-pauseplan
status: done
scope:
  - clipper/web/static/**
  - docs/GUIDE.md
  - CHANGELOG.md
  - tests/test_web.py
blocked_by: [TASK-6ceb549b0edb]
done_criteria: |
  SPEC-f348954318c1 R5 et R7.6 tenues côté écrans, vérifiées sans navigateur par des tests qui lisent les fichiers statiques et l'API (tests/test_web.py) : (1) clipper/web/static/screens/accounts.js : la case « Prêt à publier » n'a plus aria-readonly ; son gestionnaire de clic appelle POST /api/accounts/{id}/pause quand la case est cochée, POST /api/accounts/{id}/resume quand le compte porte paused_at, et « Se connecter » sinon ; le texte « En pause (manuel) depuis le » est rendu, avec la date formatée en heure de Paris (fmtParis), quand paused_at est posé ; (2) clips.js et publish.js ne proposent pas un compte dont ready_to_publish est faux (filtre conservé) et affichent « (en pause) » pour le compte figé d'une publication existante quand paused_at est posé, à la place de « (non prêt à publier) » ; (3) docs/GUIDE.md explique la pause et la reprise d'un compte (effet sur la file : les entrées restent en attente avec la raison, rien ne part ailleurs ; les publications déjà programmées côté plateforme ne sont pas touchées ; à la reprise, une publication immédiate au créneau passé part à la boucle suivante) ; (4) CHANGELOG.md « Non publié » décrit la pause manuelle d'un compte ; (5) python -m pytest -q tests/test_web.py tests/test_accounts.py vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/94791066673e@9e0de18
    tree: scope/9c2533b829ad
    criteria: 52a5ff562d37
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Partie écrans de SPEC-f348954318c1 (R5, R7.6), après TASK-6ceb549b0edb qui apporte l'état `paused_at`, les routes `POST /api/accounts/{id}/pause` / `resume`, `ready_blocked_reason` avec la raison de pause et `paused_at` dans `GET /api/publish/accounts`.

## Aujourd'hui
- clipper/web/static/screens/accounts.js : `accReadyBox` (case `data-acc-ready` en lecture seule, `aria-readonly`) ; le clic (`e.preventDefault()`) lance « Se connecter » quand le compte n'est pas prêt, rien sinon ; `accResolve` pour « J'ai réglé le problème ».
- clips.js (`clipsFillSelAccounts`, sélection multiple) et publish.js (`pubFormHtml`, série, édition d'une publication) filtrent `ready_to_publish` ; l'édition affiche « (non prêt à publier) » pour le compte figé d'une publication.
- docs/GUIDE.md décrit l'écran Comptes ; CHANGELOG.md section « Non publié ».

## À faire
- accounts.js : la case devient cliquable : cochée → clic = `POST .../pause` (toast « Compte en pause », état rafraîchi) ; décochée et `paused_at` → clic = `POST .../resume` (toast selon `ready_to_publish` rendu : « Compte prêt à publier » ou « Toujours pas prêt : <raison> ») ; décochée sans pause → « Se connecter » comme aujourd'hui. Afficher « En pause (manuel) depuis le <date> » (heure de Paris, `fmtParis`) quand `paused_at` est posé ; plus de `aria-readonly`, un `title` qui dit ce que fait le clic. « J'ai réglé le problème » inchangé.
- clips.js / publish.js : un compte en pause n'est pas proposé (déjà le cas via `ready_to_publish`, à garder) ; là où une publication existante affiche « (non prêt à publier) », afficher « (en pause) » si `paused_at` est posé.
- docs/GUIDE.md : paragraphe pause / reprise dans la section Comptes (quoi, effet sur la file, reprise).
- CHANGELOG.md « Non publié » → « Ajouté » : la pause manuelle d'un compte.
- tests/test_web.py : tests de la source JS comme `test_clips_screen_labels_every_server_status_including_not_ready` (lecture du fichier statique).
