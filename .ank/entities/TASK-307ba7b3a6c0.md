---
id: TASK-307ba7b3a6c0
type: task
slug: clipper-config-ne-plus-dire-pas-de-module-quand
title: "clipper.config : ne plus dire 'pas de module' quand c'est une dépendance du module qui manque"
created: 2026-09-25T13:40:10Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/config.py
  - tests/test_config.py
blocked_by: []
done_criteria: |
  Quand le module d'une section de config existe mais que son import échoue parce qu'une de ses dépendances manque (ModuleNotFoundError sur un autre nom), clipper.config lève une erreur qui nomme la dépendance manquante et le module concerné, au lieu de dire que le module n'existe pas ; le cas 'module réellement absent' garde son message actuel ; test de régression dans tests/test_config.py ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
