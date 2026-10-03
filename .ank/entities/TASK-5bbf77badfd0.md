---
id: TASK-5bbf77badfd0
type: task
slug: publication-programmer-une-s-rie-n-clips-choisis
title: "Publication : programmer une série (N clips choisis automatiquement, un toutes les X h, aperçu puis validation ; SPEC-1ed3, SPEC-6076 R3/R6)"
created: 2026-10-03T11:13:47Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/publish.py
  - clipper/web/**
  - tests/test_publish.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  tests/test_publish.py et tests/test_web.py verts : dates début + k×X h en durée réelle (passage heure d'hiver 25/10/2026 couvert), N meilleurs clips par score hors publiés/en file/programmés, parties d'un clip ensemble et dans l'ordre, filtre style, refus explicites (clips insuffisants, hors fenêtre, plafonds du compte) sans décalage silencieux, création tout ou rien, endpoints aperçu + création ; node --check du JS modifié. Tests unitaires sans navigateur ni réseau.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

## Demande utilisateur (2026-10-03)
« un mode : une vidéo toutes les X h ; je sélectionne le nombre de vidéos et automatiquement ça publie programmé les vidéos, toutes les X heures. »

## Comportement attendu
Écran Publication : bouton « Programmer une série » (à côté de « Nouvelle publication ») qui ouvre un formulaire :
- compte (obligatoire, TikTok ou YouTube, comptes prêts seulement, comme le formulaire existant) ;
- style (filtre optionnel ; vide = tous) ;
- nombre de vidéos N (entier >= 1) ;
- intervalle X en heures (>= 1, pas de 0,5 accepté) ;
- début : date et heure en heure de Paris (Europe/Paris, jamais l'heure du PC), défaut = prochaine heure pleine + 1 h.

Choix automatique des clips : les N meilleurs clips (score du sidecar, décroissant) prêts à publier et pas déjà publiés, en file ou programmés, dans le style choisi. Un clip en plusieurs parties est pris en entier, parties dans l'ordre et à la suite, ou pas du tout.
Dates : début + k × X h, calculées en durée réelle (datetime aware, arithmétique en UTC) : un passage heure d'été/hiver (25 oct. 2026) ne décale pas l'intervalle.

Aperçu obligatoire avant validation : liste (vignette, titre, date Paris de chaque post). Puis « Valider » crée N publications en mode « programmé » par le même chemin de création que le formulaire unitaire (mêmes validations : schedule_min_minutes, schedule_max_days par service, compte prêt).

Aucun repli silencieux (ADR-ad2e) : refus explicite, affiché dans l'aperçu, si
- moins de N clips disponibles (« seulement K clips disponibles ») ;
- une date tombe hors de la fenêtre de programmation du service, ou sous le délai minimum ;
- la série viole les plafonds du compte ([tiktok] max_posts_per_day, min_gap_minutes ; équivalents YouTube s'ils existent) : indiquer quelles dates, ne jamais décaler une date en douce.
Validation tout ou rien : si une publication de la série échoue à la création, aucune n'est créée.

## Contraintes
Réglages nouveaux (défaut d'intervalle, etc.) dans CONFIG_DEFAULTS du module. Aucune logique de publication dans le JS au-delà de l'affichage (calcul des dates et choix des clips côté Python, endpoint d'aperçu + endpoint de création). UI en français, style de l'écran existant.

## Preuves (tests unitaires, sans navigateur ni réseau)
Calcul des dates (dont passage à l'heure d'hiver 25/10/2026), choix des clips (score, parties ensemble, exclusion des déjà publiés/en file, filtre style), chaque cas de refus, tout ou rien, endpoints web (aperçu + création), `node --check` du JS modifié.
