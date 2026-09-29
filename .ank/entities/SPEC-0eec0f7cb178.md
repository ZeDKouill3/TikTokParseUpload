---
id: SPEC-0eec0f7cb178
type: spec
slug: grille-de-notation-des-moments-v3-trend-0-plafon
title: Grille de notation des moments v3 (trend à 0, plafond souple par heure)
created: 2026-09-29T09:23:31Z
author: orch-main
status: proposed
scope:
  - clipper/moments.py
  - clipper/parts.py
  - rubric.toml
references: [ADR-b1c17749b528]
supersedes: SPEC-1557120ad84b
schema: 4
version: 1
---

## Objet
Comment un moment candidat d'une vidéo longue est noté, retenu et découpé en clips. La grille vit dans `rubric.toml` (modifiable sans toucher au code) ; ce document fixe sa forme et ses règles. Remplace SPEC-1557 (décision utilisateur du 2026-09-29) : critère trend à poids 0 par défaut, et plafond souple du nombre de moments par heure de vidéo. Le reste est inchangé (clips de 60 à 120 s, longs passages en parties qui se suivent).

## Critères (note 0-10 chacun, pondération dans rubric.toml)
| Critère | Question posée | Poids défaut |
|---|---|---|
| hook | La 1re phrase du clip arrête-t-elle le scroll (affirmation choc, question, surprise, conflit, révélation) ? | 3 |
| standalone | Compréhensible sans le reste de la vidéo ? | 3 |
| payoff | Arc complet, fin sur punchline/révélation ; en multi-parties, chaque partie finit sur un suspense ? | 2 |
| emotion | Rire, cri, réaction forte, débat vif ? | 2 |
| value | Info, leak, avis tranché, théorie, controverse ? | 2 |
| trend | Touche les mots-clés tendance de rubric.toml ? | 0 |

Score final 0-100 = moyenne pondérée x10, plus bonus signaux mesurés (plafonnés, poids dans rubric.toml) :
- recouvrement avec la courbe YouTube « most replayed » (si présente) ;
- pics d'énergie audio ;
- éléments visuels marquants (descriptions d'images).

Un critère de poids 0 est noté mais ne compte pas dans la moyenne. trend est à 0 par défaut : la liste globale de mots-clés ne correspond pas à des contenus aléatoires (note 0 sur 112 candidats sur 112 le 2026-09-29, soit 4 à 5 points perdus par tous) ; il reste dans la grille pour de futurs mots-clés propres à chaque vidéo.

## Règles
1. Un clip (ou la partie 1 d'une série) commence sur l'accroche, pas sur la mise en contexte ; il commence et finit en frontière de phrase (jamais au milieu d'un mot). Il ne commence jamais sur un connecteur qui suppose la phrase d'avant (donc, mais, du coup...) : ce connecteur n'est ni entendu ni sous-titré, aucune fraction de mot antérieure à la borne de début n'apparaît dans le clip.
2. Exclus d'office : segments SponsorBlock (sponsor, intro, outro, selfpromo), silences > 2 s en début/fin.
3. Durée : chaque clip dure de 60 à 120 s (bornes dans rubric.toml, marge de recalage comprise). Une histoire qui tient en 60-120 s = 1 clip unique, sans mention de partie. Un long passage fort (une affaire entière, typiquement 5 à 15 min) = une série de `min_parts` à `max_parts` parties (rubric.toml, défauts 2 et 12) de 60-120 s chacune, qui se suivent : chaque partie finit sur un suspense, et la partie k+1 reprend la fin de la partie k sur environ 3 s (entre 1 et 8 s), en commençant de préférence sur un début de phrase ; ce recouvrement est voulu et n'est pas un défaut.
4. Retenus : les moments (clips uniques ou passages) au-dessus de `min_score` (rubric.toml, défaut 60), avec un plafond souple : au plus `max_moments_per_hour` moments par heure de vidéo source (rubric.toml, défaut 6 ; plafond = arrondi supérieur de max_moments_per_hour x durée en heures, au moins 1), pris par score décroissant après la règle de non-chevauchement ; un moment dont le score atteint `always_keep_score` (rubric.toml, défaut 70) est toujours retenu, même au-delà du plafond (ce qui est vraiment bon n'est jamais coupé), et compte dans le plafond. Les moments écartés par le plafond sont listés avec cette raison. Deux moments retenus ne se chevauchent pas. Entre un passage (série) et un clip unique qui le chevauche, le passage est gardé dès qu'il atteint `min_score` (le contenu du clip unique y figure déjà) ; entre deux candidats du même format, le mieux noté. Seules les parties d'une même série se recouvrent (règle 3).
5. La sortie de l'étape liste pour chaque moment : start, end (secondes, précision 0,01 s : une borne ne recule jamais dans un mot retiré), scores par critère, score final, justification courte, texte de l'accroche, découpage en parties le cas échéant.
6. Les décisions humaines journalisées (feedback) sont fournies au LLM comme exemples positifs/négatifs.
