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
  Une fois un clip en stream, `stream_variant` (SPEC-76dc) choisit
  l'agencement visuel : `"top"` (défaut, comportement inchangé, décrit
  ci-dessus) ou `"split"` (webcam en haut sur ~1/3 de la hauteur, jeu en bas
  pleine largeur, badge de style optionnel à la jonction) — voir *Agencement
  stream split* ci-dessous.

Le contrat de sortie d'un clip (`SPEC-6a47`, succède à `SPEC-6127`) :
`.mp4` vertical 1080x1920 + `.json` sidecar (titre, légende, hashtags,
rapport qa...). En letterbox, titre d'écran en haut, sous-titres dans la
bande floue du bas. Voir *Appel à l'abonnement* ci-dessous pour le pseudo
d'affichage et la carte de fin optionnels.

```toml
[reframe]
format = "letterbox"
layout = "stream_auto"   # ou "letterbox"
```

## Appel à l'abonnement (SPEC-6a47, `preset` par style)

Désactivé par défaut : sans configuration explicite, le rendu, le sidecar et
la légende restent identiques à `SPEC-6127`. Utile pour un contenu tiers
(ex. un·e streameur·se dont on republie les meilleurs moments) : pseudo
d'affichage discret sous le titre d'écran pendant tout le clip, carte de fin
« Abonne-toi ! » sur les dernières secondes, ligne d'appel et hashtags
supplémentaires dans la description. S'applique en letterbox et en stream
(`layout = "stream_auto"`) ; ignoré en `format = "crop"` (option figée,
`cta` reste `false` dans le sidecar, ce n'est pas une erreur).

Un preset par style est un fichier de config séparé, passé avec `--config` :

```powershell
python -m clipper run https://www.twitch.tv/videos/<id> --config presets/ma-chaine.toml
```

`presets/ma-chaine.toml` :

```toml
[render]
cta_enabled = true
cta_handle = "twitch.tv/ma_chaine"
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

## Agencement stream split (SPEC-76dc, `preset` par style)

Un second agencement visuel pour les clips déjà en stream (`stream_variant`,
voir *Formats de sortie* ci-dessus), pensé pour reproduire le montage
« webcam en haut, jeu en bas » qu'une streameuse ou un streamer fait
déjà lui-même : deux zones fixes qui se partagent toute la hauteur (jamais de
déformation, chaque zone est recadrée au ratio de son rectangle de
destination), un badge de style optionnel (logo + pseudo, fond noir par
défaut ou sans fond) à leur jonction, et un style de sous-titres à deux
couleurs (mot en train
d'être prononcé dans une couleur distincte, pas de fond). `title_enabled`
(nouveau réglage, défaut `true` — comportement inchangé) permet de retirer le
titre d'écran, utile ici puisque ce modèle n'en a pas.

`presets/ma-chaine-stream.toml` :

```toml
[reframe]
layout = "stream_auto"
stream_variant = "split"

[render]
title_enabled = false             # pas de titre d'ecran pour ce modele
cta_enabled = false                # ni carte de fin
badge_enabled = true
badge_logo = "presets/logo-ma-chaine.png"   # PNG, jamais dans clipper/assets
badge_name = "ma_chaine"

[subtitles]
split_current_word_color = "#9146FF"   # violet Twitch (defaut) ; #RRGGBB ou un nom
split_shadow_enabled = false
```

Les zones (`split_webcam_dest`, `split_gameplay_dest`, `badge_dest`,
`split_subtitle_dest`, toutes `[reframe]`) ont des valeurs par défaut qui
correspondent à la maquette de référence ; réglables (mêmes clés
`{x, y, w, h}` en pixels du canevas 1080x1920), mais une config qui les fait
déborder du canevas, se chevaucher entre elles ou sortir de la zone sûre
TikTok (badge, sous-titres) est une erreur explicite au chargement
(ADR-ad2e). `badge_enabled` sans `badge_logo` (fichier
introuvable inclus) ou sans `badge_name`, ou activé sur un layout qui n'a pas
de zone badge (letterbox, stream `"top"`, format crop), est aussi une erreur
explicite : le badge remplace le pseudo d'affichage de l'appel à l'abonnement
quand les deux sont actifs, sans toucher à la carte de fin.

Le groupe logo + nom est toujours centré horizontalement sur `badge_dest`
(largeur ajustée au contenu, mesurée avec la vraie police) : jamais de vide
asymétrique. `badge_background` (défaut `"black"`) dessine un rectangle
plein derrière tout le bandeau ; `"none"` retire ce rectangle derrière le
nom — le nom reste lisible grâce à `badge_name_outline` /
`badge_name_outline_color` (contour, défauts `3` / `"black"`) et, si besoin,
une ombre réglable (`badge_name_shadow_enabled`, défaut `false`, puis
`badge_name_shadow_color` et `badge_name_shadow_offset`). Le carré du logo
lui-même n'est jamais noir : il est toujours rempli avec `badge_logo_fill`
(quel que soit `badge_background`), par défaut vide (`""`) pour
échantillonner automatiquement la couleur au coin de l'image du logo
(ex. le fond violet déjà présent dans un logo Twitch) — réglable à une
couleur fixe si besoin.

## Console de gestion

`python -m clipper serve` lance la console web (FastAPI + page statique, sans
étape de build) et, en sous-processus, le **worker** qui traite la file. Par
défaut : `http://127.0.0.1:8000` (`[web] port` ou `--port`). La page ne fait
aucun traitement vidéo, audio ou LLM : elle lit `workspace/`, `output/`,
`state/` et `presets/`, et demande le travail au worker. Fermer l'onglet, ou
même arrêter le serveur, n'interrompt pas une vidéo en cours de traitement.
`python -m clipper worker` lance le worker seul (sans interface).

### Les 8 écrans

La navigation (barre latérale, onglets en bas sur téléphone) donne :

1. **Accueil** (tableau de bord) : vidéos en cours (étape, progression, durée
   restante estimée quand le pipeline la donne), file d'attente (passer une
   vidéo en tête, la retirer), vidéos en échec ou remises en file avec leur
   raison, VOD « à confirmer » issues de la surveillance, clips à valider,
   prochaines publications, coût LLM du jour et de la semaine par usage, état
   matériel (GPU ou CPU).
2. **Vidéos** : liste filtrable (style, statut, texte) ; ajout par URL avec
   choix du style (ou « sans style » pour `config.toml` seul) ; fiche
   avec la frise des 12 étapes, le journal suivi en direct, « relancer depuis
   cette étape » et « annuler ».
3. **Revue** (mode `review`) : lecteur de la source calé sur le moment, score,
   accroche, justification du jury, bornes début/fin ajustables ; raccourcis
   `A` (accepter), `R` (refuser), `J`/`K` (suivant/précédent), espace
   (lecture). « Lancer le rendu » n'est actif que quand chaque moment a une
   décision ; sinon la raison s'affiche.
4. **Clips** : galerie 9:16 par vidéo et par style, lecteur, fiche du clip
   (titre d'écran, description, hashtags, partie N/M, `qa_status`, `issues`),
   édition de la description et des hashtags, du titre d'écran (re-rendu),
   approuver / refuser, re-rendre, télécharger le mp4, copier la description.
5. **Styles** : liste (nom, source, surveillance, mode),
   création et édition d'un preset par formulaire, chaque champ montrant sa
   valeur héritée de `config.toml` tant que le preset ne la redéfinit pas ; une
   erreur de validation s'affiche sous le champ. Deux outils : l'**éditeur
   d'agencement** (canevas 1080×1920 : zones webcam, jeu, badge, sous-titres à
   glisser et redimensionner sur une image clé d'une vidéo du style,
   enregistrées dans `[reframe]` ; un agencement qui déborde ou se chevauche
   est refusé avec le message de `reframe`) et l'**aperçu du style des
   sous-titres** sur une phrase d'exemple, rendu par le pipeline.
6. **Publication** : par compte, clips `approved` / `scheduled`, calendrier
   hebdomadaire des créneaux (glisser-déposer sur un créneau libre),
   télécharger, copier la description, « marquer publié », « repasser en
   attente ». La mise en ligne reste manuelle : le dépôt ne publie rien sur
   TikTok.
7. **Statistiques** : par clip (résultats importés, décisions humaines, QA),
   coûts LLM par vidéo, usage et période, durée par étape, import CSV des
   statistiques de la plateforme.
8. **Réglages** : `config.toml` en formulaire (mode global, dossiers, backend
   et modèle LLM par usage, surveillance), écriture validée avant d'être
   enregistrée ; section « Accès » (hôte, jeton masqué) en lecture seule avec
   la commande à lancer.

Toute erreur de l'API s'affiche en clair (toast et à la place de l'objet),
jamais un tiret muet. Les actions qui ont un inverse (décision de revue,
approbation) proposent « Annuler » pendant 5 secondes ; les autres (annuler un
traitement, refuser une série, supprimer un style) demandent confirmation.

### La file de traitement

Ajouter une vidéo (écran Vidéos, ou VOD confirmée) l'inscrit dans
`state/queue.json`. Le worker traite **une vidéo à la fois**, chacune dans un
processus enfant `python -m clipper` ; « annuler » termine ce processus.
L'ordre est modifiable (passer en tête, retirer). Une erreur transitoire
remet la vidéo en file avec sa raison et l'heure de reprise (`retry_at`) ;
une erreur définitive la passe en `failed`. Le worker lit les mêmes fichiers
`state/` que le serveur, sous verrou de fichier.

### Presets de style en surcouche

Un style est un fichier `presets/<nom>.toml` : une **surcouche** fusionnée
clé par clé sur `config.toml`. Seules les clés redéfinies figurent dans le
fichier ; tout le reste est hérité. La table `[channel]` (validée par
`CONFIG_DEFAULTS` de `clipper/channel.py`) décrit le style lui-même :
`display_name`, `source_url`, `watch`, `watch_interval_s`,
`watch_min_duration_s`, `mode`, `timezone`, `logo`. Le compte de publication
et les créneaux réguliers n'y sont plus : ils appartiennent au compte (écran
Comptes), chaque publication choisit le sien. Un ancien preset qui porte
encore `slots` / `tiktok_account` est migré au démarrage (créneaux repris sur
ce compte s'il n'en a pas déjà, clés retirées du fichier). Exemple `presets/ma_chaine.toml` :

```toml
[channel]
display_name = "ma_chaine"
source_url = "https://www.twitch.tv/ma_chaine/videos"
watch = true
mode = "review"

[reframe]
format = "stream_auto"
stream_variant = "split"
```

Le nom (`ma_chaine`, minuscules, chiffres, `_` et `-`) est celui du fichier.
Le formulaire de l'écran Styles lit et écrit ce même fichier ; le même
preset s'utilise en ligne de commande avec
`--config presets/ma_chaine.toml`.

### Le dossier `state/`

Tout état hors vidéo vit en fichiers JSON sous `state/`, jamais en base ni en
mémoire seule (un redémarrage reprend où l'on en était) :

- `state/queue.json` : la file de traitement ;
- `state/watch/<chaine>.json` : surveillance (vidéos vues, VOD en attente de
  confirmation, dernière erreur) ;
- `state/publish/<chaine>.json` : file de publication et créneaux pris.

Chemins réglables dans `[worker]`, `[watch]` et `[publish]`. Les vidéos
elles-mêmes restent sous `workspace/<video_id>/` et `output/<video_id>/`.

### Surveillance des VOD

Avec `watch = true` dans `[channel]`, le worker interroge la `source_url` du
style toutes les `watch_interval_s` secondes (rien n'est téléchargé pour
lister). Il ignore les VOD plus courtes que `watch_min_duration_s`, les
directs en cours et celles déjà vues. En mode `auto` les nouvelles VOD sont
mises en file ; en mode `review` elles apparaissent « à confirmer » sur
l'Accueil, où l'on choisit de les confirmer (mise en file) ou de les ignorer.
Une erreur de listage est affichée (`last_error`), le style reste surveillé.

### Notifications

Un toast s'affiche à chaque passage d'une vidéo à `done`, `failed`,
`awaiting_review` ou `queued`. Le bouton cloche de l'en-tête active en plus
les **notifications du navigateur** : la permission n'est demandée qu'à ce
clic, jamais au chargement de la page, et le réglage reste local au
navigateur (`localStorage`). Si le flux temps réel (`/api/events`) tombe, un
bandeau « connexion perdue » apparaît et la page interroge l'API toutes les
5 secondes.

### Accès distant par jeton

Par défaut la console n'écoute que sur `127.0.0.1` et n'exige rien. Pour la
joindre depuis un téléphone du même réseau :

```toml
[web]
token = "un-jeton-long-et-aleatoire"
```

```bash
python -m clipper serve --host 0.0.0.0
```

`--host` (ou `[web] host`) autre que `127.0.0.1` **exige** `[web] token` :
sans jeton, `serve` refuse de démarrer avec un message qui nomme la clé, sans
lancer ni serveur ni worker. Avec un jeton, toute requête `/api` et `/media`
sans jeton valide reçoit 401 ; la page, elle, se charge et affiche une saisie
du jeton, gardé ensuite dans un cookie du navigateur (`SameSite=Strict`).
Un script peut l'envoyer dans l'en-tête `x-clipper-token`. Le jeton ne se
modifie pas depuis l'interface : fichier `config.toml`, puis redémarrage.

Limites, à lire avant d'ouvrir le port :

- **Réseau local seulement.** Un seul jeton partagé, un seul utilisateur, pas
  de comptes ni de limitation de tentatives.
- **Pas de TLS** : le jeton et les vidéos circulent en clair. Sur un réseau de
  confiance seulement.
- **N'expose jamais le port sur Internet** sans reverse proxy TLS devant
  (Caddy, nginx...) ; sans lui, ne redirige pas le port depuis la box.

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
`rubric_path` = `"rubric.toml"` (chemin utilisé tel quel ; `"builtin"` :
grille embarquée dans le paquet, sans fichier local), `max_transcript_chars`,
`chunk_chars` (découpe les longues vidéos), `exploration_share` = 0.1 (part
de candidats hors grille stricte, pour ne pas se figer sur les mêmes
formats).

`[vision]` — `window_seconds` = 10, `batch_size` = 8, `max_width` = 768,
`parallel` = 4.

`[parts]` — `part_overlap_seconds` = 3, `parallel` = 4. La grille des durées
est celle de l'étape moments (`rubric.path` de `moments.json`) ; l'ancienne clé
`rubric_path` de `[parts]` est refusée.

`[captions]` — `title_max_chars` = 100, `caption_max_chars` = 300,
`hashtags_max` = 8, `hook_words_max` = 8, `screen_title_words_max` = 6,
`screen_title_allow_emoji` = `false` (SPEC-6a86 : sans configuration
explicite, un `screen_title` avec un emoji est refusé — activer l'option ne
le rend pas obligatoire, elle permet seulement d'en accepter un au plus),
`screen_title_forbidden_words` (liste de mots d'emphase clickbait refusés
dans `screen_title`, insensible à la casse et aux accents, mot entier ;
réglable par preset de style), `parallel` = 4 (moments traités en
parallèle), `cta_line`/`cta_hashtags` (SPEC-6a47, vides par défaut, voir
*Appel à l'abonnement* ci-dessus).

`[reframe]` — voir *Formats* ci-dessus, plus le détecteur de visages
(`detector` = `"mediapipe"`, `min_confidence` = 0.5, `sample_fps` = 5.0),
`output_width`/`output_height` = 1080/1920, `letterbox_zoom` = 1.3.
`stream_variant` (SPEC-76dc, voir *Agencement stream split* ci-dessus) et ses
zones (`split_webcam_dest`, `split_gameplay_dest`, `badge_dest`,
`split_subtitle_dest`).

`[subtitles]` — `font_name` = `"Poppins ExtraBold"`, `font_size` = 96,
`min_words_per_group`/`max_words_per_group` = 2/4, `emphasis` = `true`
(emphase choisie par LLM), `parallel` = 4 (clips traités en parallèle, lu par
le pipeline). Rien ne s'affiche pendant un silence (TASK-9ee7) : `hold_s`
(0,3 s) — un groupe de mots reste affiché au plus ce temps après la fin de
son dernier mot, borné par le début du suivant — `gap_s` (0,6 s) — un écart
de plus que ça avant le mot suivant coupe le groupe, rien n'est affiché
pendant l'écart — `max_word_s` (1,5 s) — la fin d'un mot isolé, parfois
étirée par faster-whisper sur le silence qui suit, est bornée à ce temps
depuis son début. Style de l'agencement stream split (SPEC-76dc, préfixe
`split_`, jamais d'appel LLM) : `split_font_name`/`split_font_size`,
`split_uppercase`, `split_text_color`/`split_current_word_color` (le mot en
train d'être prononcé) — couleurs `#RRGGBB` ou un nom (`white`, `black`,
`purple`...), pas le format ASS des réglages ci-dessus —
`split_outline_color`/`split_outline`, `split_shadow_enabled` (défaut
`false`) et `split_shadow_color`/`split_shadow_offset`.

`[render]` — `crf` = 20, `x264_preset` = `"medium"`, `nvenc_preset` = `"p5"`
(si GPU), `audio_bitrate` = `"192k"`, normalisation loudness
(`loudnorm_i/tp/lra`), réglages du titre d'écran (`title_font_size`,
`title_pad_x/y`...) et de l'accroche (`hook_seconds`, `hook_font_size`,
`hook_margin_top`). Encodeur choisi par `clipper.gpu` (`h264_nvenc` si CUDA
détecté, sinon `libx264`). `title_enabled` (SPEC-76dc, défaut `true` —
comportement inchangé) : désactive le titre d'écran, sur tout layout.
`cta_enabled`/`cta_handle`/`cta_seconds`/`cta_text` (SPEC-6a47, désactivé par
défaut, voir *Appel à l'abonnement* ci-dessus) et leurs réglages de mise en
page (`cta_handle_font_size`, `cta_card_font_size`...). Badge de style
(SPEC-76dc, voir *Agencement stream split* ci-dessus) : `badge_enabled`
(défaut `false`), `badge_logo`, `badge_name`, `badge_logo_size` = 100,
`badge_glyph_scale` = 0.65, `badge_logo_fill` = `""` (échantillonné au coin
du logo si vide), `badge_font_size` = 40, `badge_background` =
`"black"` (`"none"` = pas de rectangle derrière le nom), `badge_name_outline`
= 3, `badge_name_outline_color` = `"black"`, `badge_name_shadow_enabled` =
`false`, `badge_name_shadow_color` = `"black"`, `badge_name_shadow_offset` =
`[2, 2]`.

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
"review"`, etc.) s'appliquent. `clipper init` écrit `config.toml` (à partir
de `config.example.toml`) et `rubric.toml` dans le dossier courant — refuse
d'écraser un fichier déjà présent sans `--force`.

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
