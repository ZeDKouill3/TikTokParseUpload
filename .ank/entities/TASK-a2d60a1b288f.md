---
id: TASK-a2d60a1b288f
type: task
slug: config-load-config-sur-un-fichier-explicitement
title: "config : load_config sur un fichier explicitement donné et absent doit échouer (repli silencieux)"
created: 2026-09-29T18:35:44Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/config.py
  - clipper/__main__.py
  - tests/test_config.py
  - tests/test_cli.py
blocked_by: []
done_criteria: |
  load_config sur un chemin explicite inexistant lève une erreur qui nomme le chemin ; clipper --config absent.toml run ... échoue avec ce message ; le cas par défaut garde son comportement documenté ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

load_config('E:/nope/absent.toml') renvoie les valeurs par défaut sans rien dire : un script de test a rendu du letterbox au lieu du stream à cause d'un chemin de config périmé (2026-09-29). Contraire à ADR-ad2e. Un chemin explicitement passé (CLI --config ou appel direct) qui n'existe pas doit lever une erreur claire ; garder le comportement documenté pour le config.toml par défaut absent seulement s'il est voulu (vérifier la doc/les tests existants et le dire dans ank log).
