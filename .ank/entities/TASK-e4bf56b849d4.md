---
id: TASK-e4bf56b849d4
type: task
slug: tiktok-preuve-de-publication-lien-du-post-priv-n
title: "TikTok : preuve de publication, lien du post, privé non programmable, statistiques lues sur les vraies pages"
created: 2026-10-01T16:06:39Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/assets/tiktok_selectors.toml
  - clipper/tiktok.py
  - clipper/publish.py
  - tests/test_tiktok.py
  - tests/test_publish.py
blocked_by: [TASK-d90f7adf5eb8]
done_criteria: |
  Tests d'abord rouges, fausse page, aucun navigateur réel ni réseau : (1) une publication privée (visibilité Toi uniquement) en mode programmé est refusée explicitement avant toute ouverture de navigateur ; (2) succès de publication prouvé par la navigation vers /tiktokstudio/content (preuve principale) ou le message « Vidéo publiée » (secours) dans un délai réglable ; ni l'un ni l'autre = échec R4 avec capture, jamais un succès supposé ; (3) la fenêtre « Continuer à publier ? » est une fenêtre connue : clic « Annuler », attente de la fin de la vérification, nouvel essai, une fois ; (4) lien du post : sur /tiktokstudio/content, premier a[href*='/video/'] dont le texte correspond au début de la légende publiée ; l'URL complète et l'id (fin du href) sont enregistrés par mark_published ; introuvable = publication réussie mais lien manquant signalé explicitement (pas d'id inventé) ; (5) fetch_stats va directement sur /tiktokstudio/analytics/<id>?qa_enter_from=analytics et lit les cartes VideoMetricsCard par libellé : vues (entier), temps de lecture total et moyen (convertis en secondes depuis « 0h:00m:00s » / « 12s »), part vue en entier (pourcentage), nouveaux followers ; likes, commentaires depuis la ligne de la page Publications ; rétention et sources « en cours de traitement » = null explicite ; tous ces repères dans tiktok_selectors.toml (data-tt de préférence) ; (6) un test par cas : succès par navigation, succès par message, aucun signe, fenêtre Continuer à publier, lien trouvé, lien introuvable, métriques à zéro, métriques remplies, rétention en traitement ; (7) tests existants verts. python -m pytest -q tests/test_tiktok.py tests/test_publish.py vert.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/306456d65596@d21a008
    tree: scope/e1a560d30821
    criteria: 433529f0faf4
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Relevé réel 2026-10-01 (post privé de test publié par l'utilisateur, FR).
PRIVÉ : avec la visibilité « Toi uniquement », « Programmer » est grisé (« Les vidéos privées ne peuvent pas être programmées »).
CONFIRMATION : sans vérification de contenu en cours, après « Publier » : message « Vidéo publiée » puis l'URL passe à https://www.tiktok.com/tiktokstudio/content. Si on clique pendant la vérification : fenêtre « Continuer à publier ? » (« Nous sommes encore en train de vérifier… ») avec boutons « Annuler » / « Publier maintenant » (classes TUXButton).
PAGE PUBLICATIONS (/tiktokstudio/content) : tableau « Contenu (Créé le) | Politique de confidentialité | Vues | J'aime | Commentaires | Actions », le plus récent en haut ; lien de chaque post a[href*='/video/'] de forme /@<compte>/video/<id> dont le texte est la légende du post. Repères de composants data-tt plus stables que les classes css-xxxx.
ANALYSE D'UN POST : URL directe https://www.tiktok.com/tiktokstudio/analytics/<id>?qa_enter_from=analytics ; carte [data-tt='VideoOverviewPage_VideoInfoCard_FlexRow'] (légende, « Publié le JJ/MM/AAAA », 5 compteurs) ; métriques [data-tt='VideoOverviewPage_VideoMetricsCard_FlexItem'], texte « libellé | valeur » : « Vues de vidéo | 0 », « Temps de lecture total | 0h:00m:00s », « Temps de visionnage moyen | 0s », « A regardé toute la vidéo | 0% », « Nouveaux followers | 0 » ; « Taux de rétention » et sources de trafic : « en cours de traitement » (sources visibles à partir de 100 vues).
