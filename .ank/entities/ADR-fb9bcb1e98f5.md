---
id: ADR-fb9bcb1e98f5
type: adr
slug: gpu-d-tection-auto-cuda-cpu-un-seul-mod-le-lourd
title: "GPU : détection auto CUDA/CPU, un seul modèle lourd en VRAM à la fois"
created: 2026-09-25T09:35:26Z
author: claude-plan
status: accepted
scope:
  - clipper/**
constraint: |
  Le device se résout via clipper.gpu (cuda si disponible, sinon cpu), jamais codé en dur. Une étape qui charge un modèle lourd (whisper, détection de visages, VLM local, LLM local) le libère avant de rendre la main ; deux modèles lourds ne sont jamais chargés en même temps. Tout le pipeline doit tourner sur CPU (lentement) pour les tests.
ratified: 7439bad46e39
verified:
  - by: UP60041549@wl0023729
    at: 2026-09-25T09:43:52Z
schema: 4
version: 2
---

## Contexte
Cible : PC perso avec RTX 3050 portable (probablement 4 Go de VRAM, à mesurer), secours : PC tour 3050. Dev initial sur un PC sans NVIDIA.
4 Go ne tiennent pas whisper large-v3 + un VLM 7B en même temps.

## Décision
- `clipper.gpu` expose le device et le compute_type (ex. `float16`/`int8_float16` sur CUDA, `int8` sur CPU).
- Chargement / déchargement explicites par étape (`del model`, `torch.cuda.empty_cache()` ou équivalent, `keep_alive: 0` côté Ollama).
- Rendu ffmpeg : NVENC si dispo, sinon libx264.

## Conséquences
Les étapes sont séquentielles par vidéo. La tâche de benchmark 3050 fixe les tailles de modèles par défaut.
