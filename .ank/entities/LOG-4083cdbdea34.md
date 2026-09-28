---
id: LOG-4083cdbdea34
type: log
title: "Lecture : reprise calculee par cut_k (fonction de la seule coupe), DP snap_cuts adaptee (partie k+1"
created: 2026-09-28T20:52:41Z
author: w-4f4f
scope:
  - clipper/parts.py
  - tests/test_parts.py
about: TASK-4f4fe1fa1bf3
seq: 3
schema: 4
version: 1
---

 = cut_{k+1} - start(cut_k)). part_count_range : N parties tiennent D si D + (N-1)*part_overlap_seconds dans [N*low, N*high]. Repli (c) 'dernier debut de mot avant cut_k' lu comme restreint a ]cut_k - part_overlap_min, cut_k[ (sinon reprise > max) ; segment sans mots = un pseudo-mot couvrant le segment.
