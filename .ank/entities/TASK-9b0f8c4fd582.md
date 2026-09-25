---
id: TASK-9b0f8c4fd582
type: task
slug: clipper-gpu-d-tecter-cuda-via-ctranslate2-sans-t
title: "clipper.gpu : détecter CUDA via CTranslate2, sans torch"
created: 2026-09-25T13:24:01Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/gpu.py
  - tests/test_gpu.py
blocked_by: []
done_criteria: |
  clipper.gpu.get_device() renvoie Device(type='cuda', compute_type='float16') quand ctranslate2.get_cuda_device_count() > 0, et Device(type='cpu', compute_type='int8') sinon, ainsi que si ctranslate2 est absent ou lève une exception ; torch n'est plus importé par clipper.gpu ; tests/test_gpu.py couvre les trois cas en simulant ctranslate2 (aucun GPU requis) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/1350fda09a9f@64437e9
    tree: scope/a01a90faa548
    criteria: a5a4f838c5c0
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Constat du 2026-09-25 sur la RTX 3050 Laptop : get_device() s'appuie sur torch, absent des dépendances, donc renvoie toujours cpu alors que ctranslate2 (déjà tiré par faster-whisper, qui est le seul consommateur GPU aujourd'hui) voit 1 device CUDA. Pas d'ajout de torch (dépendance lourde refusée). ADR-fb9b inchangé : le device vient toujours de clipper.gpu.
