---
id: TASK-1f45d2439dfa
type: task
slug: config-preset-de-cha-ne-en-surcouche-de-config-t
title: "config : preset de chaîne en surcouche de config.toml (base) et écriture TOML validée"
created: 2026-09-30T20:42:22Z
author: w-plan-web
status: in_progress
scope:
  - clipper/config.py
  - tests/test_config.py
  - pyproject.toml
blocked_by: []
done_criteria: |
  tests/test_config.py prouve, sans réseau : (1) load_config('presets/ma_chaine.toml', base='config.toml') fusionne les clés plates puis chaque section clé par clé, le preset gagnant, une sous-table ([llm.usages.x]) étant remplacée entière ; (2) une clé ou section inconnue dans le preset lève ConfigError qui nomme section et clé ; (3) write_config(path, data, base=...) sérialise en TOML (tomli_w, dépendance ajoutée à pyproject), relit le résultat par load_config avec la même base, puis remplace le fichier atomiquement ; un ConfigError laisse le fichier d'origine intact et remonte ; (4) un preset complet existant (toutes les clés redéfinies) charge à l'identique avec ou sans base ; (5) load_config sans base garde son comportement actuel (tests existants inchangés et verts). python -m pytest -q tests/test_config.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

ADR-4f6e §2, SPEC-fc0c §1.2 et §1.5. Décision utilisateur 2026-09-30 : un preset ne porte que ce qui diffère de config.toml ; backend LLM, modèles et dossiers vivent une seule fois dans config.toml. Les commentaires TOML sont perdus à l'écriture (accepté).

Points d'attention : la validation section par section (_validate_section) doit se faire sur le résultat fusionné ; `Config.section(name)` reste la seule lecture côté étapes. `write_config` est la brique unique réutilisée par clipper/channel.py (presets) et par l'écran Réglages (config.toml). Écriture atomique : tmp + os.replace, robuste sous Windows (voir pipeline._atomic_replace).
