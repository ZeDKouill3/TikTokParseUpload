---
id: ADR-798cf21fddd6
type: adr
slug: veille-igdb-api-officielle-propri-t-de-twitch-co
title: "Veille : IGDB (API officielle, propriété de Twitch) comme source des dates de sortie et de la hype des jeux, avec le même jeton d'app Twitch que Helix"
created: 2026-10-06T19:34:11Z
author: w-igdb
status: proposed
scope:
  - clipper/veille.py
  - clipper/veille_sources.py
constraint: |
  La veille peut lire l'API officielle IGDB (https://api.igdb.com/v4, propriété de Twitch) avec le même jeton d'app Twitch (client_credentials) et le même cache que Helix, par un collecteur et un transport injectables, pour les dates de sortie et la hype des jeux seulement ; requêtes séquentielles (jamais en parallèle, au plus 4 par seconde), jamais de scraping ; une source IGDB sans clé ou en erreur est une erreur nommée et visible, jamais une date ni un chiffre inventé.
amends: [ADR-ca9a5792739c]
schema: 4
version: 1
---

## Contexte
Sur le compte TikTok de l'utilisateur, les 6 posts à plus de 10 000 vues datent
tous de J+3 à J+15 après la sortie d'Hytale (13/01/2026) ; médiane 829 vues sur
Hytale contre 388 hors Hytale (relevé du 2026-10-06). La veille (ADR-ca9a,
SPEC-bdd9) voit un jeu « qui monte » mais ne sait pas qu'il vient de sortir ni
qu'une sortie arrive : elle ne peut ni anticiper ni prioriser la fenêtre de
sortie. ADR-ca9a limite les sources à Twitch Helix, YouTube Data API v3 et
Steam Web API : IGDB n'y est pas, d'où cet amendement.

## Décision
1. **IGDB est une source officielle admise**, en plus des trois d'ADR-ca9a.
   Documentation lue le 2026-10-06 : https://api-docs.igdb.com/ (sections
   `#account-creation`, `#authentication`, `#requests`, `#rate-limits`,
   `#release-date`, `#game`, `#pagination`). IGDB appartient à Twitch, son
   API est gratuite pour un usage non commercial (Twitch Developer Service
   Agreement) et s'authentifie exactement comme Helix : `POST
   https://id.twitch.tv/oauth2/token` en `client_credentials`, puis en-têtes
   `Client-ID` et `Authorization: Bearer <access_token>`.
2. **Mêmes identifiants, même jeton, même cache.** `[veille]
   twitch_client_id` / `twitch_client_secret` et `state/veille/
   twitch_token.json` servent aussi à IGDB : aucune clé nouvelle, aucun
   secret nouveau à masquer. Un 401 renouvelle le jeton une fois, comme pour
   Helix.
3. **Périmètre : sorties et hype seulement.** Endpoints `release_dates` (avec
   expansion de `game`, `platform`, `release_region`, `status`,
   `date_format`) et, au besoin, `games`. Pas de recherche de jeux, pas de
   popularité externe, pas de contenu.
4. **Limites respectées par construction.** La doc fixe 4 requêtes par
   seconde (429 au-delà) et 8 requêtes ouvertes au plus : le collecteur
   envoie ses requêtes l'une après l'autre, jamais en parallèle, et une
   pagination plafonnée (`limit` 500 au plus par page). Un 429 est une
   erreur de source visible, pas une attente silencieuse.
5. **Pas de repli silencieux (ADR-ad2e).** IGDB en erreur : la section
   « Sorties » et les repères J+N sont absents avec le message d'erreur ; les
   autres sources et le choix de Claude continuent. Aucune date n'est
   déduite d'un autre signal.

## Conséquences
- Nouvelle source `igdb` dans `clipper/veille_sources.py` et
  `clipper/veille.py` ; règles détaillées dans la SPEC qui s'appuie sur cet
  ADR (sorties à venir, repère J+N, priorité donnée à Claude, réglages).
- Une à quatre requêtes IGDB par relevé quotidien : négligeable.
- Steam « Prochainement » (`appdetails` → `release_date`) n'est pas retenu :
  IGDB couvre déjà les sorties PC et consoles et `external_games`
  (`category = 1` = Steam) permet la correspondance Steam si un jour utile.
