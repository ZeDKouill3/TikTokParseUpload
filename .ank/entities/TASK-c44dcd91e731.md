---
id: TASK-c44dcd91e731
type: task
slug: audit-lot-h-download-fichier-v-rifi-restes-netto
title: "Audit lot H : download : fichier vérifié, restes nettoyés"
created: 2026-10-10T18:25:23Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/download.py
  - clipper/workspace.py
  - tests/test_download.py
  - tests/test_workspace.py
blocked_by: []
done_criteria: |
  Lot H de l'audit complet du 10/10 (contre-vérifié par Fable). Défauts couverts : media-I1, media-I2, media-M2. Détails, scénarios, preuves rejouables (scripts dans scratch-<domaine>/) : rapports E:\ClaudeRandom\TiktokParseUpload\research\reviews\audit-1010\<domaine>.md (coeur, publication, web, jury, image, stats, media, veille, installeur ; id = <domaine>-I<n>/M<n>) et E:\ClaudeRandom\TiktokParseUpload\research\reviews\audit-1010\contre-verif.md (verdicts, lot H) ; LECTURE SEULE, ne rien écrire dans research/. Correctif attendu : `clipper/download.py` (ffprobe durée, refus si vide ou écart > max(5 s, 1 %), `declared_duration`, conteneur réel, nettoyage `.part*`/`.ytdl`), `clipper/workspace.py` (`heavy_paths` + motifs), `tests/test_download.py`, `tests/test_workspace.py`. Critère CPU : Un faux yt-dlp qui produit 3 s pour 3 600 annoncées lève `DownloadError` sans écrire `meta.json`, et laisse un `.part-Frag7` absent après un download réussi ; `purge_heavy` supprime un `.mp4.part`. Pour chaque défaut : test de régression ROUGE avant le correctif, vert après ; tests existants des modules touchés verts ; aucune valeur de secours silencieuse (ADR-ad2e) ; si un défaut s'avère faux ou exige une décision humaine (amendement de spec/ADR), le dire dans ank log et ne pas le corriger.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/d30a3b149989@31d42ef
    tree: scope/5dbac92ea40b
    criteria: be8e216f0308
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
