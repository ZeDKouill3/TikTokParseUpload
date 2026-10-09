---
id: TASK-a2cd6af4e083
type: task
slug: moments-un-passage-d-action-prend-comme-parole-e
title: "Moments : un passage d'action prend comme parole et accroche les mots prononcés dans le passage, même si leur phrase déborde"
created: 2026-10-09T07:05:36Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/moments.py
  - tests/test_moments_action.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  research/reviews/nuit2-0910.md « Douteux » 1 (sonde cand2) : dans clipper/moments.py _action_candidate (~l.868-900), hook_text et speech (texte « Parole » donné au proposeur/jury) ne viennent que des phrases ENTIÈREMENT incluses dans le passage ; une phrase qui chevauche le passage (commencée avant, ou qui déborde après la fin) compte pour la règle « parole trop tard » mais pas pour le texte : un passage où l'on parle de +8,5 s à la fin est jugé « sans parole » et son accroche est la description de l'image. (1) Le texte de parole (speech) d'un candidat d'action est construit à partir des MOTS horodatés compris dans [start, end] de toutes les phrases qui chevauchent le passage (mots géants exclus selon action_word_max_chars) ; pour une phrase sans horodatage des mots, seule une phrase entièrement incluse fournit son texte (pas de découpe devinée). (2) hook_text : si une phrase entièrement incluse existe, règle actuelle inchangée (première phrase incluse, retrait des connecteurs de tête) ; sinon, s'il y a des mots retenus dans le passage, hook_text = ces mots depuis le premier mot retenu jusqu'à la fin de sa phrase ou la fin du passage (au plus la longueur maximale d'accroche déjà appliquée ailleurs dans moments.py s'il y en a une) ; s'il n'y a aucun mot retenu, règle SPEC-b0f3 R11 inchangée (accroche = description de l'image la plus intense). (3) Rien d'autre ne change : bornes, rejets (parole trop tard, connecteurs, SponsorBlock, durée), candidates = "transcript" octet pour octet identique (test témoin existant vert). (4) Tests CPU sans réseau (fixtures tests/test_moments_action.py) : passage 5-20 s avec une phrase 8,5-25 s horodatée -> speech non vide (mots 8,5-20 s seulement), hook_text = ces mots, pas la description d'image ; passage avec une phrase incluse -> hook inchangé ; passage sans aucun mot -> accroche = image ; tests existants verts. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
