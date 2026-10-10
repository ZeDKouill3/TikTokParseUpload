---
id: LOG-57ced0282fb1
type: log
title: "media-I1/I2/M2 corriges. Rouge avant: test_download ImportError (_probe_duration absent),"
created: 2026-10-10T18:34:23Z
author: w-c44dcd91e731
scope:
  - clipper/download.py
  - clipper/workspace.py
  - tests/test_download.py
  - tests/test_workspace.py
about: TASK-c44dcd91e731
seq: 2
schema: 4
version: 1
---

 test_workspace purge .part rouge (heavy_size 0 vs 5). Vert apres (download, workspace, logging_verbose, pipeline, worker). Hors scope assume: tests/test_logging_verbose.py (2 tests: sonde ffprobe patchee car faux yt-dlp ecrit des octets bidon). test_web perf scan flaky sous charge, sans rapport.
