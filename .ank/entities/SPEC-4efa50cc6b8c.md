---
id: SPEC-4efa50cc6b8c
type: spec
slug: veille-source-igdb-sorties-de-jeux-section-sorti
title: "Veille : source IGDB (sorties de jeux), section « Sorties » (récentes J+N, à venir 14 j), repère J+N sur les jeux et les VOD, priorité donnée à Claude à la fenêtre de sortie (J0 à J+15), réglages [veille], tests sans réseau (complète SPEC-bdd9)"
created: 2026-10-06T19:36:37Z
author: w-igdb
status: superseded
scope:
  - clipper/veille.py
  - clipper/veille_sources.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_veille*.py
  - tests/test_web_veille.py
  - docs/GUIDE.md
references: [ADR-798cf21fddd6, SPEC-bdd9e0db8905, ADR-ca9a5792739c, ADR-ad2e562b1810, ADR-b1c17749b528]
ratified: fb2cb4ee8c70
verified:
  - by: nicoc@zedk_ordi
    at: 2026-10-07T06:51:53Z
schema: 4
version: 3
---

## Objet
Ajoute à la veille (SPEC-bdd9, qui reste entière et en vigueur) une quatrième
source, IGDB (ADR-798c), pour connaître le calendrier des sorties de jeux :
une section « Sorties » (récentes et à venir), un repère J+N sur chaque jeu et
chaque VOD candidate dont le jeu vient de sortir, et une consigne de priorité
donnée à Claude pour la fenêtre de sortie. Motif mesuré : les 6 posts TikTok
de l'utilisateur à plus de 10 000 vues datent tous de J+3 à J+15 après la
sortie d'Hytale (13/01/2026). Tout est fichier JSON sous `state/veille/`
(R2 de SPEC-bdd9), sans valeur de secours silencieuse (ADR-ad2e). « Aujourd'hui »
= date Europe/Paris (`[veille] timezone`). La numérotation continue celle de
SPEC-bdd9 (R1 à R10).

Doc IGDB lue le 2026-10-06 (https://api-docs.igdb.com/) : `#authentication`
(même jeton Twitch client_credentials), `#requests` (`POST https://api.igdb.com/v4/<endpoint>`,
en-têtes `Client-ID` et `Authorization: Bearer`, corps Apicalypse),
`#rate-limits` (4 requêtes/s, 429 au-delà, 8 requêtes ouvertes au plus),
`#pagination` / `#limit` / `#offset` (`limit` 10 par défaut, 500 au plus),
`#expander` (`game.name`), `#release-date` (champs `date` datetime, `human`,
`platform`, `release_region`, `status`, `date_format`, `game`, `y`, `m`, `d` ;
`region` et `category` dépréciés), `#game` (`hypes` Integer « Number of follows
a game gets before release » ; `follows` « DEPRECATED! - To be removed » :
jamais utilisé), `#coming-soon-games-for-playstation-4` (exemple
`where ... date > <epoch>; sort date asc;`). Les valeurs possibles de
`release_date_statuses.name`, `release_date_regions.region` et
`date_formats.format` ne sont pas énumérées dans la doc : elles sont relevées
telles quelles, jamais interprétées (R13).

## R11. Réglages (`[veille]`, ajoutés à CONFIG_DEFAULTS de clipper/veille.py)
| clé | défaut | rôle |
|---|---|---|
| `upcoming_days` | `14` | horizon des sorties à venir, en jours (≥ 1) |
| `release_window_days` | `15` | un jeu sorti il y a 0 à N jours est « en fenêtre de sortie » (≥ 0) |
| `igdb_min_hypes` | `0` | une sortie dont `hypes` est inférieur (ou absent, si > 0) n'est pas listée (≥ 0) |
| `igdb_releases_max` | `30` | sorties gardées par liste (récentes, à venir), après tri (≥ 1) |
| `igdb_pages_max` | `4` | pages de 500 lignes au plus par relevé (≥ 1) |
Aucune clé nouvelle : IGDB utilise `twitch_client_id` / `twitch_client_secret`
(R8). Valeur hors bornes : `VeilleError` nommant la clé (R1).

## R12. Collecteur `igdb` (clipper/veille_sources.py, transport injectable)
- Source `igdb` ajoutée à `SOURCES` ; clés exigées : celles de `twitch`
  (clé vide → `error` « twitch_client_id absente : à saisir dans Réglages ›
  Veille », collecteur non appelé, comme R3).
- Jeton : celui de `_Twitch` (`twitch_token.json`, renouvelé sur 401 une
  fois). En-têtes `Client-ID: <client_id>`, `Authorization: Bearer <jeton>`,
  `Accept: application/json`.
- Une requête `POST https://api.igdb.com/v4/release_dates`, corps texte :
  `fields game.name,game.slug,game.url,game.hypes,game.first_release_date,
  date,human,platform.name,release_region.region,status.name,
  date_format.format; where date >= <début> & date < <fin> & game != null;
  sort date asc; limit 500; offset <k×500>;` avec `début` = minuit UTC de
  (aujourd'hui − `release_window_days`) et `fin` = minuit UTC de
  (aujourd'hui + `upcoming_days` + 1), en secondes Unix (la doc type `date`
  en datetime et `first_release_date` en « Unix Time Stamp » ; son exemple
  dit « milliseconds » mais sa valeur 1538129354 est en secondes : le test
  réel optionnel de R16 tranche, le code suit les secondes).
- Pagination : page suivante tant que la page rend 500 lignes et que
  `igdb_pages_max` n'est pas atteint ; requêtes l'une après l'autre, jamais
  en parallèle ; au moins 250 ms entre deux requêtes IGDB (4/s) via
  l'horloge injectée. HTTP 429 : `SourceError` « IGDB : limite de 4
  requêtes/s dépassée (HTTP 429) », pas de réessai.
- Retour : `{"releases": [{igdb_id, name, slug, url, hypes | null,
  first_release_date | null, date (« YYYY-MM-DD », jour UTC du timestamp),
  human | null, platform | null, region | null, status | null,
  date_format | null}], "skipped_rows": n}`, une entrée par ligne
  `release_dates`. `game` absent ou sans `name`, ou `date` absente : ligne
  ignorée et comptée dans `skipped_rows`. Champ `hypes` absent → `null`
  (jamais 0).
- Erreur HTTP, JSON illisible, champ attendu absent : `SourceError` avec
  code, URL et début de réponse, sans jeton (R3).

## R13. Sorties du jour (clipper/veille.py, `days/<date>.json`)
`collect` regroupe les lignes par `igdb_id` : une sortie = `{igdb_id, name,
key (normalize(name)), slug, url, hypes, date (la plus ancienne du jeu dans
la fenêtre), human, platforms: [noms uniques triés], regions: [uniques],
statuses: [uniques], days: date − aujourd'hui en jours (négatif ou 0 = déjà
sorti)}`. `statuses`, `regions`, `date_format` sont relevés tels quels et
affichés tels quels : aucun filtre dessus (valeurs non documentées).
- `releases.recent` : `days` dans [−`release_window_days`, 0], tri `days`
  décroissant (le plus récent d'abord) puis `hypes` décroissant (null en
  dernier) puis `name`.
- `releases.upcoming` : `days` dans [1, `upcoming_days`], tri `date`
  croissante puis `hypes` décroissant puis `name`.
- `igdb_min_hypes` > 0 : une sortie avec `hypes` null ou < seuil est écartée
  et comptée dans `releases.excluded_low_hypes`.
- Chaque liste est coupée à `igdb_releases_max` ; `releases.truncated`
  = `{recent: n, upcoming: n}` (sorties écartées par la coupe).
- `sources.igdb` = `{status, at, error, counts: {rows, recent, upcoming,
  skipped_rows}}` comme les autres sources (R2). Source en erreur :
  `releases = {recent: [], upcoming: [], excluded_low_hypes: 0, truncated:
  {recent: 0, upcoming: 0}}`, aucun repère J+N (R14), l'erreur visible dans
  `sources.igdb.error`. `history/<date>.json` ne change pas (pas de
  moyenne sur 7 jours pour une date de sortie).

## R14. Repère J+N sur les jeux (R4) et les VOD candidates (R5)
- Chaque jeu de `games` porte `release: {igdb_id, name, date, days_since,
  hypes} | null`. Correspondance : par `igdb_id` quand le collecteur Twitch
  fournit `igdb_id` pour ce jeu (champ optionnel `igdb_id` des `games`
  Twitch, rempli depuis `helix/games/top` dont la doc Helix dit « igdb_id :
  The ID that IGDB uses to identify this game. If the IGDB ID is not
  available to Twitch, this field is set to an empty string ») ; sinon par
  `key` normalisée (R4). Une sortie `recent` seulement (`days_since` =
  −`days`, 0 à `release_window_days`) ; une sortie à venir ne met pas de
  repère (le jeu n'est pas sorti). Sans correspondance : `null`.
- Chaque candidat porte `signals.release_days_since` (entier ou `null`)
  copié du jeu de son `game_key`.
- Un jeu « en fenêtre de sortie » = `release` non nul. Ce n'est pas un
  filtre : les jeux hors fenêtre restent relevés et candidats.

## R15. Choix de Claude (R6, complété)
Le prompt de `decide` ajoute :
- à chaque ligne de jeu : `sortie_j_plus=<days_since | inconnu>` et
  `hypes_igdb=<hypes | inconnu>` ;
- à chaque ligne de candidat : `sortie_j_plus=<release_days_since | inconnu>` ;
- un bloc « Sorties de jeux (IGDB) » : les `recent` (nom, J+N, hypes,
  plateformes) puis les `upcoming` (nom, date, J−N, hypes, plateformes) ;
  source en erreur : « Sorties de jeux : indisponibles (<erreur>) » ;
- la consigne : « Un jeu sorti depuis 0 à `release_window_days` jours est
  dans sa fenêtre de sortie : à qualité de gameplay égale, propose d'abord
  ses VOD ; une sortie à venir n'est pas un motif de choix aujourd'hui. »
Schéma, `check`, nombre d'appels et comportement en erreur inchangés (R6).
Aucun choix n'est fait par le code à la place de Claude.

## R16. Tests (aucun réseau par défaut)
- Collecteur `igdb` injecté (`collectors["igdb"]`) et transport injecté :
  regroupement, bornes de fenêtre (J−15, J0, J+1, J+14, J+15 exclu), tris,
  `igdb_min_hypes`, coupe et `truncated`, `hypes` absent → null, lignes sans
  `game` ou sans `date` comptées, repère par `igdb_id` puis par `key`,
  `signals.release_days_since`, prompt (lignes et bloc), source en erreur
  (tout à vide, erreur visible, autres sources intactes), 429 → erreur
  nommée, espacement des requêtes (horloge injectée), pagination plafonnée,
  réglages hors bornes → `VeilleError` nommant la clé, secrets absents des
  messages.
- Un test réel optionnel derrière `CLIPPER_REAL_NETWORK=1` (comme les
  sources existantes) : une requête `release_dates` sur la fenêtre du jour
  avec les clés de `config.toml`, au moins une ligne, `date` en secondes
  Unix dans la fenêtre demandée.

## R17. Routes et écran (R9, R10, complétés ; SPEC-c100 s'applique)
- `GET /api/veille` et `GET /api/veille/{date}` rendent `releases` et
  `sources.igdb` avec l'état du jour (aucun calcul dans `clipper/web`) ;
  `settings` expose `upcoming_days`, `release_window_days`,
  `igdb_min_hypes`. Aucune route nouvelle.
- Écran « Veille », nouvelle section « Sorties de jeux » placée entre les
  propositions du jour et les meilleurs clips : deux listes, « Sorties
  récentes » (nom, badge « J+N », hypes, plateformes, lien « Voir sur IGDB »
  vers `url`) et « À venir (N j) » (nom, date, badge « J−N », hypes,
  plateformes, lien) ; liste vide : « Aucune sortie dans la fenêtre » ;
  `truncated` > 0 : « +n autres » ; source en erreur : le message de
  `sources.igdb.error` en rouge, pas de liste. Bandeau des sources :
  `igdb` ajouté (libellé « IGDB (sorties) »).
- Badge « Sortie J+N » sur chaque proposition dont le candidat porte
  `signals.release_days_since` non nul, et sur chaque ligne de « Ce qui
  monte » dont le jeu porte `release`.
- Réglages › Veille : `upcoming_days`, `release_window_days`,
  `igdb_min_hypes` éditables ; l'aperçu des réglages de l'écran Veille les
  montre. docs/GUIDE.md : IGDB utilise les clés Twitch déjà saisies, rien
  de plus à faire ; la section et les réglages décrits. CHANGELOG mis à jour.

## Hors périmètre (non retenu)
- Steam « Prochainement » / `appdetails.release_date` : IGDB couvre déjà
  les sorties PC et consoles ; à reconsidérer si IGDB manque des sorties.
- Popularity API IGDB (`popularity_primitives`, « Want to Play ») : signal
  possible plus tard, pas nécessaire au calendrier.
- Pas de sélection automatique par le code selon la fenêtre : Claude seul
  choisit (ADR-ca9a §4), la fenêtre est une consigne et un affichage.
