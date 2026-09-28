---
id: SPEC-ef7cc8cfb025
type: spec
slug: grille-de-notation-des-moments-clips-60-120-s-s
title: Grille de notation des moments (clips 60-120 s, séries de parties qui se suivent)
created: 2026-09-28T20:08:17Z
author: nicoc@zedk_ordi
status: proposed
scope:
  - clipper/moments.py
  - clipper/parts.py
  - rubric.toml
references: [ADR-b1c17749b528]
supersedes: SPEC-53f3d22d6314
schema: 4
version: 1
---

## Objet
Comment un moment candidat d'une vidéo longue est noté, retenu et découpé en clips. La grille vit dans `rubric.toml` (modifiable sans toucher au code) ; ce document fixe sa forme et ses règles. Remplace SPEC-53f3 : décision utilisateur du 2026-09-28, clips de 60 à 120 s, longs passages découpés en parties qui se suivent.

## Critères (note 0-10 chacun, pondération dans rubric.toml)
| Critère | Question posée | Poids défaut |
|---|---|---|
| hook | La 1re phrase du clip arrête-t-elle le scroll (affirmation choc, question, surprise, conflit, révélation) ? | 3 |
| standalone | Compréhensible sans le reste de la vidéo ? | 3 |
| payoff | Arc complet, fin sur punchline/révélation ; en multi-parties, chaque partie finit sur un suspense ? | 2 |
| emotion | Rire, cri, réaction forte, débat vif ? | 2 |
| value | Info, leak, avis tranché, théorie, controverse ? | 2 |
| trend | Touche les mots-clés tendance de rubric.toml ? | 1 |

Score final 0-100 = moyenne pondérée x10, plus bonus signaux mesurés (plafonnés, poids dans rubric.toml) :
- recouvrement avec la courbe YouTube « most replayed » (si présente) ;
- pics d'énergie audio ;
- éléments visuels marquants (descriptions d'images).

## Règles
1. Un clip (ou la partie 1 d'une série) commence sur l'accroche, pas sur la mise en contexte ; il commence et finit en frontière de phrase (jamais au milieu d'un mot). Il ne commence jamais sur un connecteur qui suppose la phrase d'avant (donc, mais, du coup...) : ce connecteur n'est ni entendu ni sous-titré, aucune fraction de mot antérieure à la borne de début n'apparaît dans le clip.
2. Exclus d'office : segments SponsorBlock (sponsor, intro, outro, selfpromo), silences > 2 s en début/fin.
3. Durée : chaque clip dure de 60 à 120 s (bornes dans rubric.toml, marge de recalage comprise). Une histoire qui tient en 60-120 s = 1 clip unique, sans mention de partie. Un long passage fort (une affaire entière, typiquement 5 à 15 min) = une série de 2 à `max_parts` parties (défaut 12) de 60-120 s chacune, qui se suivent : chaque partie finit sur un suspense, et la partie k+1 reprend la fin de la partie k sur environ 3 s (entre 1 et 8 s), en commençant de préférence sur un début de phrase ; ce recouvrement est voulu et n'est pas un défaut.
4. Retenus : tous les moments (clips uniques ou passages) au-dessus de `min_score` (rubric.toml, défaut 60), sans plafond ; deux moments retenus ne se chevauchent pas (on garde le mieux noté). Seules les parties d'une même série se recouvrent (règle 3).
5. La sortie de l'étape liste pour chaque moment : start, end (secondes, précision 0,1 s), scores par critère, score final, justification courte, texte de l'accroche, découpage en parties le cas échéant.
6. Les décisions humaines journalisées (feedback) sont fournies au LLM comme exemples positifs/négatifs.
