---
id: TASK-0dbead00e989
type: task
slug: worker-un-worker-json-verrouill-par-un-lecteur-n
title: "Worker : un worker.json verrouillé par un lecteur ne tue plus la boucle (battement réessayé)"
created: 2026-10-10T13:37:48Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/worker.py
  - tests/test_worker.py
blocked_by: []
done_criteria: |
  Constat réel 10/10 12:50 Paris (audit coeur I4) : Worker._beat fait os.replace(tmp, worker.json) sans réessai ; une lecture concurrente de l'API web sous Windows donne « PermissionError: [WinError 5] Accès refusé: 'state\worker.json.5256.tmp' -> 'state\worker.json' » qui remonte de tick() et tue la boucle du worker : la file est restée bloquée 1 h 20 (vidéo finie mais entrée running). Correctif : _beat utilise channel.replace_retrying (même mécanisme que la file) ; si le verrou persiste après les réessais, le battement est sauté avec un log.warning (le suivant réessaie), le .tmp est supprimé, et la boucle continue. Critère CPU : test où os.replace lève PermissionError N fois puis réussit -> worker.json écrit ; test où il lève toujours -> tick() ne lève pas, warning journalisé, pas de .tmp laissé ; régression rouge avant le correctif.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
