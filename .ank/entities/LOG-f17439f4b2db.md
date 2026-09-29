---
id: LOG-f17439f4b2db
type: log
title: "repro: python -c load_config('definitely_absent_xyz.toml') -> Config(mode=review,"
created: 2026-09-29T18:39:31Z
author: w-a2d60a1b288f
scope:
  - clipper/config.py
  - clipper/__main__.py
  - tests/test_config.py
  - tests/test_cli.py
about: TASK-a2d60a1b288f
seq: 2
schema: 4
version: 1
---

 workspace=workspace), aucune erreur. Cause: clipper/config.py load_config ne distingue jamais chemin explicite vs implicite, seul path.exists() decide (si absent -> data={} silencieux dans tous les cas). CLI --config absent.toml idem: erreur reste 'aucun etat pour la video' au lieu de nommer le fichier de config manquant. Test existant test_config_defaults_to_review_mode_when_no_config_file appelle load_config(isolated_cwd / 'config.toml') explicite mais absent et attend le comportement par defaut silencieux -- ce test encode exactement le bug (chemin explicite absent traite comme defaut). Fix: sentinel pour distinguer 'aucun argument' (comportement par defaut documente, garde le silence) de 'chemin explicitement fourni' (leve ConfigError nommant le chemin si absent) ; CLI passe args.config=None par defaut (au lieu de la chaine 'config.toml') pour que 'pas de --config' redevienne l'appel implicite ; le test existant sera reecrit pour appeler load_config() sans argument (cwd=isolated_cwd) au lieu de lui passer le chemin explicite absent.
