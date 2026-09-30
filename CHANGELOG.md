# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Ce dépôt n'utilise pas (encore) de versionnage sémantique strict : la
version 0.1.0 est une pré-version, avant tout tag ou publication.

## [0.1.0] - 2026-09-30

Première pré-version : pipeline complet YouTube/VOD Twitch -> clips TikTok
verticaux sous-titrés, en local.

### Ajouté

- Pipeline en 12 étapes (`download, transcribe, scenes, audio, moments,
  vision, parts, captions, reframe, subtitles, render, qa`), chaque étape un
  module `clipper/` qui lit/écrit sous `workspace/<video_id>/`, enchaînées
  uniquement par `clipper.pipeline` (ADR-b16b).
- Téléchargement YouTube et VOD Twitch (`twitch.tv/videos/<id>`) via yt-dlp.
- Transcription mot par mot (faster-whisper, `BatchedInferencePipeline`,
  `batch_size=8`), avec correction de la transcription et du vocabulaire de
  noms propres par LLM.
- Sélection des moments forts par LLM notée selon une grille (`rubric.toml`,
  SPEC-0eec), avec un mode jury à cinq juges (retention, spectateur,
  monteur, avocat, conformite) pour la sélection en mode `auto` (ADR-ff87),
  débat déclenché sur écart de score et apprentissage à partir des
  décisions passées sans uniformisation des juges (ADR-1cf0).
- Ajustement visuel des moments par lecture des images clés (étape
  `vision`), découpe des moments trop longs en plusieurs parties (`parts`).
- Génération du titre, de la légende, des hashtags et de l'accroche de
  chaque clip par LLM (`captions`).
- Deux formats de recadrage vertical (`[reframe]`) : `letterbox` (zoom fixe,
  titre d'écran en haut, sous-titres dans la bande floue du bas, SPEC-6127)
  et `stream_auto` (facecam détectée une fois, agrandie en haut, jeu en bas,
  jamais de bascule dans un clip, SPEC-3a88) ; `crop` (suivi de visage)
  conservé comme option figée.
- Sous-titres mot par mot (.ass) avec emphase choisie par LLM.
- Appel à l'abonnement optionnel (SPEC-6a47, désactivé par défaut) : pseudo de
  chaîne discret sous le titre d'écran, carte de fin « Abonne-toi ! » sur les
  dernières secondes, ligne d'appel et hashtags dans la description ; réglé
  par un fichier de config par chaîne (`--config`).
- Rendu ffmpeg (image, sous-titres, titre d'écran, audio normalisé),
  encodeur choisi par `clipper.gpu` (NVENC si CUDA détecté, sinon libx264).
- Contrôle qualité automatique (`qa`) : résolution, durée, silence de tête,
  image noire — un clip n'est prêt que si `qa.is_ready` le confirme.
- Deux modes d'exécution : `review` (validation humaine de chaque moment
  via `python -m clipper decide` ou l'interface web) et `auto` (le
  pipeline va jusqu'au bout, `qa` remplace la revue humaine), sans repli
  silencieux sur erreur (ADR-ad2e) : une erreur transitoire remet la vidéo
  en file d'attente (`python -m clipper queue`), une erreur définitive la
  passe `failed`.
- Interface web locale (`python -m clipper serve`, `clipper/web/`) : page
  statique servie par FastAPI, aucune logique métier côté serveur
  (ADR-09ad).
- Tout appel LLM centralisé dans `clipper.llm.ask(...)` (ADR-b1c1),
  backends interchangeables (`claude-cli` par défaut, `claude-api`,
  `ollama`), modèle configurable par usage, réponse validée contre un
  schéma JSON, consommation journalisée par vidéo
  (`workspace/<video_id>/llm_usage.jsonl`).
- Résolution automatique CPU/CUDA (`clipper.gpu`), un seul modèle lourd en
  VRAM à la fois, libéré explicitement après usage (ADR-fb9b).
- Suite de tests tournant entièrement sur CPU, sans réseau ni vrai
  modèle/Claude par défaut (`FakeBackend`) ; tests optionnels marqués
  `skipif`, sautés sauf variable d'environnement explicite
  (`CLIPPER_CLAUDE_INTEGRATION=1`, `CLIPPER_REAL_MODELS=1`).
- Script d'installation `tools/setup.ps1` (vérifie uv, Python 3.11, ffmpeg,
  `claude`, `ank`, GPU optionnel).

### Connu comme limite

- Pré-version : pas de garantie de stabilité de l'interface en ligne de
  commande ni du format de configuration.
- Chaque vidéo traitée consomme du quota Claude (coût variable selon la
  durée, le nombre de clips et le mode de sélection ; voir
  `docs/benchmarks/rtx3050.md`).
- La grille de notation des moments (`rubric.toml`) est calée sur la
  parole : un moment fort sans dialogue marquant peut être sous-noté.
- Aucune publication automatique sur TikTok : le dépôt produit les clips
  et leurs métadonnées, la mise en ligne reste manuelle.
