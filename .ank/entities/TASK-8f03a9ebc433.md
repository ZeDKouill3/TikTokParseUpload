---
id: TASK-8f03a9ebc433
type: task
slug: tests-le-journal-global-n-crit-plus-dans-le-vrai
title: "Tests : le journal global n'écrit plus dans le vrai logs/ (fixture autouse vers un dossier temporaire)"
created: 2026-10-05T23:12:53Z
author: nicoc@zedk_ordi
status: open
scope:
  - tests/conftest.py
  - tests/test_journal.py
  - clipper/journal.py
blocked_by: []
done_criteria: |
  Constat 2026-10-05 : la suite de tests écrit dans le VRAI logs/journal-*.log du dépôt (lignes « GET http://testserver », « worker[...] purge aaaaaaaaaaa »). Une fixture autouse dans tests/conftest.py fait pointer le dossier du journal (clipper/journal.py CONFIG_DEFAULTS "dir") vers tmp_path pour tout test, y compris ceux qui créent l'app web ou le worker. Preuve par test unitaire : après des appels représentatifs (TestClient GET, log d'un worker), aucun fichier n'est créé ni modifié sous le logs/ du dépôt (comparer liste/mtime avant-après) et les lignes vont dans le tmp. test_journal.py existant reste vert. Aucune logique de production changée sauf si strictement nécessaire pour rendre le dossier injectable (alors via CONFIG_DEFAULTS, ADR conventions).
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---
