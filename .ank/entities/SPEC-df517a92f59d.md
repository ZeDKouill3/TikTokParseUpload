---
id: SPEC-df517a92f59d
type: spec
slug: veille-calendrier-des-sorties-de-jeux-igdb-colle
title: "Veille : calendrier des sorties de jeux (IGDB) : collecte par /games sur la fenêtre J-15..J+14 triée par hypes, jeux en tendance gardés, étiquette « Portage », jaquettes, écran calendrier (bandeau récents, frise 14 jours, téléphone, panneau détail), repère J+N et priorité à Claude inchangés (succède à SPEC-4efa)"
created: 2026-10-07T08:20:49Z
author: w-calplan
status: proposed
scope:
  - clipper/veille.py
  - clipper/veille_sources.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_veille*.py
  - tests/test_web_veille.py
  - docs/GUIDE.md
  - CHANGELOG.md
references: [ADR-0944f6d2110d, ADR-798cf21fddd6, SPEC-bdd9e0db8905, ADR-ca9a5792739c, ADR-ad2e562b1810, ADR-b1c17749b528, ADR-09ad233678f2, SPEC-c1001cb7cbdb]
supersedes: SPEC-4efa50cc6b8c
schema: 4
version: 1
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
  first_release_date | null, cover_image_id | null, release_dates:
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
  cover_image_id, first_release_date, date, human, days, platforms, regions,
  statuses, portage, trend}`.
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

## R15. Choix de Claude (R6) — inchangé, plus « portage »
Comme SPEC-4efa R15 (`sortie_j_plus=`, `hypes_igdb=`, bloc « Sorties de jeux
(IGDB) », consigne de priorité à la fenêtre de sortie). Chaque ligne du bloc
ajoute `portage=oui` quand `portage` est vrai (rien sinon) : Claude sait
qu'un portage n'est pas une nouveauté. Schéma, `check`, nombre d'appels et
comportement en erreur inchangés (R6). Aucun choix fait par le code.

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
- Un test réel optionnel derrière `CLIPPER_REAL_NETWORK=1` : une requête
  `games` sur la fenêtre du jour, au moins un jeu avec `cover_image_id` et
  une `release_dates` dans la fenêtre.

## R17. Routes et écran (R9, R10 complétés ; SPEC-c100 s'applique)
- `GET /api/veille` et `GET /api/veille/{date}` rendent `releases` et
  `sources.igdb` tels qu'écrits (aucun calcul) ; `settings` expose
  `upcoming_days`, `release_window_days`, `igdb_min_hypes`,
  `igdb_recent_max`, `igdb_upcoming_max` ; `PUT /api/settings` les écrit et
  refuse une valeur hors bornes (400, message de `VeilleError`). Aucune
  route nouvelle, aucune route d'image.
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
    FR », « top R joueurs Steam » (R = `steam_rank`) ; séparateur « · » ;
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
  et sur « Ce qui monte » (`release`) : inchangés.
- Réglages › Veille : `upcoming_days`, `release_window_days`,
  `igdb_min_hypes`, `igdb_recent_max`, `igdb_upcoming_max` éditables ;
  l'aperçu des réglages de l'écran Veille les montre.
- docs/GUIDE.md : le calendrier (bandeau, frise, téléphone, détail), les
  jaquettes chargées depuis images.igdb.com par le navigateur, les cinq
  réglages, `igdb_releases_max` ignorée. CHANGELOG mis à jour.

## Hors périmètre (non retenu)
- Recherche de VOD par jeu depuis le calendrier : pas de recherche de VOD
  dans l'application aujourd'hui ; une SPEC dédiée la définira.
- Notes / `total_rating_count`, captures, vidéos IGDB : hors ADR-0944.
- Second appel IGDB par identifiants pour les jeux en tendance sans aucune
  hype : non retenu (un jeu sans hype n'a aucun signal IGDB ; le relevé
  Twitch/Steam le montre déjà dans « Ce qui monte »).
