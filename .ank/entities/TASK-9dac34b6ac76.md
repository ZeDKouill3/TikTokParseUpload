---
id: TASK-9dac34b6ac76
type: task
slug: apprentissage-4-4-bilan-des-vod-choisies-par-la
title: "Apprentissage (4/4) : bilan des VOD choisies par la veille (state/veille/bilan.json écrit par learning après chaque versement : clips publiés, vues et rang à maturité, raison si absent) donné à Claude dans le prompt du choix des VOD (SPEC R8)"
created: 2026-10-07T10:27:52Z
author: w-learnplan
status: done
scope:
  - clipper/learning.py
  - clipper/veille.py
  - tests/test_learning.py
  - tests/test_veille.py
blocked_by: [TASK-c108c1430ebc]
done_criteria: |
  tests/test_learning.py prouve sur tmp_path (state/veille/seen.json avec des entrées queued datées, sidecars output/<video_id>/*.json avec et sans tiktok_post, journal outcomes et sync.json fabriqués) : (1) learning.write_veille_report(now, config=) écrit state/veille/bilan.json {computed_at, days = [learning] veille_report_days (défaut 30), entries: [{picked_on, candidate_id, source, game_name, channel_name, title, video_id, clips_published, clips_mature, views_percentile_mean | null, views_at_maturity_max | null, missing: null | "no_clips" | "not_published" | "immature" | "account_below_min"}]} pour les VOD mises en file dans les veille_report_days derniers jours, au plus [learning] veille_report_max (défaut 20) entrées, les plus récentes d'abord, chiffres pris dans les entrées stats du journal (jamais calculés autrement, jamais inventés : une VOD sans clip mûr a missing renseigné et des chiffres null) ; (2) learning.run_if_due appelle write_veille_report après chaque sync ; (3) deux écritures de suite donnent le même contenu hors computed_at. tests/test_veille.py prouve avec FakeBackend : (4) veille._prompt (et donc l'appel llm.ask de veille.decide) contient, avant la ligne « Candidats (VOD) : », le bloc « Bilan des VOD choisies récemment (vues à maturité, rang 0-1 dans le compte) » avec une ligne par entrée du fichier (titre, jeu, chaîne, clips publiés, rang moyen, vues max, ou missing en clair) ; (5) sans fichier, la ligne « Bilan des VOD choisies récemment : aucun (pas encore de résultats) » est présente ; (6) un bilan.json illisible est une VeilleError nommant le fichier, jamais ignoré ; (7) le schéma et le contrôle check du choix sont inchangés (tests existants verts). python -m pytest -q tests/test_learning.py tests/test_veille.py vert ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/e7acf61bd25c@fa9a672
    tree: scope/76df250ff4e3
    criteria: 98b162e508b9
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

ADR-c260 point 8 et SPEC associée R8 : la veille (ADR-ca9a, SPEC-bdd9 R6) fait choisir les VOD par Claude sans jamais lui dire ce que ses choix précédents ont donné. Mesure du 2026-10-07 : 2 jours d'état, 6 propositions dont 4 mises en file (`state/veille/seen.json`, clé `queued`, avec `candidate_id`, `video_id`, `url`), aucun clip de ces VOD encore publié : le premier bilan dira `missing` partout, ce qui est la réponse honnête.

Chaîne : `seen.queued[].video_id` → `output/<video_id>/*.json` (`tiktok_post`) → entrées `stats` du journal (`views_at_maturity`, `views_percentile`, tâche 2/4). `learning` écrit le fichier, `veille` le lit : `veille.py` n'importe pas `learning` (le fichier est le contrat, comme les autres fichiers de `state/veille/`, ADR-ca9a §3, écriture atomique) et `learning` n'importe pas `veille`.

Lectures : `clipper/veille.py` (`_prompt`, `decide`, `_schema`, `_check_picks`, `seen.json`), `clipper/learning.py` (tâche 2/4 : `sync.json`, entrées `stats`), SPEC-bdd9 R6 (choix de Claude : usage `veille`, schéma inchangé), ADR-ad2e (aucun chiffre inventé). Aucun nom réel dans les tests.
