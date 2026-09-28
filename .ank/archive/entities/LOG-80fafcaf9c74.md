---
id: LOG-80fafcaf9c74
type: log
title: "Repro: clipper.<name> important mais dependance interne manquante (ex:"
created: 2026-09-25T13:46:06Z
author: w-307b
scope:
  - clipper/config.py
  - tests/test_config.py
about: TASK-307ba7b3a6c0
seq: 2
schema: 4
version: 1
---

 totally_missing_dependency_xyz_abc) -> _section_defaults dit a tort 'pas de module clipper.<name>' car sauf 'except ImportError' generique. Mesure: importlib.import_module('clipper.repro_dep') (module qui fait 'import totally_missing_dependency_xyz_abc') leve ModuleNotFoundError avec exc.name='totally_missing_dependency_xyz_abc'. A l'inverse importlib.import_module('clipper.no_such_module_xyz') (module reellement absent) leve ModuleNotFoundError avec exc.name='clipper.no_such_module_xyz' (== nom cible exact). Hypothese confirmee: exc.name == f'clipper.{name}' distingue module absent vs dependance manquante. Fix: comparer exc.name a la cible.
