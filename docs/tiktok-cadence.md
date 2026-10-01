# Étude : cadence de publication TikTok sûre et efficace

Tâche TASK-8f5f8413622d, pour régler la table `[tiktok]` (SPEC-9225, R6 : défauts
provisoires de 3 posts par jour et 120 min d'écart, « à revoir par une étude »).

- Date de l'étude : 2026-10-01.
- Méthode : recherches web uniquement (aucune ligne de code).
- Limite importante : les pages elles-mêmes n'ont pas pu être ouvertes (le réseau
  de l'environnement bloque `tiktok.com` et la plupart des sites tiers). Les faits
  ci-dessous viennent des **résumés de résultats de recherche** et des pages
  indiquées en lien. Les pages d'aide officielles de TikTok n'ont **pas** été lues
  directement : tout ce qui leur est attribué passe par des sources secondaires.
  Chaque point à valeur de décision est à reconfirmer dans TikTok Studio avant de
  figer un défaut.

## 1. Faits sourcés

Convention : « officiel » = rapporté comme venant de TikTok, mais lu via une source
secondaire. « Secondaire » = blogs, agences, éditeurs d'outils, études privées.

### 1.1 Nombre de posts par jour et par compte

| Fait | Nature | Source |
|---|---|---|
| TikTok conseille 1 à 4 posts par jour, la constance primant sur un chiffre précis. | Officiel (relayé) | [Joinbrands](https://joinbrands.com/blog/how-often-to-post-on-tiktok/), [Powerful Marketers](https://powerful-marketers.com/how-many-tiktoks-should-i-post-a-day/), [Hooked](https://www.hooked.so/blog/how-many-tiktoks-should-i-post-a-day) |
| Au-delà de 4 à 5 vidéos par jour : baisse de portée et d'engagement, risque de signalement par l'algorithme, vidéos qui se concurrencent. | Secondaire | [Social Champ](https://www.socialchamp.com/blog/how-often-should-you-post-on-tiktok/), [Handler](https://gethandler.ai/blog/how-long-to-wait-between-tiktok-posts) |
| Comptes neufs (0-10 000 abonnés) : 7 à 14 posts par semaine ; comptes établis (100 000+) : 3 à 5 par semaine. | Secondaire | [NapoleonCat](https://napoleoncat.com/blog/how-often-to-post-on-tiktok/) |
| Sur 11,4 millions de posts, 2 à 5 posts par semaine donnent le meilleur gain de vues par effort ; au-delà de 5 par semaine, rendement décroissant. | Étude privée | [Buffer](https://buffer.com/resources/best-time-to-post-on-tiktok/) |
| Pas de plafond quotidien universel annoncé pour la publication dans l'application ; des fonctions précises ont leur plafond (ex. 30 vidéos « shoppable » par jour). | Secondaire | [TikTok Discover](https://www.tiktok.com/discover/does-tiktok-limit-how-many-posts-a-day?lang=en) |
| Via l'API de publication directe, TikTok impose un plafond par compte créateur sur 24 h, typiquement autour de 15 posts, variable selon le compte. | Secondaire (API) | [Storrito](https://storrito.com/help-center/tiktok-post-limits/) |

### 1.2 Écart minimal entre deux posts

| Fait | Nature | Source |
|---|---|---|
| Aucun minimum imposé par TikTok ; l'usage retenu est un plancher de 3 à 4 h entre deux posts. | Secondaire | [Handler](https://gethandler.ai/blog/how-long-to-wait-between-tiktok-posts), [Predis](https://predis.ai/resources/how-long-should-i-wait-to-post-another-tiktok/), [Likefy](https://likefy.com/en/how-long-should-i-wait-to-post-another-tiktok/) |
| Une analyse de comptes espaçant d'au moins 3 à 4 h trouve +22 % d'engagement moyen par vidéo face à des comptes qui publient à l'heure. | Étude privée, non vérifiée | [Handler](https://gethandler.ai/blog/how-long-to-wait-between-tiktok-posts) |
| Si un post décolle, attendre plus longtemps (6 à 8 h) ; s'il est « mort » après 2 h, on peut republier plus tôt. | Secondaire | [Handler](https://gethandler.ai/blog/how-long-to-wait-between-tiktok-posts) |

### 1.3 Heures et jours favorables (France)

| Fait | Nature | Source |
|---|---|---|
| Étude Agorapulse × Play Play (France) : jeudi, vendredi et week-end favorables ; plages 6 h-10 h et 19 h-23 h ; engagement relativement stable dans la journée, pic à 22 h. | Étude d'éditeur, France | [Swello](https://swello.com/fr/blog/quand-poster-sur-tiktok-2025/), [Neads](https://neads.io/blog/quand-poster-sur-tiktok/) |
| Synthèses françaises : créneaux 6 h-10 h, 12 h-13 h, 18 h-22 h, pic à 20 h. | Secondaire, France | [Lesmakers](https://lesmakers.fr/quand-poster-sur-tiktok/), [Mo-jo](https://www.mo-jo.fr/blog/meilleurs-moments-poster-videos-tiktok), [Ruche Pollen](https://ruche-pollen.com/blog-social-media/meilleur-moment-poster-tiktok-heures-virales-2025) |
| Influencer Marketing Hub (plus de 100 000 vidéos) : meilleurs résultats entre 18 h et 22 h, heure locale. | Étude privée, non propre à la France | [Lesmakers](https://lesmakers.fr/quand-poster-sur-tiktok/) |
| Buffer (7,1 millions de posts, monde) : meilleur jour le samedi, meilleur créneau le dimanche 9 h, puis lundi 13 h. | Étude privée, monde | [Buffer](https://buffer.com/resources/best-time-to-post-on-tiktok/) |
| Les études divergent sur le week-end (Sprout Social favorise les après-midi de semaine) : les créneaux sont à tester sur son propre compte. | Secondaire | [Buffer](https://buffer.com/resources/best-time-to-post-on-tiktok/) |

Lecture : les heures varient d'une étude à l'autre, seule la tendance « matin tôt,
midi, soirée » est stable en France. Aucune étude n'est propre à une niche.

### 1.4 Risque de restriction (fréquence, automatisation)

| Fait | Nature | Source |
|---|---|---|
| Les règles TikTok interdisent le spam, dont l'usage de l'automatisation pour faire tourner de nombreux comptes ou envoyer du contenu répétitif, et les outils conçus pour contourner ses systèmes. | Officiel (relayé) | [Newsroom TikTok](https://newsroom.tiktok.com/en-eu/how-tiktok-counters-deceptive-behaviour), [OpenTermsArchive](https://github.com/OpenTermsArchive/contrib-versions/blob/main/TikTok/Community%20Guidelines.md), [Socially In](https://sociallyin.com/resources/tiktok-rules/) |
| Les conditions d'utilisation US (mises à jour le 15 juillet 2026, d'après la source) interdisent bots et scraping sans accord écrit de TikTok ; les scripts non officiels exposent à un bannissement. | Secondaire | [InstantDM](https://instantdm.com/blog/is-tiktok-automation-allowed) |
| TikTok peut signaler un compte qui publie trop souvent comme spam ; baisse brutale de vues (« shadowban ») possible avant une restriction complète ; un contenu d'allure automatisée peut déclencher des restrictions même sans infraction au fond. | Secondaire | [Ayrshare](https://www.ayrshare.com/docs/help-center/technical-support/tiktok_account_restricted), [TikTok Discover](https://www.tiktok.com/discover/what-to-do-if-you-cant-post-tiktoks-because-your-posting-too-much) |
| La détection s'appuie sur des comportements mécaniques (intervalles réguliers, actions instantanées). | Secondaire, vendeurs d'outils | [Post Bridge](https://support.post-bridge.com/troubleshooting/how-and-why-to-warm-up-a-new-tiktok-account-before-using-post-bridge), [GeeLark](https://www.geelark.com/glossary/tiktok-warmup-bot/) |
| Compte neuf : 7 à 14 jours pour établir la confiance ; schéma courant : 4 jours d'usage sans publier, 1er post jour 5-6, un post par jour ensuite, en manuel depuis le téléphone tant que les vues restent sous ~500. Sauter cette phase : posts bloqués, 0 vue, shadowban, suspension dans les cas graves. | Secondaire, vendeurs d'outils (intérêt commercial) | [Post Bridge](https://support.post-bridge.com/troubleshooting/how-and-why-to-warm-up-a-new-tiktok-account-before-using-post-bridge), [Blotato](https://help.blotato.com/platforms/tiktok/brand-new-accounts), [Multilogin](https://multilogin.com/blog/how-to-warm-up-tiktok-account/) |

Aucune source lue ne donne de seuil chiffré d'actions par minute ou de délai
minimal entre clics. Les délais d'action (§3) sont donc des recommandations sans
base chiffrée.

### 1.5 Programmation dans TikTok Studio

| Fait | Nature | Source |
|---|---|---|
| Programmation native gratuite de 15 minutes à 10 jours à l'avance, depuis un navigateur de bureau ou l'application TikTok Studio, compte Créateur ou Business uniquement. | Secondaire | [Hopper HQ](https://www.hopperhq.com/blog/how-to-schedule-tiktok-posts-desktop-mobile/), [Octospark](https://octospark.ai/tiktok-post-scheduler/), [Metricool](https://metricool.com/schedule-tiktok-videos/) |
| Un post programmé ne se modifie pas : il faut le supprimer et le renvoyer. | Secondaire | [Handler](https://gethandler.ai/blog/can-you-schedule-posts-on-tiktok) |
| Vidéos seulement (pas de carrousels, playlists, lives). | Secondaire | [Handler](https://gethandler.ai/blog/can-you-schedule-posts-on-tiktok) |
| Envoi groupé : jusqu'à 30 vidéos importées en une session (début 2026) ; c'est une limite d'import, pas un plafond de posts programmés. | Secondaire | [adamconnell.me](https://adamconnell.me/schedule-tiktok-posts/) |
| Vidéos « shoppable » : programmation de 30 minutes à 30 jours, jusqu'à 50 vidéos programmées par compte. Cas particulier, non applicable aux vidéos ordinaires. | Officiel (TikTok Seller University, relayé) | [TikTok Seller University](https://seller-us.tiktok.com/university/essay?knowledge_id=7651565985810231&lang=en) |

**Non trouvé :** aucun nombre maximal de posts programmés en même temps pour une
vidéo ordinaire n'apparaît dans les résultats. À mesurer ou à lire dans TikTok
Studio avant d'en dépendre.

## 2. Écarts et incertitudes

- Presque tout vient de blogs, d'agences et d'éditeurs d'outils, dont certains
  vendent des services de planification ou de « warm-up » : intérêt commercial.
- Les chiffres « +22 % d'engagement » et « +300 % de croissance » ne sont pas
  vérifiables ici.
- Les études d'heures se contredisent (week-end vs semaine) et ne sont pas
  spécifiques à la France, sauf celle d'Agorapulse × Play Play.
- Le plafond API (~15 posts par 24 h) concerne l'API de publication directe, pas
  le navigateur piloté par ce projet (SPEC-9225).

## 3. Recommandations (non sourcées en tant que telles)

Elles découlent des faits ci-dessus avec une marge de prudence ; ce sont des
choix de conception, pas des règles de TikTok. Le défaut actuel (3 posts par jour,
120 min d'écart) est sous le plancher usuel de 3 à 4 h et trop agressif pour un
compte neuf.

### 3.1 Valeurs proposées pour `[tiktok]`

| Réglage | Compte neuf (14 premiers jours, puis revue) | Compte établi (après 14 jours, vues stables) |
|---|---|---|
| `max_posts_per_day` | 1 (2 au plus après une semaine sans incident) | 3 (jamais plus de 4, plafond du conseil officiel relayé) |
| `min_gap_minutes` | 480 | 240 |
| `min_action_delay_s` | 3 | 2 |
| `max_action_delay_s` | 12 | 8 |
| Fenêtre de programmation : avance minimale | 60 min | 30 min |
| Fenêtre de programmation : avance maximale | 3 jours | 7 jours (jamais plus que les 10 jours natifs) |

Justification :

- `max_posts_per_day` : le conseil relayé de 1 à 4 par jour sert de borne haute ;
  les sources de warm-up recommandent un post par jour au début. 3 pour un compte
  établi est dans la fourchette, avec marge sous le seuil de 4 à 5 à partir duquel
  la portée baisse.
- `min_gap_minutes` : 240 = haut du plancher de 3 à 4 h ; 480 pour un compte neuf
  garantit un espacement net même si le plafond est monté à 2.
- Délais d'action : aucun chiffre sourcé. Des délais aléatoires bornés (R6) évitent
  les intervalles mécaniques signalés en §1.4 ; un compte neuf est traité avec plus
  de lenteur. Valeurs à ajuster à l'usage réel.
- Fenêtre de programmation : le natif accepte de 15 min à 10 jours. On garde une
  marge de sécurité au-dessus du minimum et on programme court pour un compte neuf,
  car un post programmé ne se modifie pas (§1.5) et qu'une période courte limite
  les reprises. Aucun réglage de fenêtre n'existe encore dans `[tiktok]` : si la
  tâche de réglage en ajoute, ces valeurs sont les défauts proposés.
- Les créneaux de publication (hors `[tiktok]`) : viser matin (6 h-10 h), midi
  (12 h-13 h) et soirée (18 h-22 h) heure de Paris, et préférer jeudi à dimanche ;
  puis remplacer par les statistiques du compte (R7) dès qu'elles existent.

### 3.2 Garde-fous qui restent à définir hors de cette étude

- Une vraie phase de warm-up manuel (4 à 7 jours sans publication automatisée) est
  hors de portée d'un réglage numérique ; la recommandation est de la faire à la
  main avant de brancher le compte.
- Surveiller l'effondrement soudain des vues après une série de posts : signal de
  limitation à traiter en baissant `max_posts_per_day`.
- Reconfirmer dans TikTok Studio le plafond de posts programmés et la fenêtre
  15 min - 10 jours avant de graver les défauts ci-dessus.
