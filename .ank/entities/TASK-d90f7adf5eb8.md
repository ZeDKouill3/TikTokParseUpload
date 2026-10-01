---
id: TASK-d90f7adf5eb8
type: task
slug: tiktok-rep-res-r-els-de-tiktok-studio-fen-tres-c
title: "TikTok : repères réels de TikTok Studio, fenêtres connues, programmation par les sélecteurs date/heure, connexion par un Chrome normal"
created: 2026-10-01T15:52:09Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/assets/tiktok_selectors.toml
  - clipper/tiktok.py
  - clipper/browser.py
  - tests/test_tiktok.py
  - tests/test_browser.py
  - README.md
blocked_by: [TASK-693006b5b96e]
done_criteria: |
  Tests de régression d'abord rouges, fausse page Playwright, aucun navigateur réel ni réseau : (1) clipper/assets/tiktok_selectors.toml reprend les repères réels du corps (fin d'envoi, légende, Afficher plus, visibilité par id d'option avec le texte en secours, Maintenant/Programmer par libellé, champs heure/date, calendrier, sélecteur d'heure, bouton final unique post_video_button, abandon) ; l'en-tête dit ce qui est vérifié en réel et ce qui ne l'est pas (confirmation après publication) ; (2) la légende est vidée puis tapée caractère par caractère ; (3) la programmation règle l'heure et la date par les sélecteurs (navigation de mois par les flèches jusqu'au mois cible, jour, heure, minutes ; minutes arrondies au pas proposé par TikTok, journalisé) ; (4) avant de cliquer le bouton final, attente du résultat de la vérification de contenu : « Aucun problème constaté » -> on continue ; problème signalé ou délai [tiktok] content_check_timeout_s (défaut 900) dépassé -> échec explicite R4 ; (5) fenêtres connues ([popups] dans le toml : texte de la fenêtre -> bouton à cliquer, ici Annuler pour les vérifications automatiques et J'ai compris pour les nouveautés) fermées et journalisées ; toute autre fenêtre modale = arrêt R4 ; (6) clipper browser login ouvre un Chrome normal en sous-processus sur le profil (jamais Playwright pour la connexion), attend sa fermeture, Chrome absent = erreur explicite ; README à jour ; (7) un test par cas : envoi OK immédiat, programmé (changement de mois), vérification en cours puis OK, vérification en échec, fenêtre connue, fenêtre inconnue ; (8) tests existants verts. python -m pytest -q tests/test_tiktok.py tests/test_browser.py vert.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---

Relevé réel de TikTok Studio (FR, 2026-10-01, page https://www.tiktok.com/tiktokstudio/upload?from=webapp, un seul cadre), complété par un ancien script de l'utilisateur.
CONNEXION : Chrome lancé par Playwright (launch_persistent_context) est refusé à la connexion TikTok (faux message « Nombre maximal de tentatives atteint »). Un Chrome normal lancé en sous-processus (chrome.exe --user-data-dir=state/browser/<compte> --no-first-run <url>) se connecte, et Playwright réutilise ensuite la session du profil sans problème.
PAGE D'ENVOI : input fichier input[type='file'] (OK) ; zone [data-e2e='select_video_container'] / button[data-e2e='select_video_button'] ; envoi terminé = [data-e2e='upload_status_container'] contenant « Importé » (l'actuel upload_status_success est FAUX) ; légende = [data-e2e='caption_container'] [contenteditable='true'] (éditeur Draft.js .public-DraftEditor-content, pré-rempli avec le nom du fichier : clic, Ctrl+A, Retour arrière, puis keyboard.type caractère par caractère, pas fill) ; paramètres repliés : clic sur [data-e2e='advanced_settings_container'] (« Afficher plus ») si besoin ; visibilité = [data-e2e='video_visibility_container'] button[role='combobox'] puis div[role='option'].Select__item d'id option-"0" (Tout le monde), option-"2" (Ami(e)s), option-"1" (Toi uniquement = privé) (l'actuel privacy_container est FAUX) ; quand publier = [data-e2e='schedule_container'] avec 2 radios Maintenant / Programmer (ids aléatoires : viser par libellé) (l'actuel schedule_radio est FAUX) ; après Programmer : 2 input.TUXTextInputCore-input dans schedule_container, heure (valeur contenant « : ») puis date (AAAA-MM-JJ) ; date via calendrier span.month-title / span.year-title, flèches span.arrow (nth 0 précédent, nth 1 suivant), jour span.day.valid au texte exact ; heure via span.tiktok-timepicker-option-text.tiktok-timepicker-left (heures) / tiktok-timepicker-right (minutes) au texte exact, fermeture par clic hors du champ ; bouton final button[data-e2e='post_video_button'] dont le texte est « Publier » ou « Programmer » (pas de schedule_video_button) ; abandon button[data-e2e='discard_post_button'].
VÉRIFICATION DE CONTENU : bloc « Vérification de contenu simple » : « Vérification en cours… environ 10 minutes » puis « Aucun problème constaté » (vert) ou un problème.
FENÊTRES SURGISSANTES vues au premier envoi : « Activer les vérifications automatiques du contenu ? » (boutons Annuler / Activer) ; bulle « Nouvelles fonctionnalités d'édition ajoutées » (bouton J'ai compris).
NON VU : fenêtre de confirmation après publication et lien du post.
