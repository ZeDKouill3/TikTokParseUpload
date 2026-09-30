---
id: TASK-585e54dc6eab
type: task
slug: channel-py-cha-nes-channel-de-presets-chaine-tom
title: "channel.py : chaînes ([channel] de presets/<chaine>.toml) : liste, chargement fusionné, validation, sauvegarde"
created: 2026-09-30T20:42:22Z
author: w-plan-web
status: done
scope:
  - clipper/channel.py
  - tests/test_channel.py
blocked_by: [TASK-1f45d2439dfa]
done_criteria: |
  tests/test_channel.py prouve : (1) clipper.channel.CONFIG_DEFAULTS contient exactement les clés de SPEC-fc0c §1.3 avec leurs défauts (display_name, source_url, watch, watch_interval_s, watch_min_duration_s, mode, slots, timezone, tiktok_account, logo) ; (2) list_channels(presets_dir) ne renvoie que les presets ayant une table [channel], triés par nom ; un nom hors ^[a-z0-9_-]{1,40}$ est refusé (ChannelError) ; (3) load_channel(name) renvoie le Config fusionné (via load_config base=config.toml) et le dict [channel] ; mode absent = mode global, mode invalide = ConfigError ; (4) un slot dont day n'est pas mon..sun ou time n'est pas HH:MM lève ConfigError nommant le slot ; (5) save_channel(name, data) passe par config.write_config et un fichier invalide reste intact ; (6) delete_channel supprime le fichier et refuse un nom inconnu ; (7) next_slots(channel, after, n) renvoie les n prochains créneaux dans le fuseau de la chaîne. python -m pytest -q tests/test_channel.py tests/test_config.py vert, aucun réseau.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/294271d27edd@cb8bf0e
    tree: scope/90c0574a3449
    criteria: f491505296bd
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

ADR-4f6e §2, SPEC-fc0c §1. Bibliothèque, pas une étape : n'importe aucune étape ni clipper.web (ADR-b16b). Fixtures avec `ma_chaine` seulement.

Le module ne connaît ni la file ni la publication : il donne la liste des chaînes, un Config fusionné prêt pour pipeline.run/render, et la validation des réglages [channel] (créneaux, fuseau IANA via zoneinfo). `next_slots(channel, after, n)` (créneaux à venir dans le fuseau de la chaîne) vit ici : clipper/publish.py s'en sert.
