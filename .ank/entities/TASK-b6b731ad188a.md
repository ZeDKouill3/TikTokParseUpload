---
id: TASK-b6b731ad188a
type: task
slug: banc-whisper-small-vs-large-v3-turbo-sur-rtx-305
title: Banc whisper small vs large-v3-turbo sur RTX 3050 (vitesse, VRAM, qualité FR, corrections transcript_fix) et choix du modèle par défaut
created: 2026-09-30T10:18:03Z
author: nicoc@zedk_ordi
status: done
scope:
  - docs/benchmarks/whisper-modeles.md
  - clipper/transcribe.py
  - tests/test_transcribe.py
  - config.example.toml
blocked_by: []
done_criteria: |
  docs/benchmarks/whisper-modeles.md compare small et large-v3-turbo (même extrait de 10 min de 7VaA8XUKrAY, parole FR, puis 10 min de v2887271276, stream de jeu) : durée de transcription, facteur temps réel, pic VRAM (échantillonnage nvidia-smi 1 Hz PENDANT le banc seulement), texte des 2 versions sur 20 passages où elles diffèrent (tableau pour jugement humain), nombre et coût réel des corrections transcript_fix sur chaque version (1 appel réel par version) ; recommandation argumentée ; si large-v3-turbo tient en VRAM avec marge (< 3,2 Go) et améliore la qualité, CONFIG_DEFAULTS['model'] de clipper/transcribe.py passe à large-v3-turbo (compute_type adapté via clipper.gpu, un seul modèle lourd en VRAM, ADR-fb9b) avec test unitaire ; config.example.toml à jour ; aucun passage vidéo complet.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/497e04d44dfb@60312ba
    tree: scope/462f9ed362e0
    criteria: 9c4b42980847
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-09-30 : le GPU (RTX 3050 Laptop 4 Go) n'est utilisé qu'à 1,68 Go au pic (whisper small). Hypothèse : large-v3-turbo transcrit mieux le français et réduit les corrections transcript_fix (~4 $ par vidéo de 67 min avant correctifs). Bancs existants : docs/bench-whisper-vitesse.md (small, batch 8 = x4,9), docs/benchmarks/rtx3050.md (mentionne 2,0–2,8 Go estimés pour un plus gros modèle). Extraire les 10 min avec ffmpeg depuis workspace/<id>/<id>.mp4 (ou l'audio déjà extrait) dans research/whisper-banc/. Téléchargement du modèle large-v3-turbo autorisé (une fois). Écran bleu 0x7E le 2026-09-30 lié au pilote NVIDIA : nvidia-smi seulement pendant le banc, jamais en boucle hors banc. Ne pas lancer tant qu'un autre calcul GPU tourne (vérifier qu'aucun `python -m clipper` n'est actif).
