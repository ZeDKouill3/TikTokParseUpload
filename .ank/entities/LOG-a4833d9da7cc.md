---
id: LOG-a4833d9da7cc
type: log
title: "Fix: load_config utilise un sentinel _UNSET pour distinguer appel implicite (defaut, silencieux si"
created: 2026-09-29T18:54:08Z
author: w-a2d60a1b288f
scope:
  - clipper/config.py
  - clipper/__main__.py
  - tests/test_config.py
  - tests/test_cli.py
about: TASK-a2d60a1b288f
seq: 3
schema: 4
version: 1
---

 config.toml absent, comportement documente inchange) vs chemin explicite (leve ConfigError nommant le chemin si absent). CLI: --config default=None au lieu de la chaine 'config.toml', pour que l'absence de --config redevienne l'appel implicite ; load_config(args.config) si fourni, sinon load_config(). Verifie: sans le fix __main__.py, 'python -m clipper status X' sans --config dans un dossier sans config.toml levait a tort 'fichier de config introuvable : config.toml' (regression) -- confirme via git stash sur __main__.py seul. Tests existants test_config_defaults_to_review_mode_when_no_config_file et test_config_section_returns_only_defaults_when_table_absent encodaient le bug (chemin explicite absent traite comme defaut) : le premier appelle desormais load_config() sans argument, le second ecrit un config.toml vide avant l'appel explicite. Ajoute test_config_raises_when_explicit_path_is_missing (regression, verifiee rouge avant fix) et tests/test_cli.py::test_cli_config_explicit_and_missing_fails_naming_the_path. Suite complete : 941 passed, 8 skipped, 0 echec.
