---
id: TASK-fdfb14ad4791
type: task
slug: jury-grille-embarqu-e-builtin-gaming-v2-non-acti
title: "Jury : grille embarquée builtin:gaming-v2 (non activée), signal mesuré speech_density, outil de rejeu hors ligne sur les posts connus"
created: 2026-10-10T02:06:39Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/assets/rubric-gaming-v2.toml
  - clipper/moments.py
  - prompts/jury/retention/v1.md
  - tools/replay_jury.py
  - tests/test_moments.py
  - tests/test_replay_jury.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Plan et constats : E:\ClaudeRandom\TiktokParseUpload\research\reviews\plan-jury-retention.md (local, research/ ignoré par git), sections « Les 10 clips », Propositions (1) et tâche (4). Préparer l'expérience A/B sans rien activer (l'utilisateur décidera). (a) Nouvelle grille embarquée builtin:gaming-v2 = clipper/assets/rubric-gaming-v2.toml : copie de rubric-gaming.toml avec les changements de la table (1) du plan : value weight 0 -> 2, emotion 4 -> 2, nouvelles questions hook / payoff / standalone (texte exact du plan), single_max et part_max 90 -> 60, min_score inchangé ; load_rubric accepte 'builtin:gaming-v2' ; builtin:gaming et builtin:gaming-action inchangés octet pour octet (tests existants SPEC-9216/SPEC-b0f3 verts sans modification). Aucun preset ni config.toml ne change. (b) Signal mesuré speech_density (zéro LLM) calculé dans moments.py depuis les mots horodatés du candidat : mots par seconde et délai du premier mot ; bonus/malus réglable dans la table [bonus] de la grille (clés speech_density_min_wps, speech_density_max_first_word_s, speech_density_malus) ; 0 (désactivé) quand la clé est absente, donc aucune grille existante ne change de note ; activé dans gaming-v2 (malus plafonné si < 1,5 mot/s ou premier mot > 2 s). Tests : candidat à 0,5 mot/s -> malus ; 3 mots/s et premier mot à 0 s -> 0 ; grille sans les clés -> 0. (c) prompts/jury/retention/v1.md : la perspective retention v1 (texte exact du plan, section (1) APRÈS), versionnée, non branchée. (d) tools/replay_jury.py <posts.csv> [--rubric builtin:gaming-v2] [--perspective prompts/jury/retention/v1.md] : rejoue le jury sur les candidats connus du csv (research/perf-0910/posts.csv : video_id, clip_id, pct_watched) et écrit Spearman(note, pct_watched) par juge et pour la note finale ; tests CPU avec FakeBackend sur 4 cas synthétiques au rho connu ; exécution réelle seulement avec CLIPPER_REAL_MODELS=1 (test optionnel sauté par défaut, quota). CHANGELOG [Non publié] Ajouté.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/74798c152bfa@13a2e7f
    tree: scope/474c27bc149d
    criteria: dd433f322f74
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
