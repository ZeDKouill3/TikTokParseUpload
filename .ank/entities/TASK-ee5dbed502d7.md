---
id: TASK-ee5dbed502d7
type: task
slug: web-cran-r-glages-config-toml-en-formulaire-mode
title: "web : écran Réglages (config.toml en formulaire : mode, dossiers, [llm] backend et modèles par usage, [web], [worker] ; écriture validée ; section Accès)"
created: 2026-09-30T20:44:58Z
author: w-plan-web
status: done
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_web.py
blocked_by: [TASK-f753723ce754]
done_criteria: |
  tests/test_web.py prouve (config.toml temporaire) : GET /api/settings renvoie les valeurs effectives et, par section, les CONFIG_DEFAULTS avec commentaires (même mécanisme que l'écran Chaînes) ; PUT /api/settings passe par config.write_config sur config.toml : une valeur refusée par load_config donne 422 avec detail et le fichier reste intact ; un mode ou backend changé est relu par les nouvelles entrées de file (create_app recharge la config à chaque requête de file, ou expose reload) ; l'écran settings contient le formulaire par sections, la section 'Accès' en lecture seule (hôte, port, jeton masqué, commande serve à lancer) et l'avertissement 'commentaires du fichier perdus' avant la première écriture. python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/926cbadd6a58@7260b8f
    tree: scope/9d1eeb53773d
    criteria: d71600606081
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

SPEC-c100 E8, ADR-4f6e §2 et §5. Le jeton ne se modifie pas depuis l'interface (il faut le fichier et un redémarrage) : c'est ce que dit la section Accès.
