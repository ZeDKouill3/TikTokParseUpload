---
id: SPEC-bdd9e0db8905
type: spec
slug: veille-r-glages-veille-fichiers-state-veille-sou
title: "Veille : réglages [veille], fichiers state/veille/, sources Twitch/YouTube/Steam, montée vs 7 jours, candidats, choix de Claude, actions Clipper/Ignorer, meilleurs clips du jour archivés, routes et écran Veille"
created: 2026-10-06T11:32:12Z
author: w-veille
status: accepted
scope:
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/web/static/**
  - clipper/llm/__init__.py
references: [ADR-ca9a5792739c, ADR-35b778a98d22, SPEC-74e9fda61a5a, ADR-b1c17749b528, ADR-ad2e562b1810, ADR-09ad233678f2, SPEC-c1001cb7cbdb]
ratified: 8103b133f6fb
verified:
  - by: nicoc@zedk_ordi
    at: 2026-10-06T11:37:03Z
schema: 4
version: 3
---

## Objet
Règles de la veille des sujets chauds (ADR veille) : réglages, sources et
chiffres relevés, montée, candidats, choix de Claude, actions, sélection des
meilleurs clips du jour, écran et routes. Tout est fichier JSON sous
`state/veille/`, écrit atomiquement (tmp + replace, verrou `channel_mod.
file_lock`), sans valeur de secours silencieuse (ADR-ad2e). Dates et heures
« du jour » = Europe/Paris. Aucun nom réel dans le code, les tests et les
entités (`ma_chaine`, `streamer_a`). Maquette de référence :
`research/maquettes/veille.html` (local).

## R1. Réglages (`[veille]`, CONFIG_DEFAULTS de clipper/veille.py)
| clé | défaut | rôle |
|---|---|---|
| `enabled` | `false` | rien ne tourne tant que c'est faux ; l'écran le dit |
| `run_at` | `"07:00"` | heure locale du relevé quotidien (`HH:MM`) |
| `timezone` | `"Europe/Paris"` | fuseau du « jour » et de `run_at` |
| `language` | `"fr"` | Twitch : `language` des streams et des VOD |
| `region` | `"FR"` | YouTube : `regionCode` |
| `taste` | `""` | goûts de l'utilisateur, texte libre donné à Claude |
| `max_vods_per_day` | `3` | nombre max de VOD proposées (≥ 1) |
| `best_clips_per_day` | `3` | clips gardés par jour (≥ 1) |
| `baseline_days` | `7` | jours de référence pour la montée (≥ 1) |
| `history_days` | `90` | rétention des relevés (≥ `baseline_days`) |
| `rise_min_pct` | `50` | seuil « qui monte » (affichage, KPI), pas un filtre pour Claude |
| `vod_min_duration_s` | `1800` | VOD plus courte : pas candidate |
| `vod_max_age_h` | `36` | VOD publiée avant : pas candidate |
| `twitch_top_games` | `20` | jeux FR les plus regardés dont on liste les VOD |
| `twitch_vods_per_game` | `10` | VOD par jeu (`first`) |
| `youtube_max_results` | `50` | `maxResults` (1-50) |
| `youtube_min_duration_s` | `600` | vidéo plus courte : pas candidate |
| `steam_top` | `100` | jeux relevés |
| `twitch_client_id`, `twitch_client_secret`, `youtube_api_key` | `""` | clés (R8) |
| `state_dir` | `"state/veille"` | dossier d'état |
| `http_timeout_s` | `20` | délai par requête |
Valeur hors bornes ou `run_at` mal formé : `VeilleError` nommant la clé.

## R2. Fichiers
- `history/<YYYY-MM-DD>.json` : `{date, at, twitch: {<game_key>: {name, viewers_fr}},
  steam: {<appid>: {name, players}}, youtube: {<game_key>: {views_per_hour_sum}}}`.
  Un fichier par jour ; un relevé rejoué le même jour remplace le fichier.
  Les fichiers plus vieux que `history_days` sont supprimés au relevé.
- `days/<YYYY-MM-DD>.json` : `{date, started_at, finished_at | null,
  sources: {twitch | youtube | steam: {status: "ok" | "error", at, error | null,
  counts}}, games: [R4], candidates: [R5], excluded: {too_short, too_old,
  already_known}, llm: {status: "ok" | "error" | "skipped", error | null,
  model | null}, proposals: [R6], skipped_note: str, refresh_requested_at | null}`.
- `seen.json` : `{queued: [{candidate_id, video_id, url, date, channel,
  queue_entry_id, at}], ignored: [{candidate_id, video_id, date, at}]}`.
- `selection/<YYYY-MM-DD>.json` : `{date, computed_at, kept: [{video_id,
  clip_id, score, rank}], archived: [...], restored: [{video_id, clip_id,
  restored_at}]}`.
- `refresh.json` : `{requested_at}` ; `twitch_token.json` : `{access_token,
  expires_at}` (le secret n'y est jamais).
Un fichier illisible est une `VeilleError` nommant le fichier.

## R3. Sources (collecteurs ; transport HTTP injectable)
- **Twitch** : jeton d'app par `POST id.twitch.tv/oauth2/token`
  (`client_credentials`), mis en cache, renouvelé s'il expire ou sur 401.
  `GET helix/streams?language=<language>&first=100` paginé (5 pages max) →
  viewers FR par jeu (somme de `viewer_count` par `game_id`/`game_name`).
  `GET helix/games/top?first=<twitch_top_games>` pour les noms et images.
  Pour les `twitch_top_games` jeux FR les plus regardés : `GET helix/videos?
  game_id=&language=&period=day&sort=views&type=archive&first=
  <twitch_vods_per_game>` → VOD candidates (`duration` « 3h2m1s » → secondes).
- **YouTube** : `GET youtube/v3/videos?chart=mostPopular&regionCode=<region>
  &videoCategoryId=20&part=snippet,statistics,contentDetails&maxResults=
  <youtube_max_results>&key=` ; `views_per_hour = viewCount / max(1,
  heures depuis publishedAt)` ; durée ISO 8601 → secondes. Jamais `search.list`.
- **Steam** : `GET api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/`
  (top `steam_top`), noms via `ISteamApps/GetAppList/v2/` (relu au plus une
  fois par jour), `ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=`
  pour un jeu Twitch qui monte mais absent du top. Sans clé.
- Clé Twitch ou YouTube vide : la source est `error` avec le message
  « <clé> absente : à saisir dans Réglages › Veille », le collecteur n'est
  pas appelé. HTTP non 2xx, JSON illisible, champ attendu absent : `error`
  avec code, URL sans paramètres secrets et début de réponse. Aucun message,
  journal ni fichier d'état ne contient une clé ou un secret.

## R4. Jeux et montée
Un jeu = `{key, name, twitch_fr_viewers, twitch_avg, twitch_delta_pct,
steam_appid | null, steam_match, steam_players, steam_avg, steam_delta_pct,
youtube_views_per_hour, vod_count, baseline_days_available}`. `key` = nom
normalisé (minuscules, sans accents ni ponctuation, espaces réduits) ; la
correspondance Twitch ↔ Steam se fait sur cette clé ; sans correspondance :
`steam_match = false`, champs Steam `null` (affiché « hors Steam »).
`avg` = moyenne des `baseline_days` relevés précédents disponibles ;
`delta_pct = (aujourd'hui − avg) / avg × 100` arrondi à l'entier ; avec moins
de 2 relevés précédents : `delta_pct = null`, `baseline_days_available` le dit
(affiché « pas assez d'historique (n j) »). Un jeu « monte » si l'un des
deltas ≥ `rise_min_pct`.

## R5. Candidats
Un candidat = `{id: "<source>:<video_id>", source, video_id, url, title,
channel_name, game_key, game_name, duration_s, published_at, view_count,
views_per_hour, signals: {twitch_delta_pct, steam_delta_pct, ...}}`.
Exclus avec compte dans `excluded` : durée < `vod_min_duration_s`
(YouTube : `youtube_min_duration_s`), âge > `vod_max_age_h`, déjà connu
(`video_id` dans `workspace/<video_id>/`, dans `state/queue.json`, ou dans
`seen.json`). Un direct en cours n'est pas une VOD.

## R6. Choix de Claude
Un appel `llm.ask("veille", prompt, [], SCHEMA, check=...)` par relevé, texte
seul : goûts (`taste`, ou « aucune préférence déclarée »), `max_vods_per_day`,
la table des jeux (R4) et des candidats (R5) avec leurs chiffres, et la
consigne : choisir les VOD dont le gameplay se prête à des clips courts
compréhensibles seuls ET qui collent aux goûts, en privilégiant ce qui monte,
sans juger les personnes. Schéma : `{picks: [{candidate_id: str, reason: str
(1-240 car.)}] (0 à max_vods_per_day), skipped_note: str (0-300)}` ; `check` :
ids existants et uniques. Réponse refusée après réparation : `llm.status =
"error"`, `proposals = []`, l'erreur dans le fichier et le journal ; aucun
choix de remplacement. Proposition = `{candidate_id, rank, reason, status:
"proposed" | "queued" | "ignored", decided_at | null, channel | null,
queue_entry_id | null}`. Aucun candidat : `llm.status = "skipped"`, Claude
n'est pas appelé.

## R7. Exécution (worker) et actions
- `run_if_due(now)` à chaque tour du worker : `enabled` faux → rien ; sinon
  relevé si `days/<aujourd'hui>.json` n'existe pas et `now ≥ run_at`, ou si
  `refresh.json` existe (consommé avant de commencer). Un relevé rejoué le
  même jour garde les propositions déjà `queued`/`ignored` (par
  `candidate_id`) et remplace le reste. `started_at` posé avant les
  collecteurs, `finished_at` après Claude : l'écran montre « en cours ».
- `clip(date, candidate_id, channel | None, short_clips=None)` →
  `worker.enqueue(url, channel, "run", short_clips=...)`, proposition
  `queued`, entrée dans `seen.queued`. Déjà `queued`/`ignored` ou candidat
  inconnu : `VeilleError`. `ignore(date, candidate_id)` → `ignored` +
  `seen.ignored`. Une VOD de `seen` n'est plus jamais candidate.
- `select_best(now)` après chaque fin de processus enfant du worker : pour
  chaque `seen.queued` dont `pipeline.json` est `done`, le jour (Europe/Paris)
  de fin de la vidéo est son jour de sélection ; les clips de ce jour (sidecars
  `output/<video_id>/*.json`, `qa.status = passed`) sont classés par `score`
  décroissant puis `clip_id` ; les `best_clips_per_day` premiers (les parties
  d'une série comptent pour un, au score de la série) sont `kept`, les autres
  `archived`, sauf un clip dont l'entrée de publication est `approved`,
  `scheduled` ou `published` (toujours `kept`). Un clip `restored` reste
  visible. Aucun fichier de `output/` n'est modifié ni supprimé.
- `restore(video_id, clip_id)` : retiré de `archived`, ajouté à `restored`.

## R8. Clés
Saisies dans Réglages › Veille ; `GET /api/settings` ne renvoie jamais leur
valeur, seulement `twitch_client_id_set`, `twitch_client_secret_set`,
`youtube_api_key_set` (booléens) ; `PUT` les écrit quand elles sont
présentes dans le corps, les garde sinon ; `clipper.journal.mask_secrets`
les masque. Comment les obtenir est documenté dans docs/GUIDE.md (console
développeur Twitch : application, client id + secret ; Google Cloud : clé
API avec YouTube Data API v3 activée, quota par défaut 10 000 unités/jour).

## R9. Routes (clipper/web, aucune logique réseau ni LLM)
- `GET /api/veille` : état du jour (ou du dernier relevé), sélection du jour,
  `enabled`, clés présentes (booléens), `next_run_at`, `running` (started_at
  sans finished_at). `GET /api/veille/{date}` : un jour donné (404 sinon).
- `POST /api/veille/refresh` → 202, écrit `refresh.json` ; 409 si un relevé
  est en cours ou si `enabled` est faux (message : activer dans Réglages).
- `POST /api/veille/{date}/{candidate_id}/clip` `{channel | null,
  short_clips | null}` → 202 avec l'entrée de file ; 404 candidat inconnu ;
  409 déjà traité. `POST .../ignore` → 200.
- `POST /api/veille/clips/{video_id}/{clip_id}/restore` → 200.
- `GET /api/clips` masque les clips `archived` sauf `?archived=1` ; la vue
  d'un clip porte `veille: {date, status: "kept" | "archived" | "restored"}
  | null`.
- SSE (`/api/events`) : tout changement sous `state/veille/` émet
  `{kind: "veille", id: <nom de fichier>}`.

## R10. Écran « Veille » (SPEC-c100 T1-T8 s'appliquent)
Entrée « Veille » dans la navigation (Production, après Tableau de bord ;
onglet bas mobile à la place de Vidéos), compteur = propositions
`proposed`. Contenu, dans l'ordre de la maquette : bandeau des sources (heure,
comptes, erreur en rouge avec le message), KPI (jeux qui montent, VOD
proposées / max, meilleurs clips gardés / rendus, prochain relevé),
propositions du jour (rang, vignette, titre, chaîne, jeu, durée, publication,
vues, signaux chiffrés avec Δ 7 j, raison de Claude, « Voir la VOD », choix
du style, « Clipper », « Ignorer » ; une proposition `queued` reste affichée
le jour même avec « en file » et « Voir dans Vidéos », une `ignored`
disparaît), note des écartés (`skipped_note`), meilleurs clips du jour
(gardés avec score et actions Voir / Approuver, archivés repliés avec
« Restaurer »), tableau « ce qui monte » (Twitch FR, Steam, YouTube, VOD FR,
Δ 7 j ; `null` affiché avec sa raison), aperçu des réglages avec lien vers
Réglages › Veille. `enabled` faux : état vide « Veille désactivée » avec le
lien. Bouton « Rafraîchir » désactivé pendant `running`.
