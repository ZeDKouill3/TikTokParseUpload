# Changelog

Toutes les évolutions notables de ce dépôt sont consignées ici. Format inspiré
de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Depuis la 0.2.0,
le dépôt suit le [versionnage sémantique](https://semver.org/lang/fr/) :
`MAJEUR.MINEUR.CORRECTIF`, avec le plan de versions et les critères de la 1.0.0
dans [`docs/versions.md`](docs/versions.md). Tant que la version reste en `0.x`,
la configuration, les écrans et les fichiers d'état peuvent encore changer.
Notes de version détaillées : [`docs/releases/`](docs/releases/).

## [Non publié]

## [0.5.1] - 2026-10-06

Petite version de correction autour de la veille (écran Veille). Le zip
s'appelle `Clipper-portable-0.5.1.zip` ; la mise à jour se fait en relançant
`Installer.bat` depuis ce zip, tes données ne sont pas touchées. Aucun nouveau
réglage : la veille reste désactivée par défaut (`[veille] enabled = false`).

### Ajouté

- Veille : chaque VOD proposée (Twitch et YouTube) affiche sa miniature, lue dans
  la réponse de l'API, à la place du bloc gris (qui reste si la miniature manque
  ou si la VOD Twitch est encore en cours de traitement).
- Veille : le détail de la source Twitch indique combien de VOD privées ont été
  écartées.

### Corrigé

- Veille : une VOD Twitch privée n'est plus jamais proposée (champ `viewable` de
  l'API Twitch différent de `public`). Limite connue : l'API Twitch renvoie
  `viewable = public` pour une VOD réservée aux abonnés, donc ces VOD ne sont
  pas détectées et peuvent encore être proposées ; elles échouent alors au
  téléchargement (contenu réservé aux abonnés).
- Veille : un jeu présent dans les ventes Steam FR mais absent du top joueurs
  affiche son rang de ventes et sa montée au lieu de « hors Steam ». « Hors
  Steam » ne reste que pour un jeu absent de toutes les sources Steam.

## [0.5.0] - 2026-10-06

Veille des sujets chauds (Twitch, YouTube, Steam), clips courts, heure libre
par clip dans les séries programmées, légendes avec mots-clés de recherche,
recalage de la webcam et statistiques TikTok relues sur la vraie page. Pas de
fichier de notes séparé dans le dépôt pour cette version : cette section du
changelog suffit (elle sert aussi de corps à la release). Le zip s'appelle
`Clipper-portable-0.5.0.zip` ; la mise à jour se fait en relançant
`Installer.bat` depuis ce zip, tes données ne sont pas touchées. La veille est
désactivée par défaut (`[veille] enabled = false`) et les clips courts aussi
(`[moments] short_clips = false`) : sans réglage de ta part, rien ne change.

### Ajouté

- **Série programmée : coche « Heure par clip »** (TASK-fa00): dans « Programmer
  une série », mode Manuel, une coche (décochée par défaut) donne à chaque clip
  sélectionné (chaque partie d'un clip découpé) son propre champ date et heure
  (heure de Paris), pré-rempli au rythme actuel (début + intervalle, ou à la
  suite de la dernière programmation) et modifiable un par un. L'aperçu et la
  création envoient la date de chaque clip (`clip_dates`) ; chaque date est
  validée clip par clip côté Python avec les refus explicites habituels (fenêtre
  maximale, avance minimale, plafonds, créneau déjà pris sur le compte, même
  heure qu'un autre clip de la série) et le refus s'affiche sous le clip
  concerné. Une partie datée avant (ou à la même heure que) la partie
  précédente est refusée. Décochée : comportement inchangé.
- **Veille : top des ventes Steam du pays** (TASK-2784) : nouvelle source
  `steam_fr` (`IStoreTopSellersService/GetWeeklyTopSellers`, sans clé, pays =
  `[veille] region`, langue = `[veille] language`, `steam_sellers_top` = 50
  places relevées). Les noms viennent de la réponse (pas d'appel `appdetails`).
  Les jeux de `day.games` déjà présents (Twitch, Steam mondial) portent
  `steam_sellers_rank`, `steam_sellers_last_week_rank`, `steam_sellers_gain` ou
  `steam_sellers_new` (« nouveau dans le top ventes FR » : semaine dernière
  absente ou 0), fusionnés par clé normalisée sans doublon ; les jeux nouveaux
  ou gagnant au moins `steam_rank_gain_min` places sont ajoutés comme les jeux
  Steam qui montent (`source = "steam_fr"`, plafond `steam_risers_max`), même
  sans Twitch. Claude les reçoit en contexte ; une erreur de cette source est
  nommée sans bloquer les autres. Écran Veille : colonne « Ventes FR » (« #5
  +107 places » / « Nouveau dans le top ventes FR »), libellés de relevé en
  français (« 99 jeux » au lieu de « 99 games »), et « Jeux qui montent » compte
  aussi les gains de places Steam (mondial et FR).
- **Veille : jeux Steam qui montent visibles sans Twitch FR** (TASK-f4e2) :
  `day.games` ajoute les jeux Steam du relevé absents de la liste Twitch qui
  sont « nouveau dans le top » (`last_week_rank` <= 0) ou gagnent au moins
  `[veille] steam_rank_gain_min` (5) places, plafonnés à `steam_risers_max`
  (10), avec `source = "steam"`, `twitch_match = false` et les champs Twitch à
  `null` (rang inconnu = jeu non retenu, rien d'inventé). Ils sont donnés à
  Claude et affichés dans « Ce qui monte » (« Nouveau dans le top Steam » ou
  « +N places », « hors Twitch FR »), même quand Twitch est en erreur.

- **Légendes : mots-clés de recherche en tête** (TASK-b8a0) : la consigne de
  `captions` exige que la première phrase de la légende contienne le nom du jeu
  (écrit officiellement) et le streamer ou la chaîne de la source (`channel` de
  `meta.json`), puis le moment, en restant naturelle. Jeu ou chaîne inconnus :
  la consigne le dit à Claude, rien n'est inventé. Réglage
  `[captions] caption_keywords_first` (défaut `true`) ; à `false`, consigne
  identique à avant.
- **Veille des sujets chauds** (ADR-ca9a, SPEC-bdd9) : chaque jour le worker
  relève ce qui monte sur Twitch (viewers FR par jeu), YouTube (vidéos
  populaires FR) et Steam (joueurs), compare à la moyenne des 7 jours
  précédents et demande à Claude (usage `veille`, un seul appel texte) de
  proposer 2-3 VOD à clipper d'après tes goûts. Nouvel écran **Veille**
  (navigation et barre basse mobile, compteur = propositions à décider) :
  sources avec leur erreur visible, KPI, propositions avec la raison de Claude
  et le choix du style, boutons « Clipper » / « Ignorer », « Rafraîchir »
  (désactivé pendant un relevé), meilleurs clips du jour (les autres sont
  archivés, jamais supprimés, avec « Restaurer »), tableau « ce qui monte »
  (une donnée absente est expliquée, jamais un 0). Écran Clips : filtre
  « Archivés » (les clips archivés sont masqués ailleurs). Routes
  `/api/veille` (lecture et demandes seulement : le serveur web n'appelle ni
  source ni LLM) et `GET /api/clips?archived=1`. Réglages › Veille : goûts,
  nombres, heure, et les clés d'API (`twitch_client_id`,
  `twitch_client_secret`, `youtube_api_key`) en écriture seule : jamais
  renvoyées par `/api/settings` (seulement `<clé>_set`), masquées dans le
  journal. Désactivée par défaut (`[veille] enabled = false`). Voir
  `docs/GUIDE.md`, section « Veille des sujets chauds ».

- **Clips courts** (TASK-4f5e) : interrupteur `[moments] short_clips` (défaut
  `false`, bornes `short_min` = 20 s et `short_max` = 45 s), réglable par style
  ou dans `config.toml`. Actif, il remplace les durées de la grille (clip
  unique et parties de série) et demande à Claude un clip qui démarre sur le
  moment fort. Par vidéo : case « Clips courts » à trois états (valeur du
  style / oui / non) dans *Ajouter une vidéo*, `--short-clips` /
  `--no-short-clips` en ligne de commande, champ optionnel `short_clips` de
  `POST /api/queue` (les anciennes entrées gardent la valeur du style). Le mode
  est écrit dans `moments.json` et visible sur la fiche de la vidéo. Inactif :
  comportement inchangé.

### Modifié

- **Webcam du stream : bords recalés sur la vraie incrustation** (TASK-893d) :
  une fois le rectangle choisi par Claude (candidats numérotés, SPEC-4a9b), les
  quatre bords sont recalés sur le vrai bord de l'incrustation (vote des pics de
  gradient sur les images de la période, dans une marge bornée réglable
  `facecam_refine_*`, hors du visage stable). La webcam n'est plus décalée et la
  bande de texte de l'overlay ne reste plus visible sous elle. Un côté sans bord
  fiable reste tel quel et la raison est journalisée (jamais de repli
  silencieux). `facecam.json` garde `candidate_rect` (choix de Claude),
  `refined_rect` et `refine_reason`.
- **Dépôt GitHub renommé en TiktokClipper** : les liens de la documentation et
  du changelog pointent vers le nouveau nom.

### Corrigé

- **Statistiques TikTok : le relevé ne s'arrête plus sur `viewers_card`**
  (TASK-429d) : les repères des onglets Spectateurs et Engagement n'avaient
  jamais été confirmés sur la vraie page et le relevé s'arrêtait avec « élément
  attendu absent après 30 s : viewers_card ». Les repères viennent maintenant
  d'un relevé réel en lecture seule (cartes `AnalyticsCard_CardWrapper`) ; les
  barres et les valeurs « <1 % » sont lues, la courbe de rétention (un canvas)
  reste `null`, une valeur introuvable reste `null` ou arrête explicitement le
  relevé, jamais devinée.
- **Veille Steam : noms des jeux sans `GetAppList`** (TASK-7486) : Valve a
  retiré `ISteamApps/GetAppList/v2` (HTTP 404), la source Steam tombait en
  erreur. Les noms viennent maintenant de l'API magasin sans clé
  (`store.steampowered.com/api/appdetails`), demandés seulement pour les jeux du
  top, mis en cache sous `state/veille/steam_names.json` (un nom connu ne se
  redemande pas) et plafonnés par `[veille] steam_name_lookups_max` (100) par
  relevé. Un jeu dont le nom reste introuvable n'est pas relevé et sa raison est
  gardée (`unnamed` dans l'état de la source), jamais un nom inventé.
- **Veille Steam : montée immédiate par le rang** (TASK-7486) : le relevé garde
  `rank` et `last_week_rank` de `GetMostPlayedGames` ; chaque jeu porte
  `steam_rank_gain` (gain de rang vs semaine dernière) et `steam_new_in_top`
  (`last_week_rank` 0 = nouveau dans le top, sans gain chiffré ; champ absent =
  `null`), transmis à Claude avec les candidats à côté de la montée vs 7 jours,
  qui reste `null` tant que l'historique manque.


## [0.4.2] - 2026-10-06

Webcam du stream retrouvée avec l'aide de Claude, garde-fou réseau pour le
navigateur piloté, publication TikTok plus robuste, statistiques plafonnées et
gestion de l'espace disque. Pas de fichier de notes séparé dans le dépôt pour
cette version : cette section du changelog suffit. Le zip s'appelle
`Clipper-portable-0.4.2.zip` ; la mise à jour se fait en relançant
`Installer.bat` depuis ce zip, tes données ne sont pas touchées.

### Ajouté

**Webcam du stream**

- La webcam du stream est maintenant trouvée **par période** (Just Chatting,
  puis jeu) au lieu d'un seul rectangle pour toute la vidéo. Les rectangles
  candidats (visages, cadres nets en mouvement) sont numérotés sur une planche
  et Claude répond seulement par un numéro ou « aucune » : jamais de
  coordonnées inventées. Le choix de chaque clip suit la période où il
  commence, et la décision est écrite par clip pour pouvoir la relire
  (SPEC-4a9b, proposée).

**Réseau**

- La console affiche le **pays de l'IP publique** dans une pastille en haut à
  droite, avec un réglage du pays attendu (`[network]` : `expected_country`,
  `geo_url`, `cache_s`, `block_browser`).
- Le navigateur piloté (TikTok, YouTube) **refuse de s'ouvrir** quand l'IP est
  hors du pays attendu, par exemple VPN actif.
- Au clic sur **Publier** ou **Valider**, une fenêtre d'alerte prévient quand
  l'IP est hors du pays attendu.

**Vidéos et disque**

- Purge des fichiers lourds d'une vidéo, ou de toutes les vidéos terminées,
  avec la taille affichée et une confirmation avant suppression.
- Une vidéo **interrompue** (serveur ou PC arrêté en plein traitement) est
  affichée comme interrompue, jamais comme « en cours » : tu peux la
  **reprendre** là où elle s'est arrêtée ou l'**annuler** (étapes finies
  conservées, action journalisée).
- La miniature des VOD non YouTube (Twitch...) apparaît dès l'ajout à la file.

**Statistiques TikTok**

- Les vidéos **restreintes** (non éligibles à la recommandation « Pour toi »)
  sont repérées au relevé détaillé : pastille par post, résumé « N vidéos
  restreintes sur M en ligne » par compte, texte de TikTok dans la fiche.

**Agencement**

- Éditeur d'agencement split : case **« Afficher le badge »** pour retirer ou
  remettre le badge de style sans perdre sa position enregistrée.

### Modifié

- Statistiques TikTok : le détail est **plafonné aux 30 posts récents**, la
  période par défaut passe à 365 jours, et le relevé lit correctement les
  nombres du type « 1,432 » et la tuile « 24 -2 ».
- Un clip **refusé par TikTok** à la vérification de contenu prend le statut
  `refused_by_platform` : le compte et la série continuent au lieu de
  s'arrêter.
- Les accroches et titres d'écran visent une cible de mots **plus courte**
  que la limite stricte, pour ne plus déborder.
- Quand le pays de l'IP est inconnu (service de géolocalisation injoignable),
  la publication est mise **en attente et réessayée**, le compte reste prêt ;
  si le pays est différent, le worker s'arrête et décoche le compte.
- Les dates des posts TikTok, dont l'année, sont lues en heure de Paris.
- Le contrôle de la webcam par clip a été remplacé par le choix par période
  (voir Ajouté) : une webcam avec visage et cadre n'est plus évincée.

### Corrigé

- TikTok : la vérification de contenu est lue sur le texte **visible** ; un
  « Vérification en cours » resté caché ne bloque plus jusqu'au délai.
- TikTok : une vérification encore en cours n'est plus prise pour finie quand
  « Aucun problème constaté » est affiché ailleurs (fausse fin, nouvel essai,
  fenêtre « Continuer à publier ? » puis échec de publication).
- TikTok : quand la limite quotidienne de vérification est atteinte,
  l'interrupteur grisé ne bloque plus la publication, elle continue sans lui.
- TikTok : le relevé de la liste des Publications est **complet** (liste
  virtualisée, défilement du conteneur, lignes cumulées) au lieu de s'arrêter
  à quelques vidéos.
- Sous-titres : un mot trop long est raccourci (plus de 3 lettres répétées),
  puis coupé net au besoin, au lieu de faire échouer l'étape.
- Worker : le style choisi pour une vidéo est écrit dans `pipeline.json` au
  lancement, donc conservé à la relance ou à la reprise.
- Reframe : la coupe de la webcam est journalisée et le calcul en niveaux de
  gris reste en `uint8`.
- Reframe : une vraie webcam encadrée n'est plus rejetée au contrôle par clip
  quand son cadre réel est décalé de quelques pixels du rectangle retenu
  (tolérance `facecam_clip_edge_tolerance`) ; avant, tous les clips d'un
  stream pouvaient partir en letterbox.
- Console : marges de la barre « Espace disque / Purger » de l'écran Vidéos.
- Tests : le journal global n'écrit plus dans le vrai dossier `logs/` et aucun
  test n'appelle le vrai service de géolocalisation (les tests du navigateur
  piloté échouaient sur une IP hors de France).

## [0.4.1] - 2026-10-04

Installeur portable Windows et calendrier de publication Jour / Semaine /
Mois : le zip `Clipper-portable-0.4.1.zip`, à télécharger depuis la
Release GitHub, installe tout sans outil de développement, et le calendrier de
publication affiche chaque jour sans rien cacher. Pas de fichier de notes
séparé pour cette version : cette section du changelog suffit.

### Ajouté

**Installeur portable Windows** (ADR-e1da et SPEC-38f7, ratifiées)

- Un zip d'amorçage léger, `Clipper-portable-0.4.1.zip` (< 150 Mo : `uv.exe`,
  la wheel et les scripts, jamais de Python ni de site-packages dedans),
  construit par `tools/build_portable.py` et à télécharger depuis la Release
  GitHub. Le programme se construit chez toi à l'installation.
- `Installer.bat` installe Python 3.11, l'environnement, ffmpeg et `claude`
  dans un dossier programme jetable (`%LOCALAPPDATA%\Clipper\app` par défaut),
  prépare un dossier de données séparé (`Documents\Clipper` par défaut,
  jamais touché par une mise à jour), précharge les modèles et termine par un
  `clipper doctor`. Un raccourci et un lanceur ouvrent la console.
- `Desinstaller.bat` supprime le dossier programme et conserve les données
  par défaut (`--donnees` pour tout supprimer) ; il refuse de supprimer si la
  console tourne encore.
- GPU automatique : CUDA seulement si `nvidia-smi` répond, CPU sinon. Pour
  les installations hors installeur, l'extra `clipper[cuda]` installe les
  paquets `nvidia-cublas-cu12` et `nvidia-cudnn-cu12`, et leurs dossiers `bin`
  sont ajoutés au PATH du processus sans manipulation manuelle.
- ffmpeg figé sur une version précise (GyanD 9.0.2, somme de contrôle
  vérifiée) au lieu d'une URL « latest » qui changeait en quelques jours et
  cassait l'installation.
- `clipper doctor` vérifie l'installation et `clipper models prefetch`
  télécharge les modèles à l'avance ; chaque échec est affiché, jamais remplacé en silence.
- Mise à jour par simple relance d'un zip plus récent (refus explicite d'une
  version plus ancienne). Parcours complet dans
  [`docs/INSTALLATION.md`](docs/INSTALLATION.md), nouvelle section
  « Installation sans outils de développement » dans le README, critère n°1 de
  la v1.0.0 reformulé autour du zip portable.
- Test réel optionnel de l'installeur (`CLIPPER_INSTALLER_REAL=1`) : construit
  le vrai zip, l'installe en CPU dans un dossier temporaire, vérifie
  `clipper doctor`, une mise à jour puis la désinstallation complète ; jamais
  lancé en CI ni par défaut. Option `--sans-raccourci` pour ne jamais toucher
  au vrai Bureau.

**Calendrier de publication**

- Trois vues, **Jour**, **Semaine** (par défaut) et **Mois**, avec navigation
  précédent / suivant / aujourd'hui adaptée ; `/api/publish` accepte
  `range=day|week|month` (422 si invalide) et regroupe chaque publication
  dans son jour, calculé en heure de Paris.
- En Semaine, **toutes** les publications du jour sont affichées : plus de
  « +N autres », ni défilement ni coupure, la case s'agrandit (paliers
  normal / compact / mini conservés).
- En Mois, chaque case montre le numéro du jour et le **nombre de vidéos** du
  jour ; un clic sur la case ouvre la vue Jour.
- Les créneaux libres restent des cibles de glisser-déposer en Jour et en
  Semaine, jamais tronqués.
- La **légende en couleurs** (planifié / programmé, publié, échec) reprend
  les couleurs des boîtes du calendrier.

### Modifié

- Semaine : la colonne vide de gauche (reste de l'ancienne grille horaire)
  est retirée, sept colonnes de jours.
- Le critère n°1 de la v1.0.0 (`docs/versions.md`) porte sur le zip portable
  de la Release.

### Corrigé

- Séries programmées : quand des clips validés existent mais qu'aucune série
  ne tient dans N places, le message n'affirme plus à tort « aucun clip
  validé » : il indique combien de clips et de parties sont validés et
  propose de passer à N vidéos ou de décocher « Parties ensemble ».
- Installeur, 16 points confirmés par une relecture : `uv.exe` et
  `clipper.exe` appelés par leur chemin complet, relance possible après une
  installation interrompue, override OpenCV livré dans le zip (un seul paquet
  OpenCV installé), lanceur en encodage OEM, pause sur erreur en
  double-clic, `install.json` relu à la relance, désinstallation qui vérifie
  le dossier programme, `Desinstaller.bat` et icône copiés dans `app`.
- Installeur, corrigé grâce au vrai passage de test : `Installer.bat` et
  `Desinstaller.bat` pointaient le mauvais chemin de `install.ps1` ;
  `uv pip install` sans `--python` pouvait installer dans un environnement
  ambiant (désormais explicite) ; `app\version.txt` n'était jamais écrit, si
  bien qu'une relance se croyait en première installation ; le script
  `claude.ai/install.ps1` peut renvoyer un `Byte[]` (plantait avec
  `Invoke-Expression`) et `claude` installé restait hors du PATH du processus
  courant.
- Tests dépendants de l'heure rendus déterministes : plusieurs tests
  (plafond par jour TikTok/YouTube du worker, semaine publiée) lisaient
  l'horloge deux fois et pouvaient échouer près de minuit ; l'horloge est
  figée, le calcul de « lundi » se fait dans le fuseau du compte (Paris) et
  non plus en UTC. Aucun bug du code livré n'a été révélé.

## [0.4.0] - 2026-10-03

YouTube Shorts et publication avancée : publication immédiate ou programmée
sur YouTube (comme TikTok), séries programmées, approbation groupée, calendrier
de publication toujours visible, styles détachés du compte de publication,
éditeur d'agencement letterbox, journal global de toutes les actions, et une
série de correctifs de fiabilité (revues de code sur la publication, les
comptes, le worker et la transcription). Pas de fichier de notes séparé pour
cette version : cette section du changelog suffit.

### Ajouté

**YouTube**

- Comptes YouTube (service `youtube` à côté de `tiktok`), connexion par un
  Chrome normal sur `studio.youtube.com`, « prêt à publier » vérifié comme
  pour TikTok (nom de chaîne et identifiant de chaîne enregistrés).
- Publication sur YouTube Shorts, immédiate ou programmée, par pilotage de
  YouTube Studio (`clipper/youtube.py`) : titre, description, visibilité,
  case « conçue pour les enfants », `#Shorts` ajouté si absent, lien
  `youtube.com/shorts/<id>` enregistré ; plafond de publications par jour et
  écart minimal entre deux publications (SPEC-5e50) ; toutes les dates
  saisies (TikTok et YouTube) en heure de Paris, jamais celle du PC.

**Publication et séries**

- « Programmer une série » : choisis un compte, un style (optionnel), un
  nombre de vidéos et un intervalle en heures ; Clipper choisit les N
  meilleurs clips validés (score décroissant, parties d'un clip ensemble et
  dans l'ordre), calcule les dates (passage heure d'été/hiver géré), affiche
  un aperçu, puis crée les publications d'un coup (SPEC-1ed3).
- Le mode automatique d'une série (programmée ou non) ne pioche plus que
  dans les clips déjà validés (approuvés) du compte choisi ; le nombre de
  vidéos demandé est plafonné au nombre de clips réellement disponibles, et
  une coche « Parties ensemble » (activée par défaut) impose qu'un clip
  découpé en plusieurs parties soit toujours programmé ou publié en entier.
- « Programmer une série » : coche « À la suite de la dernière
  programmation » (décochée par défaut) ; la série démarre à la dernière
  publication à venir du compte + l'intervalle, date calculée côté serveur
  et affichée à l'heure de Paris.

**Approbation**

- Écran Clips : sélection multiple et approbation groupée pour un même
  compte (« Sélectionner », cases à cocher, barre d'action en bas) ; cocher
  une partie d'un clip découpé sélectionne toute sa série ; tout ou rien
  (un clip déjà publié ou refusé dans la sélection annule tout).

**Calendrier**

- Écran Publication : le calendrier hebdomadaire est désormais toujours
  affiché (passé et futur, publications Clipper et déclarées manuellement),
  même sans compte choisi ni créneaux réguliers ; la liste des clips validés
  à publier n'apparaît plus deux fois (fusion en une seule liste « En
  attente ») ; troisième façon de dater une publication : « Après la
  dernière programmation + N h ».

**Styles et agencement**

- Éditeur d'agencement visuel pour le format letterbox (classique), sur le
  modèle de celui du format stream `split` : zones réglables par
  glisser/redimensionner ou valeurs numériques (vidéo nette, titre d'écran,
  bande des sous-titres, pseudo de chaîne), avec retour au standard du
  dépôt par un bouton.

**Journal**

- Journal global de toutes les actions, tous processus confondus (`serve`,
  `worker`, `run`, CLI) : un fichier par jour sous `logs/` (horodatage
  Europe/Paris), purgé automatiquement au-delà de 2 jours, écran « Journal »
  dans la console (menu Configuration). Chaque requête web et chaque action
  qui modifie des données (comptes, publications, styles...) y est
  consignée, mots de passe et jetons masqués.

**Moments**

- Grille de notation (`rubric.toml`) : plancher `min_moments_cap` (3 par
  défaut) sous le plafond horaire, pour qu'une courte vidéo avec plusieurs
  bons moments n'en garde pas qu'un seul (SPEC-4063 règle 4).

**Transcription**

- Chaque tranche de correction réussie est mise en cache séparément : un
  nouveau passage de l'étape `transcribe` ne redemande que les tranches
  manquantes au lieu de tout refaire si une seule bloque ; délai par tranche
  réglable (`[transcribe] fix_timeout_s`) ; une tranche en échec transitoire
  est relancée une fois seule avant de faire échouer toute l'étape.

### Modifié

**Styles et agencement**

- Un style (preset de chaîne) n'a plus de compte de publication ni de
  créneaux associés : le compte se choisit par publication, et les créneaux
  réguliers se règlent désormais sur le compte lui-même, dans l'écran
  Comptes (SPEC-6076 R2). Un preset existant qui avait encore un
  compte et des créneaux est migré automatiquement (créneaux reportés sur
  ce compte s'il n'en a pas déjà, avertissement journalisé une fois).

**Comptes**

- Écran Comptes : créneaux réguliers de publication réglables par compte
  (ajout/suppression), repris par le worker et affichés dans le calendrier
  de Publication.

**Worker et fiabilité**

- Un seul compte piloté à la fois, tous services confondus (TikTok et
  YouTube), par un verrou de pilotage inter-processus ; la prise en main
  d'une publication programmée est atomique (vérifiée sous verrou avant de
  piloter le navigateur) ; une série dont les parties sont liées n'avance
  plus à la partie N tant que la partie N-1 n'est pas publiée.
- L'annulation d'une vidéo depuis la console passe par la file de traitement
  (le serveur web ne crée plus de `Worker` lui-même) : plus d'erreur 500 à
  l'annulation, et aucune publication en cours n'est mise en échec par un
  arrêt du serveur.

### Corrigé

- **YouTube** : l'envoi d'une vidéo s'ouvre désormais par « Créer » ->
  « Importer des vidéos » ; l'ancienne URL directe d'envoi redirigeait
  silencieusement vers le tableau de bord et faisait échouer la publication.
- **Publication, comptes, styles** (revue de code) : attribuer un style à
  une vidéo qui n'en avait pas ne fait plus republier un clip déjà publié ni
  perdre ses publications antérieures ; l'approbation groupée est
  réellement tout ou rien (tous les clips validés avant toute écriture) ;
  suppression d'un style avec des publications en cours refusée (liste des
  publications concernées) ; réglages de publication (visibilité,
  commentaires...) non perdus à l'approbation ; accès concurrent à
  `accounts.json` protégé par un verrou inter-processus ; plafonds
  quotidiens et écart minimal calculés dans le fuseau du compte ; publier un
  clip d'une vidéo sans style accepté dès que le compte est choisi.
- **Worker, pipeline, transcription** (revue de code) : une erreur sur une
  vidéo ou sur un fichier de file d'attente illisible n'arrête plus la
  boucle du worker (journalisée, vidéo suivante traitée) ; le mode choisi
  pour un style est bien transmis au sous-processus de traitement ; les
  décisions de revue humaine sont prises en compte après la génération des
  sous-titres (captions) et non avant ; `retry_delays` vide ne bloque plus
  un re-essai ; une correction identique à la précédente n'est plus comptée
  comme un refus ; une ponctuation déjà présente n'est plus doublée.
- **Publication** : une entrée déjà publiée, en cours de pilotage ou
  programmée ne peut plus être approuvée ni refusée par erreur (y compris
  une partie sœur d'une série) ; une publication programmée ou déjà publiée
  via Clipper n'est plus annulable par erreur ; une partie ne s'approuve que
  si la précédente est publiée ; les créneaux déjà pris par un compte
  comptent pour tous les styles confondus (plus de double réservation d'un
  même instant) ; l'annulation d'une série en échec partiel liste
  désormais les publications déjà prises en charge par le worker au lieu
  d'échouer en silence.
- **Journal** : le handler du journal global n'est plus fermé par la
  reconfiguration du logging d'uvicorn (plus jamais d'erreur 500 une fois le
  serveur monté).
- **Console** : aperçu d'une série relancé automatiquement à chaque saisie
  (le bouton « Valider » ne reste plus grisé à tort, le nombre annoncé reste
  à jour) ; résumé des dates refusées affiché dans l'aperçu d'une série ;
  service (TikTok ou YouTube) affiché dans le choix du compte de l'écran
  Clips.

### Retiré

- Clés `[channel] tiktok_account` et `[channel] slots` d'un preset de style :
  migrées automatiquement vers le compte concerné puis retirées (voir
  « À savoir pour migrer » ci-dessous). Un style sans publication associée
  jusqu'ici continue de fonctionner, sans ces clés.

### À savoir pour migrer

- Un preset de style (`presets/<nom>.toml`) qui avait encore `tiktok_account`
  et `slots` dans sa table `[channel]` est migré tout seul au prochain
  chargement : ses créneaux passent sur ce compte TikTok (sauf si le compte
  a déjà des créneaux, auquel cas il n'est pas écrasé) et les deux clés sont
  retirées du preset à la prochaine sauvegarde. Règle les créneaux de
  publication depuis l'écran Comptes désormais, pas depuis l'écran Styles.
- Nouveau dossier `logs/` (journal global, un fichier par jour) : ignoré par
  git, se purge tout seul au-delà de 2 jours, rien à faire.

## [0.3.0] - 2026-10-03

Pré-version « prête pour l'usage réel » : corrections et réglages issus du
premier usage de la 0.2.0, sans grosse nouveauté. Attention : la clé
`[parts] rubric_path` est retirée. Notes détaillées et marche à suivre pour
migrer : [`docs/releases/v0.3.0.md`](docs/releases/v0.3.0.md).

### Ajouté

- Lanceur `Clipper.bat` à la racine : démarre `clipper serve` s'il ne tourne
  pas déjà puis ouvre `http://127.0.0.1:8000`. `tools/creer-raccourci.ps1`
  crée `Clipper.lnk` avec le logo (`tools/clipper.ico`) ; décrits dans la
  section de lancement du README.
- Console, radar du jury : un moment retenu par le jury mais écarté au
  découpage affiche « retenu par le jury, écarté au découpage : raison ».
- README refait avec captures et animations de la console, et image d'aperçu
  social du dépôt (`docs/assets/social-preview.png`).

### Modifié

- **Statistiques TikTok** (SPEC-47e2, remplace SPEC-86fe) : le relevé n'a lieu
  que lorsque tu te sers de Clipper (ouverture de l'écran Statistiques si le
  dernier relevé date de plus de `[tiktok] stats_stale_min` minutes, 60 par
  défaut ; passage d'une publication ; bouton « Relever maintenant »), avec un
  seul relevé à la fois par compte. Le relevé périodique du worker est coupé
  par défaut (`[tiktok] stats_interval_h = 0`).
- La liste Publications de TikTok Studio est lue en entier (défilement, plus
  de 50 posts, avec une limite de sécurité).
- Un compte neuf sans post est reconnu (liste vide) : plus d'attente de 30 s
  ni de publication arrêtée. Les posts supprimés sur TikTok disparaissent de
  l'affichage ; l'historique des relevés est conservé.
- Console : Publication et Statistiques se filtrent par compte TikTok (« Tous
  les comptes ») au lieu de la chaîne.
- « Chaîne » devient « Style » dans la console et la documentation (les
  identifiants internes ne changent pas : `presets/`, `[channel]`,
  `/api/channels`).
- Console, Publication : les cartes du calendrier tiennent sur deux lignes et
  le titre complet s'affiche en info-bulle.

### Corrigé

- L'étape `parts` découpe avec la grille réellement utilisée par `moments`
  (`rubric.path` de `moments.json`). Avant, une chaîne en grille gaming
  (30 à 90 s) voyait des moments valides rejetés au découpage (grille
  standard, 60 à 120 s) après avoir pris une place du plafond par heure.
- Un post publié via Clipper sur un compte non lié à une chaîne n'apparaissait
  pas dans Publication.
- `clipper.__version__` valait encore `0.1.0` ; il suit désormais la version
  du paquet.

### Retiré

- La clé `[parts] rubric_path` : la grille de découpage est celle de l'étape
  `moments`. Si elle est encore dans `config.toml`, `parts` s'arrête avec une
  erreur claire ; supprime la clé (règle `[moments] rubric_path` à la place).

## [0.2.0] - 2026-10-02

Console web v2, publication et statistiques TikTok par navigateur, comptes
rangés dans le coffre de l'OS, grille gaming et confiance du jury. Notes
détaillées et marche à suivre pour migrer :
[`docs/releases/v0.2.0.md`](docs/releases/v0.2.0.md).

### Ajouté

**Console web**

- Console de gestion web v2 (`python -m clipper serve`, `clipper/web/`) en neuf
  écrans : Tableau de bord, Vidéos, Revue, Clips, Publication, Chaînes,
  Statistiques, Comptes et Réglages. Page statique sans étape de build,
  temps réel par SSE avec repli sur interrogation toutes les 5 s,
  utilisable sur téléphone, polices embarquées.
- Écran Vidéos : liste filtrable, ajout par URL avec choix de la chaîne, fiche
  avec la frise des 12 étapes (durées, progression, journal suivi en direct),
  « relancer depuis cette étape », annulation.
- Écran Revue : lecteur calé sur le moment, timeline aux bornes glissables,
  justification du jury, raccourcis `A` / `R` / `J` / `K` / espace, « Annuler »
  pendant 5 s ; le rendu n'est proposé que lorsque chaque moment a une décision.
- Écran Clips : galerie 9:16, fiche du clip (QA, partie N/M), édition de la
  description, des hashtags et du titre d'écran (avec nouveau rendu),
  approuver / refuser, télécharger, copier.
- Diagramme en étoile du jury par moment dans la fiche vidéo (étape Moments).
- Accès distant par jeton : `serve --host` hors `127.0.0.1` exige `[web] token`
  (refus de démarrer sinon) ; page de saisie du jeton, cookie, 401 sur `/api`
  et `/media`. Réseau local seulement, pas de TLS.
- Notifications du navigateur (permission demandée depuis un réglage local,
  jamais au chargement) sur `done`, `failed`, `awaiting_review`, `queued`.
- Sortie console détaillée : `-v` (progression par étape, une ligne par appel
  LLM, résumé final) et `-vv` (détail) ; relance ciblée d'étapes par
  `--force-step` ; journal `workspace/<video_id>/events.jsonl`.

**Chaînes**

- Une chaîne = un preset `presets/<nom>.toml` fusionné clé par clé sur
  `config.toml` (table `[channel]` : nom, source, surveillance, mode, créneaux,
  fuseau, compte TikTok, logo), utilisable aussi par `--config`. `presets/`
  est ignoré par git.
- Écran Chaînes : création et édition par formulaire (valeurs héritées
  visibles, erreurs de validation sous le champ), éditeur d'agencement visuel
  (zones webcam, jeu, badge et sous-titres sur une image clé), aperçu du style
  des sous-titres, choix de la grille de notation.
- Surveillance des VOD d'une chaîne (`[channel] watch`) : mise en file
  automatique en mode `auto`, VOD « à confirmer » sur le tableau de bord en
  mode `review`.
- Agencement stream `split` (`[reframe] stream_variant = "split"`, SPEC-76dc) :
  webcam en haut, jeu en bas, badge de chaîne optionnel (logo et nom) à leur
  jonction, titre d'écran désactivable (`[render] title_enabled`), style des
  sous-titres réglable (police, couleurs, contour, ombre, position).

**Comptes et coffre**

- Écran Comptes : carnet local des comptes (libellé, plateforme, identifiant,
  notes), boutons Copier, générateur de mot de passe (12 à 64 caractères).
  Les mots de passe ne vont que dans le coffre de l'OS (`keyring`), jamais
  dans un fichier.
- Profil de navigateur par compte (`state/browser/<compte>/`), connexion
  manuelle par `python -m clipper browser login <compte>` ou depuis l'écran
  Comptes, état de connexion TikTok vérifié localement (jamais connecté,
  connecté, session expirée).
- Case « prêt à publier » calculée automatiquement : cochée quand la connexion
  est vérifiée et qu'aucun arrêt (captcha, vérification) n'est en attente.

**Publication TikTok**

- Publication par pilotage d'un vrai Chrome (Playwright, `clipper/tiktok.py`,
  `[tiktok]`) : immédiate ou programmée côté TikTok, avec lien du post
  récupéré, arrêt sûr sur captcha ou page inattendue (capture d'écran, bouton
  Réessayer), plafond de posts par jour et écart minimal par compte, délais
  aléatoires entre actions. Repères de la page dans
  `clipper/assets/tiktok_selectors.toml`.
- Écran Publication : formulaire « Nouvelle publication » (clip, compte,
  maintenant ou programmé, légende, visibilité, commentaires, réutilisation,
  étiquette IA), calendrier hebdomadaire des créneaux, statut de chaque
  entrée, « Déclarer publié (hors Clipper) ». Une vidéo sans chaîne reste
  publiable.
- Cookies YouTube lus depuis un profil de navigateur (`[download]
  cookies_profile`) pour les vidéos qui exigent une connexion.
- Test réel optionnel, publication privée sur un compte de test :
  `CLIPPER_TIKTOK_REAL=1 pytest tests/integration/test_tiktok_real.py`.
- Étude de cadence de publication : `docs/tiktok-cadence.md`.

**Statistiques TikTok**

- Écran Statistiques par compte, alimenté par TikTok Studio : vue d'ensemble
  (7 / 28 / 60 jours, évolution, courbe par jour), liste des vidéos triable,
  fiche de statistiques par vidéo, y compris les posts publiés hors Clipper.
- Relevé à la demande et périodique par le worker (`[tiktok] stats_interval_h`),
  historique horodaté sous `state/stats/tiktok/<compte>/` jamais écrasé ; une
  valeur que TikTok n'affiche pas encore reste vide, jamais 0.

**Jury et grille gaming**

- Confiance de chaque juge (0 à 100) par candidat : un débat s'ouvre si une
  confiance passe sous `[jury] debate_confidence_below` (40), la médiane est
  pondérée par la confiance (plancher `min_confidence_weight`, 0,2).
- Grille gaming embarquée : `[moments] rubric_path = "builtin:gaming"`, choisie
  par chaîne (émotion pondérée en tête, clips de 30 à 90 s).

**Worker et file**

- Worker (`python -m clipper worker`, lancé par `serve`) : file
  `state/queue.json`, une vidéo à la fois dans un processus enfant, annulation,
  reprise au redémarrage, voyant « worker actif » dans la console ; il pilote
  aussi la surveillance des VOD, la publication et le relevé des statistiques.
- Dossier `state/` : tout l'état hors vidéo en fichiers JSON sous verrou
  inter-processus (file, surveillance, publication, comptes, statistiques).

**Documentation et outils**

- `docs/GUIDE.md` : section « Console de gestion » ; `docs/versions.md` : plan
  de versions et critères de la 1.0.0 ; `docs/benchmarks/whisper-modeles.md` :
  banc `small` contre `large-v3-turbo`.
- `tools/setup.ps1` vérifie aussi `playwright` et Google Chrome.
- `clipper.gpu.vram_used_mb()` (mesure par `nvidia-smi`) affichée sur le
  tableau de bord.

### Modifié

- Statistiques TikTok : les onglets Spectateurs et Engagement ne sont ouverts qu'à
  partir de 100 vues (`[tiktok] stats_audience_min_views`) ; un relevé détaillé
  passe de 77 s à 13 s pour un post récent.
- **Format stream** (SPEC-8257) : le choix stream ou letterbox d'un clip se fait
  sur la présence de la webcam elle-même (contenu non noir, bords retrouvés,
  non figé) et non plus sur la détection du visage ; la localisation de la
  facecam, une fois par vidéo, garde le visage comme indice avec un seuil plus
  bas (`facecam_localize_min_share`, 0,1).
- **Titre d'écran sobre** (SPEC-6a86) : sans emoji ni superlatif par défaut
  (`[captions] screen_title_allow_emoji`, `screen_title_forbidden_words`) ;
  la légende et l'accroche suivent la même sobriété (`caption_allow_emoji`).
- **Sous-titres** : plus rien à l'écran pendant les silences.
- **Jury** : chaque juge doit renvoyer sa confiance par candidat ; une réponse
  sans confiance est invalide, comme tout champ manquant.
- **Détection de scènes** : seules les plages de parole (marge
  `speech_margin_seconds`) sont décodées ; elle exige désormais la
  transcription faite.
- **Rythme de publication** : défauts d'un compte neuf (`max_posts_per_day = 1`,
  `min_gap_minutes = 480`) ; délais entre actions de 0,3 à 1 s ; vérification
  de contenu de TikTok coupée par défaut (`[tiktok] content_check = "off"`,
  `"wait"` pour l'attendre).
- **Transcription** : modèle `small` conservé par défaut ; `large-v3-turbo`
  (pic VRAM 3,29 Go) reste une option au cas par cas.
- **`--config`** : le fichier passé est désormais un preset fusionné clé par clé
  sur `config.toml` (qui doit exister) au lieu de le remplacer ; un preset de
  la 0.1.0 continue de fonctionner.
- **Configuration** : `config.toml` s'écrit depuis la console, validé avant
  remplacement atomique ; nouvelles sections `[web]`, `[worker]`, `[watch]`,
  `[publish]`, `[channel]`, `[browser]`, `[accounts]`, `[tiktok]`.
- **Dépendances** : `playwright`, `keyring`, `tomli-w`, et `tzdata` sous
  Windows ; `pytest-xdist` pour les tests (`-n 6` par défaut).
- Le dépôt suit le versionnage sémantique (`docs/versions.md`).

### Corrigé

- Sous-titres : un jeton collé par apostrophe ou ponctuation isolée n'est plus
  fusionné avec le mot précédent à travers un vrai silence.
- Titre d'écran : le schéma JSON envoyé au LLM contredisait encore la règle
  « sans emoji ».
- Worker : `--config` placé avant la sous-commande est pris en compte, et un
  processus enfant qui meurt n'efface plus la vidéo en silence.
- Publication TikTok, corrigé après les premiers tests réels : fenêtres
  connues fermées, menus déroulants ne sont plus pris pour des fenêtres,
  vidéo privée (« Maintenant » grisé), cases de réglage cochées par clic,
  suggestions de hashtags refermées, case désactivée par TikTok journalisée
  et laissée, succès prouvé par la page Publications, privé et programmé
  refusés avant d'ouvrir le navigateur.
- Statistiques TikTok : repères réels de la page Publications (lignes des
  posts, vues, likes, commentaires, visibilité, date) et du menu des périodes
  de TikTok Studio ; date « 2 oct., 12:30 » sans année lue avec l'année du
  relevé (un post récent est bien relu en détail).
- Console, plusieurs séries de corrections : miniatures des clips et des
  vidéos, erreurs affichées en clair (plus de `[object Object]`), compteurs,
  voyant du worker, tri des vidéos, cache des fichiers statiques, échecs
  actionnables, marges et libellés.

### Sécurité

- Accès distant refusé sans jeton, 401 sur `/api` et `/media` ; le jeton ne
  se modifie pas depuis l'interface, seulement dans `config.toml`.
- Mots de passe des comptes uniquement dans le coffre de l'OS : erreur
  explicite plutôt que repli vers un fichier si aucun coffre sûr n'est
  disponible ; jamais renvoyés par la liste, ni écrits dans un journal.
- Routes `/api/accounts*` accessibles depuis le PC seulement (adresse de
  bouclage et en-tête `Host` vérifiés, même avec un jeton valide).
- Clipper ne saisit jamais ton identifiant ni ton mot de passe TikTok : la
  connexion se fait à la main dans un Chrome normal ; captcha ou vérification
  = arrêt immédiat, jamais de contournement.
- Seuls les cookies YouTube et Google d'un profil sont exportés vers
  `cookies.txt` ; `state/` et `presets/` sont ignorés par git.

### Retiré

- Aucune commande, route ni réglage de la 0.1.0 n'est retiré.
- Ne s'appliquent plus : « aucune publication automatique sur TikTok » et
  « surveillance d'une chaîne Twitch pas encore couverte » (limites de la
  0.1.0).

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

[Non publié]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ZeDKouill3/TiktokClipper/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ZeDKouill3/TiktokClipper/releases/tag/v0.1.0
