# Guide utilisateur

Ce guide suppose l'installation faite (voir `README.md`). Toutes les
commandes sont `python -m clipper <commande> ...` ; `--config chemin.toml`
(défaut `config.toml`) et `-v`/`-vv` (journal détaillé des étapes, voir
*Sortie détaillée* ci-dessous) marchent sur toutes.

## Les 12 étapes du pipeline

Une vidéo passe, dans l'ordre, par `download, transcribe, scenes, audio,
moments, vision, parts, captions, reframe, subtitles, render, qa`. Chaque
étape lit ses entrées sous `workspace/<video_id>/` et y écrit son résultat ;
une étape dont le résultat existe déjà n'est pas relancée (sauf `--force`).

1. **download** — télécharge la vidéo (yt-dlp), au mieux en 1080p mp4.
2. **transcribe** — transcrit l'audio mot par mot (faster-whisper), avec
   correction de la transcription et du vocabulaire de noms propres par LLM.
3. **scenes** — détecte les changements de plan (scenedetect) et extrait des
   images clés.
4. **audio** — repère les pics sonores (rires, réactions...) pour aider à
   noter les moments.
5. **moments** — le LLM choisit les moments forts du transcript, notés selon
   `rubric.toml` (SPEC-53f3).
6. **vision** — regarde les images clés de chaque moment candidat et ajuste
   la note (bonus visuel), sans relancer le LLM de `moments`.
7. **parts** — découpe un moment trop long en plusieurs parties (chacune une
   vidéo séparée) si besoin.
8. **captions** — génère titre, légende, hashtags et accroche par clip.
9. **reframe** — calcule le plan de recadrage vertical (letterbox ou suivi de
   visage selon la config, voir *Formats* ci-dessous).
10. **subtitles** — génère les sous-titres (.ass), mot par mot, avec emphase
    choisie par LLM.
11. **render** — assemble tout avec ffmpeg (image, sous-titres, titre
    d'écran, audio normalisé) : `output/<video_id>/<clip_id>.mp4`.
12. **qa** — contrôle qualité automatique (résolution, durée, silence de
    tête, image noire...) ; un clip n'est prêt que si `qa.is_ready` le dit.

Un seul modèle lourd est en VRAM à la fois (ADR-fb9b) : les étapes tournent
en séquence et chacune libère le sien (whisper dans `transcribe`, détecteur
de visages dans `reframe`) avant la suivante.

## Sortie détaillée (`-v` / `-vv`)

Sans `-v`, la sortie ne change pas : les lignes `[étape] démarrée` / `[étape]
terminée en X s` de la CLI (indépendantes du niveau de journal). Avec `-v`
(niveau `INFO`), la console montre en plus, au fil de l'eau :

- début et fin de chaque étape, avec sa durée ;
- la progression des étapes longues, au plus toutes les 30 s ou tous les
  10 % : `download` (pourcentage et débit), `transcribe` (minutes d'audio
  traitées sur le total, facteur temps réel), `reframe`/`render`/`qa` (clip
  i/N avec sa durée), `vision` (lot d'images i/N) ;
- une ligne par appel LLM (usage, modèle, tokens entrée/sortie/cache, coût,
  durée, et son issue : réussi, réessai avant réparation, ou échec) ;
- en sélection par jury (`moments`, ADR-ff87), la décision de chaque candidat
  jugé (score final, retenu, rejeté, veto, ou exploration) ;
- un résumé de `moments` (candidats notés, retenus, raison des rejets) ;
- à la fin d'un run qui va jusqu'au bout : un résumé (durée par étape, nombre
  de clips, statuts qa, coût LLM total et par usage, chemin de `output/`).

`-vv` (niveau `DEBUG`) ajoute le détail : chaque événement de progression
(chaque appel LLM, chaque segment transcrit, chaque clip ou lot traité) sans
attendre le seuil des 30 s / 10 %, plus quelques lignes internes (détail des
appels LLM). `scenes` n'est pas concerné ici (sa propre progression est une
tâche séparée).

## Modes : review et auto

Réglé par `mode` à la racine de `config.toml` (`"review"` ou `"auto"`,
ADR-ad2e).

**review** (défaut) — `run` s'arrête après `moments`/`parts`, statut
`awaiting_review`. Chaque moment proposé attend une décision :

```powershell
python -m clipper decide <video_id> <moment_id> accepted
python -m clipper decide <video_id> <moment_id> rejected
python -m clipper decide <video_id> <moment_id> adjusted --start 12.5 --end 45.0 [--comment "..."]
```

...ou via l'interface web (`python -m clipper serve`, `http://127.0.0.1:8000`) :
liste des vidéos, moments à trancher, lancement du rendu, aperçu des clips.
Une fois chaque moment décidé, `python -m clipper render <video_id>` reprend
jusqu'au bout (moments refusés retirés, bornes ajustées reportées).

**auto** — `run` va jusqu'au bout tout seul ; l'étape `qa` remplace la revue
humaine. Une erreur transitoire (quota Claude, réseau, surcharge) remet la
vidéo en file d'attente (statut `queued`, `retry_at` calculé depuis
`[pipeline] retry_delays`) au lieu d'abandonner ou de produire un résultat
dégradé en silence :

```powershell
python -m clipper queue              # reprend les videos dont retry_at est passe
python -m clipper queue --watch --interval 60   # tourne en boucle
```

Au-delà de `[pipeline] max_attempts` échecs transitoires consécutifs (défaut
5), ou pour toute autre erreur : la vidéo passe `failed`.

`python -m clipper status <video_id>` affiche l'état courant en JSON à tout
moment (utile en mode auto pour suivre une vidéo sans l'interface web).

## Formats de sortie (`[reframe]`)

Deux réglages indépendants dans `config.toml` :

- `format` — `"letterbox"` (défaut, zoom fixe, sans suivi de visage) ou
  `"crop"` (suivi de visage, **option figée** : conservée telle quelle, pas
  d'évolution prévue).
- `layout` — seulement avec `format = "letterbox"` : `"letterbox"` (défaut)
  ou `"stream_auto"` (SPEC-3a88). En `stream_auto`, la facecam de la vidéo
  est détectée une fois (si elle a un visage à position quasi fixe sur une
  bonne part des images clés, dans une zone limitée de l'écran) ; les clips
  où elle est présente rendent en format stream (facecam fixe agrandie en
  haut, jeu en bas, **jamais de bascule dans un clip**), les autres en
  letterbox classique.

Le contrat de sortie d'un clip (`SPEC-6a47`, succède à `SPEC-6127`) :
`.mp4` vertical 1080x1920 + `.json` sidecar (titre, légende, hashtags,
rapport qa...). En letterbox, titre d'écran en haut, sous-titres dans la
bande floue du bas. Voir *Appel à l'abonnement* ci-dessous pour le pseudo de
chaîne et la carte de fin optionnels.

```toml
[reframe]
format = "letterbox"
layout = "stream_auto"   # ou "letterbox"
```

## Appel à l'abonnement (SPEC-6a47, `preset` par chaîne)

Désactivé par défaut : sans configuration explicite, le rendu, le sidecar et
la légende restent identiques à `SPEC-6127`. Utile pour une chaîne tierce
(ex. un·e streameur·se dont on republie les meilleurs moments) : pseudo de
chaîne discret sous le titre d'écran pendant tout le clip, carte de fin
« Abonne-toi ! » sur les dernières secondes, ligne d'appel et hashtags
supplémentaires dans la description. S'applique en letterbox et en stream
(`layout = "stream_auto"`) ; ignoré en `format = "crop"` (option figée,
`cta` reste `false` dans le sidecar, ce n'est pas une erreur).

Un preset par chaîne est un fichier de config séparé, passé avec `--config` :

```powershell
python -m clipper run https://www.twitch.tv/videos/<id> --config presets/madajel.toml
```

`presets/madajel.toml` :

```toml
[render]
cta_enabled = true
cta_handle = "twitch.tv/madajel"
cta_seconds = 2.0                        # duree de la carte de fin (defaut)
cta_text = "Abonne-toi !"                # texte de la carte de fin (defaut)

[captions]
cta_line = "Abonne-toi sur Twitch pour plus de lives !"
cta_hashtags = ["#twitch", "#horreur"]
```

`cta_enabled` sans `cta_handle` (côté `[render]`) ou sans `cta_text`, ou un
`cta_seconds` <= 0 ou >= la durée d'un clip, est une erreur explicite
(ADR-ad2e : jamais de CTA à moitié activé) — jamais une carte de fin ou un
pseudo tronqué ou absent en silence. Les réglages de mise en page (tailles de
police, marges) vivent dans `CONFIG_DEFAULTS` de `clipper/render.py`
(`cta_handle_font_size`, `cta_card_font_size`...).

## Configuration (`config.toml`)

Chaque étape (module `clipper/<etape>.py`) déclare son propre
`CONFIG_DEFAULTS` : une table `[<etape>]` dans `config.toml` est validée
contre ce dict — clé absente de `CONFIG_DEFAULTS` refusée, section sans
module `clipper.<etape>` ou sans `CONFIG_DEFAULTS` refusée aussi (voir
`clipper/config.py`). La liste ci-dessous couvre les réglages les plus
utiles ; pour le détail complet et à jour, `CONFIG_DEFAULTS` dans le module
concerné fait foi.

Racine (pas de section) :

```toml
mode = "review"          # ou "auto"
workspace_dir = "workspace"
output_dir = "output"
```

`[pipeline]` — `max_attempts` = 5 (échecs transitoires avant `failed`),
`retry_delays` = `[300, 900, 1800, 3600]` (secondes, le dernier sert
au-delà), `feedback_examples` = 10 (décisions passées données en exemple au
LLM de `moments`).

`[llm]` — voir *Modèles et consommation Claude* ci-dessous.

`[download]` — `cookies_file`, `cookies_from_browser` (vidéos privées/âge
restreint), `js_runtimes` = `"node"`.

`[transcribe]` — `model` = `"small"` (taille faster-whisper : tiny, base,
small, medium, large-v3...), `language` (défaut détection auto),
`beam_size` = 5, `vad_filter` = `true`, `vocab`/`transcript_fix` = `true`
(corrections par LLM), `fix_chunk_words` = 3000, `fix_parallel` = 4.

`[scenes]` — `threshold` = 27.0 (sensibilité scenedetect), `jpeg_quality` =
95, `extract_parallel` = 4.

`[audio]` — `sample_rate` = 16000, `window_seconds` = 1.0,
`median_window_seconds` = 15.0, `peak_threshold_db` = 6.0.

`[moments]` — `selection` = `"single"` (ou `"jury"`, forcé en mode auto),
`rubric_path` = `"rubric.toml"`, `max_transcript_chars`, `chunk_chars`
(découpe les longues vidéos), `exploration_share` = 0.1 (part de candidats
hors grille stricte, pour ne pas se figer sur les mêmes formats).

`[vision]` — `window_seconds` = 10, `batch_size` = 8, `max_width` = 768,
`parallel` = 4.

`[parts]` — `rubric_path` = `"rubric.toml"`, `part_overlap_seconds` = 3,
`parallel` = 4.

`[captions]` — `title_max_chars` = 100, `caption_max_chars` = 300,
`hashtags_max` = 8, `hook_words_max` = 8, `parallel` = 4 (moments traités en
parallèle), `cta_line`/`cta_hashtags` (SPEC-6a47, vides par défaut, voir
*Appel à l'abonnement* ci-dessus).

`[reframe]` — voir *Formats* ci-dessus, plus le détecteur de visages
(`detector` = `"mediapipe"`, `min_confidence` = 0.5, `sample_fps` = 5.0),
`output_width`/`output_height` = 1080/1920, `letterbox_zoom` = 1.3.

`[subtitles]` — `font_name` = `"Poppins ExtraBold"`, `font_size` = 96,
`min_words_per_group`/`max_words_per_group` = 2/4, `emphasis` = `true`
(emphase choisie par LLM), `parallel` = 4 (clips traités en parallèle, lu par
le pipeline).

`[render]` — `crf` = 20, `x264_preset` = `"medium"`, `nvenc_preset` = `"p5"`
(si GPU), `audio_bitrate` = `"192k"`, normalisation loudness
(`loudnorm_i/tp/lra`), réglages du titre d'écran (`title_font_size`,
`title_pad_x/y`...) et de l'accroche (`hook_seconds`, `hook_font_size`,
`hook_margin_top`). Encodeur choisi par `clipper.gpu` (`h264_nvenc` si CUDA
détecté, sinon `libx264`). `cta_enabled`/`cta_handle`/`cta_seconds`/
`cta_text` (SPEC-6a47, désactivé par défaut, voir *Appel à l'abonnement*
ci-dessus) et leurs réglages de mise en page (`cta_handle_font_size`,
`cta_card_font_size`...).

`[qa]` — `expected_width`/`expected_height` = 1080/1920,
`duration_tolerance` = 0.5, seuils de silence et d'image noire
(`black_min_seconds` = 1.0 avertit, `black_block_seconds` = 3.0 bloque le
clip), `parallel` = 4.

`[feedback]` — `journal_path` = `"state/feedback.jsonl"` (décisions humaines
en mode review).

`[outcomes]` — `journal_path` = `"state/outcomes.jsonl"`.

`[web]` — `port` = 8000 (host toujours `127.0.0.1`, jamais configurable,
ADR-09ad : l'interface web ne sert qu'une page statique, aucune logique
métier dedans).

`[jury]` (ADR-ff87, mode `selection = "jury"`) — `threshold` = 20 (écart de
score qui déclenche un débat entre juges), `quorum`, `seed` = 0, `parallel` =
5, `judges` (composition : cinq juges par défaut — retention, spectateur,
monteur, avocat, conformite — chacun avec son `usage` LLM, son `model`
strong/fast et un veto pour `conformite`).

## Modèles et consommation Claude (`[llm]`)

Tout appel LLM passe par `clipper.llm.ask(...)` (ADR-b1c1), configuré par
usage (ex. `moments`, `parts`, `vision`, `transcript_fix`, `jury_retention`) :

```toml
[llm]
backend = "claude-cli"     # ou "claude-api", "ollama"
repair_attempts = 1        # 0 = une reponse refusee echoue tout de suite

[llm.usages.moments]
model = "strong"           # niveau (strong|fast) ou nom de modele exact
```

Un usage absent de `[llm.usages]` prend le backend global et le niveau
`fast`. Par défaut (`CONFIG_DEFAULTS`), `moments` et `parts` sont en
`strong`, tout le reste en `fast`. Le backend `claude-cli` (défaut) traduit
`strong`/`fast` en `opus`/`sonnet` (`[llm.claude_cli.models]`) ; adapte ces
noms si tes modèles disponibles diffèrent.

Chaque appel réussi ou définitivement refusé est journalisé, pendant qu'une
vidéo avance, dans `workspace/<video_id>/llm_usage.jsonl` : une ligne JSON
par appel (`usage`, `model`, `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cost_usd`, `duration_s`). Avec `-v`, un résumé cumulé
par usage est aussi journalisé en fin de passage. Pour connaître l'ordre de
grandeur réel de la consommation d'une vidéo, regarde ce fichier directement
(il n'y a pas de chiffre générique fiable à donner ici : ça dépend de la
longueur de la vidéo, du nombre de clips, du mode de sélection et des
modèles choisis) :

```powershell
Get-Content workspace\<video_id>\llm_usage.jsonl | ConvertFrom-Json | Measure-Object cost_usd -Sum
```

## Dépannage

**`ModuleNotFoundError` / erreur d'import cv2 après installation** —
installé avec `pip` au lieu de `uv`. `pip` seul ignore
`[tool.uv] override-dependencies` (qui force un seul paquet OpenCV,
`opencv-contrib-python`) et peut installer à la fois `opencv-python`
(demandé par `scenedetect`) et `opencv-contrib-python` (demandé par
`mediapipe`), qui s'écrasent l'un l'autre sur le même module `cv2`.
Réinstalle avec `uv pip install -e ".[test]"` dans un `.venv` neuf.

**faster-whisper reste sur CPU alors qu'un GPU NVIDIA est présent** — sous
Windows, CTranslate2 a besoin des paquets `nvidia-cublas-cu12` et
`nvidia-cudnn-cu12` (non installés automatiquement) et de leurs dossiers
`bin` dans le PATH au lancement. Sans ça, `clipper.gpu.get_device()` ne voit
pas CUDA et retombe sur CPU **en silence** (ce n'est pas un bug : l'absence
de CUDA est simplement non détectée). Voir *Pièges* dans `AGENTS.md`.

**Le premier `run` est lent / télécharge quelque chose** — le modèle de
détection de visages mediapipe (`blaze_face_short_range.tflite`) est
téléchargé au premier lancement dans `%USERPROFILE%\.cache\clipper\` : il
faut le réseau une fois, les lancements suivants réutilisent le cache.

**`erreur : fichier de config introuvable : ...`** — obtenu seulement avec
`--config chemin.toml` explicite pointant vers un fichier absent (jamais en
silence, voir `clipper/config.py`). Sans `--config`, l'absence de
`config.toml` n'est pas une erreur : les valeurs par défaut (`mode =
"review"`, etc.) s'appliquent. Copie `config.example.toml` vers
`config.toml` si tu veux personnaliser.

**`cle(s) inconnue(s) dans la section [...]`** — une clé de `config.toml` ne
figure pas dans le `CONFIG_DEFAULTS` du module correspondant (faute de frappe
ou réglage qui n'existe pas) ; le message liste les clés refusées.

**`claude` indisponible / quota dépassé** — en mode `auto`, la vidéo passe
`queued` et sera reprise par `python -m clipper queue` (ou `--watch`) une
fois `retry_at` passé ; en mode `review`, l'étape en échec remonte
directement (relance `run`/`render` une fois le problème résolu).

**Détecter une erreur de l'API Claude avant une vidéo d'1 h** — les erreurs
réelles de l'API (ex. un `400` inattendu) n'apparaissent qu'à l'usage : le
test de fumée `tests/integration/test_smoke_real.py` fait un vrai petit
appel `claude -p` pour chaque usage LLM du pipeline (`vocab`,
`transcript_fix`, `moments`, les 5 juges, `vision`, `parts`, `captions`,
`layout`, `emphasis`, `qa`), avec une entrée minuscule construite via le
vrai code de l'étape. Coût typique < 1 $ pour l'ensemble. Sauté par défaut
(consomme du quota) :

```powershell
$env:CLIPPER_CLAUDE_INTEGRATION = "1"
pytest tests/integration/test_smoke_real.py -k "not mini_video" -v -s
```

`-s` affiche la ligne `llm_usage.jsonl` (modèle, tokens, coût, durée) de
chaque appel. `tests/test_smoke_coverage.py` (toujours exécuté, sans
réseau) vérifie que la liste d'usages testés couvre bien tout le code du
pipeline, pas une liste recopiée à la main.

Option plus lourde : rejouer le pipeline complet (mode `auto`) sur un
extrait de 5 min d'une vidéo déjà présente dans `workspace/` (ffmpeg
requis) :

```powershell
$env:CLIPPER_CLAUDE_INTEGRATION = "1"
$env:CLIPPER_SMOKE_VIDEO = "workspace\<video_id>\<video_id>.mp4"
pytest "tests/integration/test_smoke_real.py::test_smoke_mini_video_end_to_end" -v -s
```
