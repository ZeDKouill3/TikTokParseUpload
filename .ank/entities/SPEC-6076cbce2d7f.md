---
id: SPEC-6076cbce2d7f
type: spec
slug: tiktok-par-navigateur-v2-aucun-compte-dans-un-st
title: "TikTok par navigateur v2 : aucun compte dans un style, compte choisi par publication, créneaux sur le compte"
created: 2026-10-03T10:01:15Z
author: nicoc@zedk_ordi
status: proposed
scope:
  - clipper/browser.py
  - clipper/tiktok.py
  - clipper/publish.py
  - clipper/worker.py
  - clipper/download.py
  - clipper/channel.py
  - clipper/accounts.py
  - clipper/web/**
  - pyproject.toml
supersedes: SPEC-922573c1e68f
schema: 4
version: 1
---

## Objet
Remplace SPEC-9225 (décision utilisateur du 2026-10-03) : un style n'a plus de compte associé, chaque publication choisit son compte et les créneaux réguliers vont sur le compte (R2) ; R7 renvoie à SPEC-47e2 pour le déclenchement des relevés. Le reste est repris à l'identique.

## Règles
R1. Profils. clipper.browser gère un profil Playwright persistant par compte dans state/browser/<compte>/ (state/ ignoré par git ; un test vérifie que .gitignore couvre ce chemin). Un compte de l'écran Comptes (SPEC-6fa4) peut être relié à un profil. « Se connecter » ouvre le navigateur visible sur ce profil et la page de connexion ; l'utilisateur se connecte à la main ; aucun identifiant ni mot de passe n'est jamais saisi par le programme. Navigateur : vrai Chrome (channel chrome) si présent, sinon erreur explicite (aucun repli silencieux).
R2. Aucun compte dans un style. Un style (preset presets/<nom>.toml, anciennement « chaîne ») ne porte plus de compte de publication : la clé [channel] tiktok_account est retirée (présente dans un preset = ignorée avec un avertissement journalisé une fois, puis retirée à la prochaine sauvegarde du style ; jamais utilisée). Chaque publication désigne son compte, choisi dans l'écran Publication (SPEC-1ed3) ; une publication sans compte est un échec explicite. Les créneaux de publication réguliers (anciennement [channel] slots) appartiennent au compte, pas au style : réglés dans l'écran Comptes ; les créneaux d'un preset existant sont repris une fois sur le compte qui y était relié (migration automatique et journalisée), puis retirés du preset. Le formulaire d'un style n'affiche plus ni compte associé ni créneaux.
R3. Publication. Deux modes par publication : « immédiat » (publié maintenant) et « programmé » (programmation côté TikTok à la date du créneau, pour publier PC éteint ; refus explicite si la date dépasse la limite de programmation de TikTok, réglable). Le worker prend les entrées dues de la file de publication (immédiat : créneau atteint ; programmé : dès que la date est dans la fenêtre de programmation), une à la fois, un seul compte piloté à la fois. Contenu : le mp4 et la légende + hashtags du sidecar (SPEC-6a47). Succès : mark_published avec l'URL ou l'id du post TikTok, enregistrés dans l'entrée et le sidecar.
R4. Arrêt sûr. Captcha, vérification, connexion expirée, élément attendu absent après délai, page inattendue : arrêt immédiat, entrée remise en attente (statut failed avec raison explicite et réessayable), capture d'écran sous state/browser/<compte>/captures/, événement de notification vers la console. Jamais de résolution ou contournement de captcha, jamais de clic de repli au hasard.
R5. Sélecteurs. Tous les sélecteurs et URL TikTok dans un seul fichier de données versionné (clipper/assets/tiktok_selectors.toml) ; un changement de page TikTok se corrige là sans toucher la logique.
R6. Rythme et plafonds. Délais aléatoires bornés entre actions ([tiktok] min/max_action_delay_s) ; [tiktok] max_posts_per_day (défaut 3) et min_gap_minutes (défaut 120) par compte ; un dépassement reporte la publication au prochain créneau libre, explicitement journalisé. Les défauts seront revus par une étude dédiée.
R7. Statistiques. fetch_stats(compte) relève par post publié : vues, likes, commentaires, partages et, si TikTok Studio les affiche, durée moyenne de visionnage et part vue en entier ; écrit state/stats/tiktok/<compte>.json (horodaté, écriture atomique) ; l'écran Statistiques les affiche à la place des colonnes « aucune mesure importée » (l'import CSV reste possible). Déclenchement du relevé : SPEC-47e2 R4 (seulement à l'usage ; relevé périodique du worker coupé par défaut, stats_interval_h = 0).
R8. Cookies YouTube. clipper.browser exporte les cookies d'un profil désigné ([download] cookies_profile) vers un fichier cookies.txt lu par le téléchargement ; remplace cookies_from_browser = firefox quand il est réglé.
R9. Tests. Aucun test par défaut ne lance un navigateur, ni n'accède au réseau ou à TikTok : backend browser testé avec une fausse page (objet simulé) qui rejoue les cas succès, captcha, élément absent, connexion expirée, plafond atteint. Un test réel optionnel (skipif, CLIPPER_TIKTOK_REAL=1) publie en mode brouillon/privé sur un compte de test.
