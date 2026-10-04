---
id: LOG-e09ae2b3452f
type: log
title: "released: Critere (4) exige une entree CHANGELOG.md sous [Non publie] decrivant l'installeur. Mais"
created: 2026-10-04T00:32:24Z
author: w-1b5a73188dba
scope:
  - docs/INSTALLATION.md
  - README.md
  - docs/versions.md
  - CHANGELOG.md
  - tests/test_docs_installation.py
about: TASK-1b5a73188dba
seq: 4
schema: 4
version: 1
---

 tests/test_release_docs.py::test_changelog_has_empty_unreleased_then_the_current_version_first (invariant deja ratifie, pose par les taches de release passees : TASK-7711 Release v0.4.0, TASK-4924 v0.3.0, TASK-c601 v0.2.0) exige que [Non publie] reste strictement vide en permanence -- le changelog d'une version est ecrit d'un coup par une tache de release dediee, pas de maniere incrementale par les taches de feature. Les deux ne peuvent pas etre vrais en meme temps : tout contenu sous [Non publie] fait echouer 'python -m pytest -q' en entier. tests/test_release_docs.py n'est pas dans le scope de TASK-1b5a73188dba (scope : docs/INSTALLATION.md, README.md, docs/versions.md, CHANGELOG.md, tests/test_docs_installation.py), donc je ne peux pas l'amender, et je ne dois pas assouplir mon propre critere. docs/INSTALLATION.md, README.md et docs/versions.md sont ecrits et verts (tests/test_docs_installation.py + tests/test_readme_assets.py passent) ; seul le point (4) CHANGELOG bloque. A trancher au niveau planification : soit la tache de release qui suivra integre le paragraphe installeur (deja redige dans mon diff, a recuperer), soit SPEC-38f7761891f6 R10 est amendee pour deplacer ce livrable vers la tache de release, soit l'invariant de test_release_docs.py est revu pour autoriser une accumulation incrementale sous [Non publie] entre deux releases.
