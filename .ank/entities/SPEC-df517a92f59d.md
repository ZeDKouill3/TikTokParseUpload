---
id: SPEC-df517a92f59d
type: spec
slug: veille-calendrier-des-sorties-de-jeux-igdb-colle
title: "Veille : calendrier des sorties de jeux (IGDB) : collecte par /games sur la fenêtre J-15..J+14 triée par hypes, jeux en tendance gardés, étiquette « Portage », jaquettes, écran calendrier (bandeau récents, frise 14 jours, téléphone, panneau détail) ; Steam officiel à la place de SteamDB (joueurs simultanés et pic du jour, joueurs par appid hors top 100, abonnés, gain 7 j et tendance depuis l'historique), filtre de communauté (Steam joueurs ou abonnés, Twitch FR ou hypes), au plus N VOD par jeu (succède à SPEC-4efa)"
created: 2026-10-07T08:20:49Z
author: w-calplan
status: accepted
scope:
  - clipper/veille.py
  - clipper/veille_sources.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_veille*.py
  - tests/test_web_veille.py
  - docs/GUIDE.md
  - CHANGELOG.md
references: [ADR-0944f6d2110d, ADR-798cf21fddd6, SPEC-bdd9e0db8905, ADR-ca9a5792739c, ADR-ad2e562b1810, ADR-b1c17749b528, ADR-09ad233678f2, SPEC-c1001cb7cbdb, ADR-05a42b76906f]
supersedes: SPEC-4efa50cc6b8c
ratified: a8573e43317e
verified:
  - by: nicoc@zedk_ordi
    at: 2026-10-07T08:40:38Z
schema: 4
version: 7
---

## Objet
Remplace SPEC-4efa (dont elle reprend R11 à R17, numérotation gardée ; SPEC-bdd9
R1 à R10 reste entière). Motif mesuré le 07/10/2026 sur IGDB réel et sur
`state/veille/days/2026-10-07.json` : la fenêtre J−15..J+14 compte 2 333 lignes
`release_dates`, le plafond 4 × 500 en perd 333 (les derniers jours manquent) ;
les listes sont triées par date puis coupées à 30, donc « Sorties récentes »
= 30 jeux du jour même sans hype (1 044 écartés) et AION 2 (17 hypes, n°1 des
ventes Steam FR) est absent. Correction : interroger `games` (ADR-0944) sur la
fenêtre entière, trier par hypes, garder un jeu présent dans le relevé du jour
même avec peu de hypes, étiqueter « Portage », et afficher le calendrier validé
par l'utilisateur (`research/maquettes/calendrier-sorties.html`, captures
`calendrier-pc.png`, `calendrier-mobile.png`, `calendrier-detail-pc.png`,
`calendrier-detail-mobile.png`). Aucune valeur de secours silencieuse
(ADR-ad2e) ; aucun calcul dans `clipper/web` (ADR-09ad) ; tests sans réseau.
« Aujourd'hui » = date Europe/Paris (`[veille] timezone`).

Second motif (07/10/2026) : avec les sorties IGDB, Claude a proposé 3 VOD du
même jeu (STAR WARS: Galactic Racer, J+1). L'utilisateur : « des nouveaux
jeux y en a plein, mais faut qu'il y ait du monde » (il cite les courbes de
joueurs de SteamDB). SteamDB est interdit (ADR-ca9a : jamais de scraping),
mais le même chiffre vient de l'API Steam officielle :
`ISteamUserStats/GetNumberOfCurrentPlayers/v1` (doc
https://partner.steamgames.com/doc/webapi/ISteamUserStats lue le 07/10/2026 :
GET, paramètre `appid` (uint32, obligatoire), aucune clé, « Gets the total
number of players currently active in the specified app on Steam », ne compte
pas les joueurs hors ligne ; réponse `{"response": {"player_count": n,
"result": 1}}`, vérifiée sur https://api.steampowered.com (Dota 2 : 559 193),
appid inconnu → HTTP 404). Vérifié aussi le 07/10/2026 vers 10 h 45 Paris
(ADR-05a4) : `ISteamChartsService/GetGamesByConcurrentPlayers/v1` rend
`concurrent_in_game` **et** `peak_in_game` (CS2 707 830 / 1 144 557,
identiques à SteamDB ; `peak_in_game` y est le même chiffre que dans
`GetMostPlayedGames`, pic du jour ; 18 appids du top 100 « most played »
manquent au classement par simultanés) ; les abonnés d'un jeu
(« followers » SteamDB) = `<memberCount>` de la page XML publique
`https://steamcommunity.com/games/<appid>/memberslistxml/?xml=1` (AION 2 =
124 547, SteamDB 122 747 ; Galactic Racer = 38 763 ; appid sans groupe →
HTTP 200 avec une page HTML sans la balise). SteamDB lui-même : 403
Cloudflare et FAQ anti-scraping, interdit (ADR-ca9a). D'où R18 (joueurs
Steam, pic et instantané), R21 (abonnés Steam, gain sur 7 jours, tendance
joueurs depuis l'historique), R19 (filtre de communauté) et R20
(diversité : au plus N VOD par jeu). Ces lectures Steam sont admises par
ADR-05a4 (amende ADR-ca9a) ; l'appid Steam d'un jeu IGDB vient de
`external_games` (ADR-0944).

Doc IGDB lue le 07/10/2026 : `#game` (`hypes`, `first_release_date`, `cover`,
`release_dates`), `#release-date`, `#images` (`t_cover_big`), `#filters`
(filtre sur un champ imbriqué, ex. `where release_dates.date >= …`),
`#pagination`, `#rate-limits`. Vérifié par requête réelle : `games` avec
`where release_dates.date >= S & release_dates.date < E & hypes >= 1; sort
hypes desc;` rend 336 jeux sur la fenêtre du 07/10/2026 (une page).

## R11. Réglages (`[veille]`, CONFIG_DEFAULTS de clipper/veille.py)
| clé | défaut | rôle |
|---|---|---|
| `upcoming_days` | `14` | horizon des sorties à venir, en jours (≥ 1) |
| `release_window_days` | `15` | un jeu sorti il y a 0 à N jours est « en fenêtre de sortie » (≥ 0) |
| `igdb_min_hypes` | `5` | une sortie dont `hypes` < seuil est écartée, sauf jeu présent dans le relevé du jour (R13) (≥ 1) |
| `igdb_recent_max` | `12` | sorties récentes gardées après tri (≥ 1) |
| `igdb_upcoming_max` | `20` | sorties à venir gardées après tri (≥ 1) |
| `igdb_pages_max` | `4` | pages de 500 jeux au plus par relevé (≥ 1) |
| `steam_players_lookups_max` | `30` | appels `GetNumberOfCurrentPlayers` au plus par relevé, pour les jeux hors top 100 (R18) (≥ 0 ; 0 = aucun) |
| `community_min_steam_players` | `1000` | joueurs Steam simultanés à partir desquels un jeu a une communauté (R19) (≥ 0) |
| `community_min_twitch_viewers` | `200` | spectateurs Twitch FR à partir desquels un jeu a une communauté (R19) (≥ 0) |
| `community_min_hypes` | `50` | hypes IGDB à partir desquelles un jeu a une communauté (R19) (≥ 0) |
| `community_min_steam_followers` | `10000` | abonnés Steam (R21) à partir desquels un jeu a une communauté (R19) (≥ 0) |
| `steam_followers_lookups_max` | `200` | pages `memberslistxml` lues au plus par relevé (R21) (≥ 0 ; 0 = aucune) |
| `steam_followers_pause_s` | `1.0` | pause entre deux lectures `memberslistxml`, en secondes (R21) (≥ 0.2) |
| `max_vods_per_game` | `1` | VOD proposées au plus par jeu dans un relevé (R20) (≥ 1) |
`igdb_releases_max` (SPEC-4efa) est retirée : déclarée dans `LEGACY_KEYS` de
`clipper/veille.py` (tolérée et ignorée dans un `config.toml` existant, cf.
`clipper/config.py`). Aucune clé nouvelle de secret : IGDB utilise
`twitch_client_id` / `twitch_client_secret` (R8). Valeur hors bornes :
`VeilleError` nommant la clé (R1).

## R12. Collecteur `igdb` (clipper/veille_sources.py, transport injectable)
- Source `igdb` dans `SOURCES`, clés exigées celles de `twitch` (clé vide →
  `error` « twitch_client_id absente : à saisir dans Réglages › Veille »,
  collecteur non appelé). Jeton, en-têtes, renouvellement sur 401, espacement
  de 250 ms (horloge injectée), 429 → `SourceError` « IGDB : limite de 4
  requêtes/s dépassée (HTTP 429) » sans réessai : comme SPEC-4efa R12.
- Une requête `POST https://api.igdb.com/v4/games`, corps Apicalypse :
  `fields name,slug,url,hypes,first_release_date,cover.image_id,
  external_games.uid,external_games.external_game_source,
  release_dates.date,release_dates.human,release_dates.platform.name,
  release_dates.release_region.region,release_dates.status.name,
  release_dates.date_format.format; where release_dates.date >= <début> &
  release_dates.date < <fin> & hypes >= 1; sort hypes desc; limit 500;
  offset <k×500>;` avec `début` = minuit UTC de (aujourd'hui −
  `release_window_days`) et `fin` = minuit UTC de (aujourd'hui +
  `upcoming_days` + 1), en secondes Unix. Toutes plateformes et régions,
  aucun filtre dessus. `hypes >= 1` côté serveur : un jeu sans aucune hype
  n'a aucun signal d'intérêt IGDB et n'est jamais relevé (il n'est pas
  cherché par nom non plus : ADR-798c).
- Pagination : page suivante tant que la page rend 500 jeux et que
  `igdb_pages_max` n'est pas atteint ; requêtes l'une après l'autre.
- Retour : `{"games": [{igdb_id, name, slug, url, hypes (entier ≥ 1),
  first_release_date | null, cover_image_id | null, steam_appid | null
  (l'`uid` de la première `external_games` dont `external_game_source` = 1,
  Steam ; vérifié le 07/10/2026 : AION 2 → 3393110, url
  store.steampowered.com/app/3393110 ; `category` est déprécié, jamais lu),
  release_dates:
  [{date (« YYYY-MM-DD », jour UTC du timestamp), ts (secondes), human |
  null, platform | null, region | null, status | null, date_format |
  null}]}], "skipped_rows": n}`, une entrée par jeu rendu, **toutes** ses
  `release_dates` (dans la fenêtre ou non : elles servent à l'étiquette
  « Portage », R13), une ligne `release_dates` sans `date` ignorée. Jeu sans
  `name`, sans `hypes` entier ou sans aucune `release_dates` datée : ignoré
  et compté dans `skipped_rows`. Jeu sans `id` : `SourceError`. `cover`
  absent ou sans `image_id` → `cover_image_id = null` (jamais une chaîne
  inventée).
- Erreur HTTP, JSON illisible, champ attendu absent : `SourceError` avec
  code, URL et début de réponse, sans jeton (R3).

## R13. Sorties du jour (clipper/veille.py, `days/<date>.json`)
`collect` traite chaque jeu rendu, après avoir construit `games` (R4) :
- `in_window` = ses `release_dates` dont `ts` ∈ [début, fin) ; `before` =
  celles dont `ts` < début. `in_window` vide (ne peut arriver que par
  incohérence IGDB) : jeu ignoré, compté dans `sources.igdb.counts.skipped_rows`.
- `date` = la plus ancienne de `in_window` ; `days` = `date` − aujourd'hui en
  jours (≤ 0 = déjà sorti) ; `platforms` / `regions` / `statuses` = valeurs
  uniques triées de `in_window` ; `human` = celui de la ligne de `date`.
- **`portage`** = `before` non vide **et** au moins une plateforme de
  `in_window` absente des plateformes de `before` (sortie d'un jeu déjà sorti
  avant sur d'autres plateformes : Witcher 3, Resident Evil 2/4 sur Switch 2
  → `true` ; AION 2, déjà sorti sur PC en Asie et sorti sur PC en Occident
  dans la fenêtre → `false`). Lignes sans plateforme ignorées dans ce calcul.
- **`trend`** = le jeu de `games` apparié (par `igdb_id` fourni par Twitch,
  sinon par `key` normalisée, comme R14), sous la forme `{key, name,
  twitch_fr_viewers, twitch_delta_pct, steam_players, steam_rank,
  steam_rank_gain, steam_new_in_top, steam_sellers_rank, steam_sellers_gain,
  steam_sellers_new}` copiés du jeu ; sinon `null`. « En tendance dans le
  relevé du jour » = `trend` non nul.
- Exclusion : `hypes` < `igdb_min_hypes` **et** `trend` nul → écarté, compté
  dans `releases.excluded_low_hypes`. Un jeu en tendance est gardé quel que
  soit `hypes` (AION 2 : 17 hypes).
- Entrée : `{igdb_id, name, key (normalize(name)), slug, url, hypes,
  cover_image_id, steam_appid, first_release_date, date, human, days,
  platforms, regions, statuses, portage, trend}`. `trend` porte en plus
  `steam_players_now` et `community` (R18, R19) copiés du jeu.
- `releases.recent` : `days` ∈ [−`release_window_days`, 0], tri `hypes`
  décroissant puis `days` décroissant (le plus récent d'abord) puis `name` ;
  coupée à `igdb_recent_max`.
- `releases.upcoming` : `days` ∈ [1, `upcoming_days`], tri `hypes`
  décroissant puis `date` croissante puis `name` ; coupée à
  `igdb_upcoming_max`. Le regroupement par jour est fait par l'écran
  (affichage, R17), jamais ici.
- `releases.truncated` = `{recent: n, upcoming: n}` (écartés par la coupe).
- `sources.igdb` = `{status, at, error, counts: {rows (jeux rendus),
  recent, upcoming, skipped_rows}}`. Source en erreur : `releases = {recent:
  [], upcoming: [], excluded_low_hypes: 0, truncated: {recent: 0, upcoming:
  0}}`, aucun repère J+N (R14), erreur visible dans `sources.igdb.error`.
  `history/<date>.json` ne change pas.

## R14. Repère J+N sur les jeux (R4) et les VOD candidates (R5) — inchangé
Comme SPEC-4efa R14 : chaque jeu de `games` porte `release: {igdb_id, name,
date, days_since, hypes} | null`, apparié par `igdb_id` Twitch puis par `key`,
sur une sortie `recent` seulement ; chaque candidat porte
`signals.release_days_since` copié de son jeu. Pas un filtre.

## R15. Choix de Claude (R6) — complété
Comme SPEC-4efa R15 (`sortie_j_plus=`, `hypes_igdb=`, bloc « Sorties de jeux
(IGDB) », consigne de priorité à la fenêtre de sortie), plus :
- chaque ligne du bloc « Sorties » ajoute `portage=oui` quand `portage` est
  vrai (rien sinon) : Claude sait qu'un portage n'est pas une nouveauté ;
- chaque ligne de jeu ajoute `steam_players_now=<n | inconnu>` (l'en-tête
  du bloc précise : `steam_players` = pic du jour du top 100,
  `steam_players_now` = instantané à l'heure du relevé) et
  `steam_now_delta_pct=<n | historique insuffisant>`,
  `steam_abonnes=<n | inconnu>`, `steam_abonnes_gain_7j=<n | historique
  insuffisant>` (R21) et `communaute=<ok | insuffisante>` (R19) ; seuls les
  candidats dont le jeu a une communauté sont listés (R19), donc chaque
  ligne de candidat porte `steam_players=<n (pic) | n (instantané) |
  inconnu>`, `steam_abonnes=`, `twitch_fr_viewers=` et `hypes_igdb=` de
  son jeu ;
- la consigne ajoute : « Au plus `max_vods_per_game` VOD par jeu : varie les
  jeux. » (R20).
Nombre d'appels et comportement en erreur inchangés (R6) ; `check` complété
par R20. Aucun choix fait par le code à la place de Claude.

## R16. Tests (aucun réseau par défaut)
- Collecteur `igdb` injecté et transport injecté : corps de requête (`games`,
  `fields` avec `cover.image_id` et `release_dates.date`, `where` avec les
  deux bornes en secondes Unix et `hypes >= 1`, `sort hypes desc`),
  pagination plafonnée, espacement, 429, `cover_image_id` null si absent,
  `skipped_rows` (sans `name`, sans `hypes`, sans date), `id` absent →
  `SourceError`, secrets absents des messages.
- `collect` : bornes de fenêtre (J−15 inclus, J0, J+1, J+14 inclus, J+15 et
  J−16 exclus), `date` = plus ancienne dans la fenêtre (une date hors fenêtre
  antérieure ne compte pas), `portage` vrai (Switch 2 après PS4) et faux
  (même plateforme, autre région ; aucune date antérieure), `trend` par
  `igdb_id` puis par `key` et `null` sinon, exclusion sous `igdb_min_hypes`
  sauf en tendance, tris par hypes, coupes et `truncated`, `LEGACY_KEYS`
  tolère `igdb_releases_max`, réglages hors bornes → `VeilleError` nommant
  la clé, repère R14, prompt R15 (`portage=oui`), source en erreur (tout à
  vide, erreur visible, autres sources intactes).
- R18 : collecteur `steam_players` injecté et transport injecté : ordre des
  appids, plafond `steam_players_lookups_max` (0 = aucun appel), 404 →
  `null` sans erreur de source, autre erreur HTTP → `SourceError` et source
  en erreur pendant que les autres continuent, `steam_players_now` posé sur
  le bon jeu et jamais sur un jeu du top 100 ; `history/<date>.json` porte
  `steam_now` ; `steam_players_history` rend les points `peak` et `now` des
  jours précédents (fichiers d'historique fabriqués sous `tmp_path`), sans
  jour interpolé ; `steam_avg` / `steam_delta_pct` ignorent `steam_now`.
- R18 top 100 : `concurrent` posé depuis le second classement, `null` pour
  un appid absent de celui-ci (puis relevé par appid), `players` inchangé ;
  second appel en erreur → source `steam` en erreur.
- R21 : collecteur `steam_followers` injecté : ordre des appids, plafond,
  pause (attente injectée), `<memberCount>` lu, page HTML sans balise →
  `null` compté dans `unknown`, erreur HTTP → `SourceError` et source en
  erreur pendant que les autres continuent, rien d'autre lu ;
  `steam_followers` sur les jeux et les `trend` ; `history/<date>.json`
  porte `steam_followers` ; `steam_followers_gain_7d` juste avec un fichier
  J−7 fabriqué et `null` sans lui (ou avec J−6 seulement) ;
  `steam_now_avg` / `steam_now_delta_pct` sur `steam_now` seulement ;
  seuil `community_min_steam_followers` seul suffit à `community.ok`.
- R19 : `community.ok` vrai par chaque seuil séparément (Steam seul,
  abonnés seuls, Twitch seul, hypes seuls), faux quand aucun n'est atteint et quand tout est
  inconnu, seuil à 0 atteint par toute valeur connue mais pas par `null` ;
  candidat d'un jeu sans communauté ou sans jeu → `excluded.no_community`
  et absent du prompt ; chiffres dans le prompt.
- R20 : `check` refuse deux `picks` d'un même `game_key` avec
  `max_vods_per_game` = 1 et les accepte avec 2 ; consigne dans le prompt ;
  réponse refusée après réparation → `llm.status = "error"`, aucun choix de
  remplacement.
- Un test réel optionnel derrière `CLIPPER_REAL_NETWORK=1` : une requête
  `games` sur la fenêtre du jour, au moins un jeu avec `cover_image_id` et
  une `release_dates` dans la fenêtre ; un second, même garde : un
  `GetNumberOfCurrentPlayers` sur l'appid 570 rend un entier > 0.

## R17. Routes et écran (R9, R10 complétés ; SPEC-c100 s'applique)
- `GET /api/veille` et `GET /api/veille/{date}` rendent `releases` et
  `sources.igdb` tels qu'écrits (aucun calcul) ; `settings` expose
  `upcoming_days`, `release_window_days`, `igdb_min_hypes`,
  `igdb_recent_max`, `igdb_upcoming_max`, `steam_players_lookups_max`,
  `steam_followers_lookups_max`, `steam_followers_pause_s`,
  `community_min_steam_players`, `community_min_steam_followers`,
  `community_min_twitch_viewers`, `community_min_hypes`,
  `max_vods_per_game` ; `PUT /api/settings` les écrit et refuse une valeur
  hors bornes (400, message de `VeilleError`). Aucune route nouvelle,
  aucune route d'image.
- Section « Sorties de jeux » de l'écran Veille (même place : entre les
  propositions et les meilleurs clips), conforme à la maquette :
  - en-tête « Calendrier du <date longue en français> », puces « N
    récentes », « N à venir », « Source : IGDB » ;
  - **bandeau « Sorties récentes »** (sous-titre « N derniers jours, les plus
    attendues d'abord », N = `release_window_days`) : cartes jaquette à
    défilement horizontal dans l'ordre de `recent` ; carte = jaquette
    (`<img src="https://images.igdb.com/igdb/image/upload/t_cover_big/<cover_image_id>.jpg"
    alt="Jaquette de <nom>" loading="lazy">`, erreur de chargement ou
    `cover_image_id` nul → vignette portant le nom), pastille
    « Aujourd'hui » (days = 0) ou « Sortie J+N », pastille « Tendance » si
    `trend`, nom, 3 plateformes au plus puis « +n », puce « Portage » si
    `portage`, « N hypes », ligne tendance composée des champs non nuls de
    `trend` dans cet ordre : « n°R des ventes Steam FR » ou « +G places ventes
    Steam FR » ou « nouveau dans le top ventes Steam FR », « V viewers Twitch
    FR », « P joueurs Steam (pic du jour, top R) » si `steam_players` est
    connu, sinon « P joueurs Steam (à l'instant du relevé) » si
    `steam_players_now` l'est, « A abonnés Steam » si `steam_followers`
    est connu, suivi de « (+G en 7 j) » si `steam_followers_gain_7d` l'est ;
    séparateur « · » ; puce « Communauté » (verte) si
    `trend.community.ok`, « Peu de monde » (grise) si `trend` existe sans
    communauté ;
  - **frise « À venir (N j) »** (sous-titre « une colonne par jour, la plus
    attendue en grand ») : une colonne par jour d'aujourd'hui à J+N ; colonne
    d'aujourd'hui marquée (accent, « Aujourd'hui ») et remplie des `recent` à
    `days = 0`, les autres des `upcoming` du jour ; en-tête jour de la
    semaine, date, « J−N » ; jaquettes dans l'ordre du tableau (déjà trié par
    hypes), la première en grand avec ses hypes, 5 au plus puis « +n
    autres » ; jour sans sortie : « Aucune sortie notable » ; légende
    (aujourd'hui, tendance) ;
  - **téléphone** (largeur ≤ 760 px) : la frise est remplacée par une liste
    par jour, seuls les jours avec sortie, « N jours sans sortie notable »
    entre deux, lignes jaquette + nom + plateformes + puce « Tendance » +
    hypes, la première ligne du jour en grand ;
  - **panneau détail** au clic ou à l'entrée clavier sur une jaquette
    (`role="dialog"`, `aria-modal`, fermeture par bouton, Échap ou clic hors
    du panneau, focus rendu) : jaquette, nom, date longue + puce
    (« Aujourd'hui » / « Sortie J+N » / « J−N »), toutes les plateformes,
    hypes, ligne tendance si `trend`, « Portage sur nouvelle plateforme » si
    `portage`, action « Voir sur IGDB » (lien `url`, nouvel onglet) ;
    **aucun bouton « Chercher des VOD »** : l'application n'a pas de recherche
    de VOD par jeu (vérifié le 07/10/2026 : aucune route ni écran) et un
    bouton inerte est interdit (SPEC-c100) ; la SPEC qui ajoutera une telle
    recherche ajoutera le bouton ;
  - `truncated` > 0 : « +n autres » sous le bandeau ou sous la frise ;
    `excluded_low_hypes` > 0 : « n sorties écartées (moins de N hypes) » ;
    `recent` et `upcoming` vides : « Aucune sortie dans la fenêtre » ;
    `sources.igdb` en erreur : le message de `sources.igdb.error` en rouge,
    pas de calendrier. Bandeau des sources : `igdb` « IGDB (sorties) ».
  - Aucun tri ni filtre sur `hypes` dans l'écran : seulement le groupement
    par jour (`date`) et la coupe d'affichage à 5 par colonne.
- Badges « Sortie J+N » sur les propositions (`signals.release_days_since`)
  et sur « Ce qui monte » (`release`) : inchangés. « Ce qui monte » gagne
  une colonne « Communauté » : « ok » (vert) avec les critères atteints
  (`community.met`, ex. « Twitch FR, Steam ») ou « insuffisante » (gris),
  et la colonne « Steam (joueurs) » montre le pic du jour, ou
  `steam_players_now` avec le suffixe « à l'instant » quand le pic est
  inconnu ; l'en-tête de colonne dit « Steam (pic du jour / à l'instant) ».
  Une mini-courbe (SVG en ligne, sans bibliothèque) par jeu dessine
  `steam_players_history` (un point par jour, `peak` et `now` de couleurs
  distinctes, légende), dans « Ce qui monte » et dans le panneau détail
  d'une sortie en tendance ; moins de 2 points : pas de courbe, « 1 jour de
  mesure ». Colonne « Abonnés Steam » : `steam_followers` (ou « inconnu »)
  et « +G (7 j) » ou « historique insuffisant » (R21) ; la colonne « Δ 7 j »
  Steam montre `steam_delta_pct` (pics) ou, à défaut, `steam_now_delta_pct`
  suffixé « (à l'instant) ». Le bandeau des sources porte `steam_players`
  libellé « Steam (joueurs hors top) » et `steam_followers` libellé « Steam
  (abonnés) ». Les KPI du jour affichent `excluded.no_community` :
  « n VOD écartées : communauté insuffisante ou jeu inconnu ».
- Réglages › Veille : `upcoming_days`, `release_window_days`,
  `igdb_min_hypes`, `igdb_recent_max`, `igdb_upcoming_max`,
  `steam_players_lookups_max`, `steam_followers_lookups_max`,
  `steam_followers_pause_s`, `community_min_steam_players`,
  `community_min_steam_followers`, `community_min_twitch_viewers`,
  `community_min_hypes`, `max_vods_per_game` éditables ; l'aperçu des
  réglages de l'écran Veille les montre.
- docs/GUIDE.md : le calendrier (bandeau, frise, téléphone, détail), les
  jaquettes chargées depuis images.igdb.com par le navigateur, le filtre de
  communauté (les quatre seuils, « ou » entre eux, d'où vient chaque
  chiffre : pic du jour, instantané, abonnés, hypes), la courbe et le gain
  d'abonnés construits depuis l'historique de la veille (absents les
  premiers jours), la diversité (`max_vods_per_game`), les treize réglages,
  `igdb_releases_max` ignorée. CHANGELOG mis à jour.

## R18. Joueurs Steam : pic du jour et instantané, top 100 et jeux en tendance hors top 100
- **Top 100 (source `steam`, SPEC-bdd9 R3 complétée).** Le collecteur
  `steam` lit `GetMostPlayedGames` (rangs, `last_week_rank`,
  `peak_in_game`, comme avant) **puis** `GetGamesByConcurrentPlayers/v1`
  (ADR-05a4) et, pour chaque appid du top « most played » présent dans le
  classement par simultanés, ajoute `concurrent` = `concurrent_in_game`
  (sinon `null`) ; `players` reste `peak_in_game` (même chiffre dans les
  deux classements, vérifié le 07/10/2026). Retour `games[]` =
  `{appid, name, players, concurrent | null, rank, last_week_rank}`. Le
  second appel en erreur → `SourceError` (source `steam` en erreur comme
  pour le premier).
- **Hors top 100 (source `steam_players`).** Ajoutée à `SOURCES` (aucune
  clé exigée ; ADR-05a4), collecteur injectable appelé **après** les autres
  sources avec `(settings, appids)` : la liste ordonnée des appids à
  relever, construite par `collect` = appids des jeux de `games` dont
  l'instantané est inconnu (jeux du top 100 absents du classement par
  simultanés, puis jeux « ventes FR » hors top 100, dans l'ordre de
  `games`), puis `steam_appid` des sorties `recent` (R13, dans l'ordre de
  `recent`) absents de `games` ; sans doublon ; coupée à
  `steam_players_lookups_max` (les appids au-delà sont comptés dans
  `counts.skipped`).
- Un appel par appid : `GET
  https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/`
  avec `appid=<appid>` ; appels séquentiels. Réponse
  `response.player_count` (entier) → `players[appid]` ; HTTP 404 →
  `players[appid] = null` (appid inconnu de Steam : pas une erreur de
  source) ; autre erreur HTTP ou JSON illisible → `SourceError` (source en
  erreur, aucun `steam_players_now` posé, les autres sources et le choix
  continuent). Retour : `{"players": {appid: int | null}, "skipped": n}`.
- **Deux mesures, jamais mélangées, toujours nommées.** `steam_players` =
  **pic du jour** (`peak_in_game`, top 100 seulement ; à privilégier pour
  comparer un jour à l'autre : AION 2 = 383 176 le 07/10), `null` hors top
  100. `steam_players_now` = **instantané** à l'heure du relevé quotidien
  (`run_at`) : `concurrent` du top 100 (AION 2 = 13 345 à 10 h 30 Paris le
  07/10) ou `player_count` relevé par appid (Galactic Racer = 5 283) ;
  `null` si ni l'un ni l'autre. `collect` pose `steam_players_now` sur
  chaque jeu de `games` et sur l'entrée `trend` des sorties ; une sortie
  `recent` avec `steam_appid` relevé mais sans jeu dans `games` ne crée pas
  de jeu : le chiffre vit dans `releases.recent[].steam_players_now`.
- **Historique quotidien (courbe type SteamDB).** `history/<date>.json`
  (R2 de SPEC-bdd9) gagne `steam_now: {appid: joueurs}` pour tous les
  instantanés du jour (top 100 et hors top) et `steam_followers: {appid:
  abonnés}` (R21) ; le pic du top 100 y est déjà sous `steam`. Chaque jeu
  de `games` porte `steam_players_history: [{date, kind: "peak" | "now",
  players}]`, un point par mesure et par jour sur les `baseline_days`
  derniers jours plus aujourd'hui, pris dans l'historique (`steam` →
  `peak`, `steam_now` → `now`), jours sans mesure absents, jamais
  interpolés. `steam_avg` / `steam_delta_pct` (R4) restent calculés sur les
  pics ; `steam_now_avg` / `steam_now_delta_pct` (R21) sur les instantanés
  des jours précédents (même heure de relevé) ; jamais un pic contre un
  instantané.
- `sources.steam_players` = `{status, at, error, counts: {requested,
  found, unknown, skipped}}` ; `steam_players_lookups_max` = 0 → source
  `skipped` (pas d'appel, pas d'erreur).

## R19. Communauté : un jeu « en tendance » n'est utilisable que s'il y a du monde
- Chaque jeu de `games` porte `community = {ok: bool, steam_players:
  int | null, steam_kind: "peak" | "now" | null (le chiffre Steam
  disponible : le pic du jour s'il est connu, sinon l'instantané, et son
  nom), steam_followers: int | null (R21), twitch_fr_viewers: int | null,
  hypes: int | null (= release.hypes, R14), met: [« steam » | « followers »
  | « twitch » | « hypes »]}`. `ok` = au moins un seuil atteint :
  `steam_players` ≥ `community_min_steam_players` **ou** `steam_followers`
  ≥ `community_min_steam_followers` **ou** `twitch_fr_viewers` ≥
  `community_min_twitch_viewers` **ou** `hypes` ≥ `community_min_hypes`.
  Une valeur `null` n'atteint aucun seuil, même à 0 ; tout inconnu → `ok`
  faux (ADR-ad2e : rien n'est présumé).
- Candidats (R5 de SPEC-bdd9, complété) : un candidat dont le jeu
  (`game_key`) a `community.ok` faux, ou qui n'a pas de jeu connu, est écarté
  et compté dans `excluded.no_community` ; il n'apparaît pas dans le prompt.
  Les jeux eux-mêmes restent tous dans `games` (R4) et dans « Ce qui
  monte », marqués par `community`.
- Les chiffres de `community` sont donnés à Claude (R15) et affichés (R17).
- Défauts (07/10/2026) : 1 000 joueurs Steam, 200 spectateurs Twitch FR, 50
  hypes ; relevé du jour : Galactic Racer 3 314 viewers FR → ok ; AION 2
  1 523 viewers FR → ok ; un jeu du jour sans hype et absent de Twitch/Steam
  → insuffisante.

## R20. Diversité : au plus `max_vods_per_game` VOD par jeu
- Consigne dans le prompt (R15) et `check` de `llm.ask` complété : une
  réponse dont plus de `max_vods_per_game` `picks` partagent le même
  `game_key` non nul est refusée (`SchemaError` nommant le jeu), comme un
  `candidate_id` inconnu ; après réparation refusée : `llm.status =
  "error"`, `proposals = []`, aucun choix de remplacement (R6).
- `max_vods_per_day` reste le plafond global ; avec `max_vods_per_game` = 1
  et 3 VOD par jour, les propositions couvrent 3 jeux différents ou moins.

## R21. Abonnés Steam et dérivés depuis l'historique (gain sur 7 jours, tendance joueurs)
- **Source `steam_followers`** (ajoutée à `SOURCES`, aucune clé ;
  ADR-05a4), collecteur injectable appelé après les autres sources avec
  `(settings, appids)`. Jeux suivis = appids, sans doublon, dans cet ordre :
  jeux de `games` (ordre de `games` : top Twitch avec appid, jeux qui
  montent, ventes FR), puis `steam_appid` des sorties `recent` puis
  `upcoming` absents de `games`, puis le reste du top 100 joueurs ; coupée
  à `steam_followers_lookups_max` (au-delà : `counts.skipped`).
- Un appel par appid : `GET
  https://steamcommunity.com/games/<appid>/memberslistxml/?xml=1`,
  en-tête `User-Agent` nommant Clipper, séquentiel, pause
  `steam_followers_pause_s` entre deux appels (horloge et attente
  injectées) ; `<memberCount>n</memberCount>` → `followers[appid] = n` ;
  réponse 200 sans la balise (page HTML : appid sans groupe) →
  `followers[appid] = null`, compté dans `counts.unknown`, pas une erreur ;
  erreur HTTP ou corps vide → `SourceError` (source en erreur, aucun
  abonné posé, les autres sources et le choix continuent). Rien d'autre
  n'est lu dans la page (pas de membres, pas de HTML). Retour :
  `{"followers": {appid: int | null}, "skipped": n}` ;
  `sources.steam_followers` = `{status, at, error, counts: {requested,
  found, unknown, skipped}}` ; plafond 0 → source `skipped`.
- `collect` pose `steam_followers` (entier ou `null`) sur chaque jeu de
  `games` et sur `trend` des sorties, et `releases.*[].steam_followers`
  pour une sortie sans jeu ; `history/<date>.json` garde
  `steam_followers: {appid: n}` (R18).
- **Dérivés, jamais estimés** (ADR-ad2e) :
  - `steam_followers_gain_7d` = `steam_followers` − abonnés du fichier
    d'historique daté d'il y a exactement `baseline_days` jours (7 par
    défaut) ; `null` si ce fichier ou cet appid y manque, ou si l'un des
    deux chiffres est `null` ; `steam_followers_history: [{date,
    followers}]` sur `baseline_days` + 1 jours, jours absents non
    interpolés ;
  - `steam_now_avg` / `steam_now_delta_pct` = comme `steam_avg` /
    `steam_delta_pct` (R4) mais sur `steam_now` des jours précédents, pour
    `steam_players_now` ; `null` sans jour précédent ;
  - l'écran et le prompt disent « historique insuffisant » quand un dérivé
    est `null` faute de jours, jamais un chiffre.

## Hors périmètre (non retenu)
- SteamDB (403 Cloudflare, FAQ anti-scraping ; ADR-ca9a) : jamais, ni par
  cache ni par capture ; tout vient des points Steam nommés par ADR-05a4.
- Comparer un pic à un instantané : jamais ; chaque mesure se compare à
  elle-même (R4 sur les pics, R21 sur les instantanés et les abonnés).
- Autre lecture de steamcommunity.com (membres, avis, hub, HTML) : hors
  ADR-05a4.
- Recherche de VOD par jeu depuis le calendrier : pas de recherche de VOD
  dans l'application aujourd'hui ; une SPEC dédiée la définira.
- Notes / `total_rating_count`, captures, vidéos IGDB : hors ADR-0944.
- Second appel IGDB par identifiants pour les jeux en tendance sans aucune
  hype : non retenu (un jeu sans hype n'a aucun signal IGDB ; le relevé
  Twitch/Steam le montre déjà dans « Ce qui monte »).
