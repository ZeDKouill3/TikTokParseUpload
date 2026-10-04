# Changelog

Toutes les évolutions notables de ce dépôt sont consignées ici. Format inspiré
de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Depuis la 0.2.0,
le dépôt suit le [versionnage sémantique](https://semver.org/lang/fr/) :
`MAJEUR.MINEUR.CORRECTIF`, avec le plan de versions et les critères de la 1.0.0
dans [`docs/versions.md`](docs/versions.md). Tant que la version reste en `0.x`,
la configuration, les écrans et les fichiers d'état peuvent encore changer.
Notes de version détaillées : [`docs/releases/`](docs/releases/).

## [Non publié]

### Ajouté

- **Installeur portable Windows** (SPEC-38f7761891f6, ADR-e1dac9ba2284) :
  un zip d'amorçage léger (`Clipper-portable-<version>.zip`, < 150 Mo,
  `uv.exe` + wheel + scripts, jamais de Python ni de site-packages dedans)
  construit par `tools/build_portable.py` et attaché à chaque Release.
  `Installer.bat` installe Python 3.11, l'environnement, ffmpeg (version
  figée) et `claude` dans un dossier programme jetable
  (`%LOCALAPPDATA%\Clipper\app` par défaut), prépare un dossier de données
  séparé (`Documents\Clipper` par défaut), détecte automatiquement le GPU
  (CUDA si `nvidia-smi` répond, CPU sinon), précharge les modèles et termine
  par un `clipper doctor`. `Desinstaller.bat` supprime le dossier programme
  et conserve les données par défaut (`--donnees` pour tout supprimer).
  Mise à jour par simple relance d'un zip plus récent, refus explicite d'une
  version plus ancienne. Documentation complète du parcours dans
  [`docs/INSTALLATION.md`](docs/INSTALLATION.md), nouvelle section
  « Installation sans outils de développement » dans le README.

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

[Non publié]: https://github.com/ZeDKouill3/TikTokParseUpload/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/ZeDKouill3/TikTokParseUpload/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ZeDKouill3/TikTokParseUpload/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ZeDKouill3/TikTokParseUpload/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ZeDKouill3/TikTokParseUpload/releases/tag/v0.1.0
