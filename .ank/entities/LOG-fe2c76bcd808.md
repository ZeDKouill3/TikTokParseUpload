---
id: LOG-fe2c76bcd808
type: log
title: "Clauses SPEC-6a86 (screen_title) decoupees pour TDD, dans l'ordre d'implementation :"
created: 2026-09-30T12:23:28Z
author: w-ab03e090436c
scope:
  - clipper/captions.py
  - clipper/qa.py
  - tests/test_captions.py
  - tests/test_qa.py
  - docs/GUIDE.md
  - config.example.toml
  - clipper/assets/config.example.toml
about: TASK-ab03e090436c
seq: 2
schema: 4
version: 1
---


1. CONFIG_DEFAULTS[captions] : screen_title_allow_emoji=False (nouveau).
2. CONFIG_DEFAULTS[captions] : screen_title_forbidden_words=[pur,total,explose,choc,incroyable,fou,dingue,glacant,assourdissant,devoile] (nouveau).
3. Validation emoji : par defaut (allow_emoji=False), tout emoji dans screen_title => SchemaError explicite (pas de repli silencieux).
4. Validation emoji : allow_emoji=True => au plus un emoji simple accepte (0 ou 1), ZWJ/drapeau toujours refuses.
5. Validation mots interdits : un mot de la liste (insensible casse/accents, mot entier) => SchemaError explicite.
6. Prompt captions reecrit : ton sobre, cite si possible une phrase reellement prononcee ou fait concret, mentionne l'interdiction emoji par defaut + mots interdits.
7. Tests FakeBackend : prompt construit (regles mentionnees), refus emoji (defaut), refus superlatif, option emoji (accepte avec allow_emoji=True, toujours <=1 + ZWJ/drapeau refuses).
8. Fixtures existantes de test_captions.py utilisant emoji/mot interdit comme valeur generique (hors du sujet emoji/mots) mises a jour vers un screen_title sobre par defaut.
9. Collateral hors scope strict mais necessaire : tests/test_pipeline.py:222 fixture "GTA 6 confirme \U0001F525" casse sous le nouveau defaut (aucun repli, FakeBackend statique ne peut pas reparer) -> un seul mot modifie (emoji retire) pour garder la suite verte ; aucune autre ligne de ce fichier touchee.
10. config.example.toml + clipper/assets/config.example.toml : documentation des nouveaux reglages, restent identiques (test d'egalite).
11. docs/GUIDE.md section [captions] : mention des nouveaux reglages.
12. Controle reel (4 appels claude -p max) sur les 4 moments de workspace/v2887271276, copie dans research/madajel/titres/, titres avant/apres logges.
