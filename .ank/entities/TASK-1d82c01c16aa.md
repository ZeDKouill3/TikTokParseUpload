---
id: TASK-1d82c01c16aa
type: task
slug: veille-historique-4-5-relev-par-voies-parall-les
title: "Veille historique (4/5) : relevé par voies parallèles par hôte (helix, youtube, steam_api, steam_store, steamcommunity, usher) en trois phases puis Claude, échéance globale veille_deadline_s passée aux collecteurs et au test d'accès, sources partial/skipped visibles, prompt « Relevé incomplet » (SPEC-85a0 R29, R30)"
created: 2026-10-07T13:14:45Z
author: w-histplan
status: done
scope:
  - clipper/veille.py
  - clipper/veille_sources.py
  - tests/test_veille.py
  - tests/test_veille_sources.py
blocked_by: [TASK-70228c3a3499]
done_criteria: |
  Tests verts sans réseau (collecteurs injectés synchronisés par threading.Event, horloge et attente injectées), pytest complet vert. (1) CONFIG_DEFAULTS gagne veille_deadline_s=480 (60 à 3600, VeilleError nommant la clé). (2) collect exécute les sources par voies et phases exactement comme SPEC-85a0 R29 (phase 1 : helix [twitch puis igdb], youtube, steam_api [steam puis steam_fr] ; phase 2 : steam_api [steam_players], steamcommunity [steam_followers] ; phase 3 : usher [test d'accès par jeu], steam_store [steam_reviews], helix [twitch_vods_30d] ; puis Claude), un fil par voie et par phase, barrière entre phases : tests où le collecteur steam_followers ne rend la main qu'après le début de steam_players (recouvrement dans la phase 2), où le test d'accès, steam_reviews et twitch_vods_30d se recouvrent (phase 3), où twitch est fini avant qu'igdb commence (même voie, jamais en parallèle), où la phase 2 ne commence qu'après la fin de toutes les voies de la phase 1 ; une exception dans une voie = source en erreur, autres voies et phases intactes, Claude appelé ; les jeux suivis (R23) sont fixés avant le test d'accès et un jeu vidé par le test garde son trend_30d. (3) Échéance : deadline = started_at + veille_deadline_s sur l'horloge injectée ; chaque collecteur réel de veille_sources et _check_twitch_access reçoivent deadline (callable rendant les secondes restantes) en argument nommé et vérifient avant chaque requête, pause ou essai ; _run_source ne passe deadline qu'à un collecteur dont la signature l'accepte (les faux collecteurs existants restent valides) ; tests : un collecteur réel (transport injecté) interrompu entre deux appids/pages rend deadline_stopped et n'émet plus aucune requête, collect marque la source partial avec error « échéance de N s atteinte : k ... non relevé(s) » et counts.deadline = k, une source dont la phase n'a pas commencé est skipped « échéance atteinte avant le début », test d'accès interrompu -> VOD restantes écartées access_deadline (counts.deadline, distinct de untested), deadline_hit et deadline_at écrits dans days/<date>.json, prompt avec « Relevé incomplet (échéance de N s) : <source> : <error> » et Claude appelé quand même, aucune valeur inventée ; relevé fini avant l'échéance -> deadline_hit faux, aucun partial. (4) Cette tâche ne touche ni clipper/web, ni clipper/worker.py, ni les docs, et n'amende aucune ADR ni SPEC.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/1e3f6a289f5c@56f5943
    tree: scope/7f1c62e9304f
    criteria: 5d74fb2386d7
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

Exigence utilisateur 07/10/2026 : relevé complet < 10 min ; mesuré ~4 min le 07/10 (14:35-14:39) dont steam_followers 50 × 3 s. Budget par étape et chemin critique (≈ 6,5 min nominal) dans SPEC-85a0 R30. Voies fixées par hôte dans le code, pas de réglage de parallélisme. Les collecteurs partagent le jeton Twitch par fichier verrouillé (twitch_token.json) : twitch, igdb et twitch_vods_30d restent dans la même voie helix. deadline = callable (secondes restantes) sur la même horloge injectée que les collecteurs ; signature inspectée par _run_source pour ne pas casser les faux collecteurs des tests existants.
