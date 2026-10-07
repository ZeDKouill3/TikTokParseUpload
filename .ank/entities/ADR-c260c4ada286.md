---
id: ADR-c260c4ada286
type: adr
slug: boucle-d-apprentissage-branch-e-sur-les-relev-s
title: "Boucle d'apprentissage branchée sur les relevés réels : rattachement post→clip après relevé, versement stats→outcomes, métrique normalisée à maturité, recalibrage automatique, coach sur déclencheur validé dans l'interface, bilan des VOD de veille (amende ADR-1cf0)"
created: 2026-10-07T10:24:36Z
author: w-learnplan
status: accepted
scope:
  - clipper/**
constraint: |
  Toute statistique de plateforme relevée sous state/stats/<service>/<compte>/ est versée dans le journal des résultats (clipper.outcomes) par la bibliothèque clipper/learning.py, exécutée par le worker seul à chaque tour et jamais par clipper/web, de façon idempotente, chaque entrée portant video_id, clip_id et moment_id ; un post relevé n'est relié à un clip que par l'id de post du sidecar ou par un rattachement sans ambiguïté (légende, compte, instant de publication) écrit dans le sidecar et l'entrée de publication, jamais deviné ; la métrique d'apprentissage est le rang 0-1 des vues à maturité (au moins maturity_days après publication) parmi les posts mûrs du même compte, un compte sous min_account_posts posts mûrs à vues > 0 n'entrant pas dans l'apprentissage ; le recalibrage des poids suit automatiquement chaque versement selon ADR-1cf0 ; le coach ne tourne que sur déclencheur (nouveaux cas mûrs et intervalle minimum), via clipper.llm, et aucune de ses propositions n'est appliquée sans une validation humaine explicite dans l'interface, l'adoption écrivant la perspective dans config.toml ; la veille reçoit dans son prompt le bilan chiffré des VOD choisies précédemment ; toute panne de la boucle est journalisée et visible, jamais remplacée par une valeur de secours ; YouTube n'entre dans la boucle qu'une fois son relevé existant.
amends: [ADR-1cf0b17d48b3]
ratified: a78a1a8d9afc
verified:
  - by: nicoc@zedk_ordi
    at: 2026-10-07T10:32:22Z
schema: 4
version: 2
---

## Contexte
ADR-1cf0 (accepté le 2026-09-25) a décidé une boucle d'apprentissage du jury
sur des signaux réels. Ses briques existent (TASK-a374 `clipper/outcomes.py`,
TASK-15c1 `clipper/jury_calibration.py`, TASK-6595 `clipper/jury_coach.py`,
TASK-022d exploration) mais, mesuré sur le dépôt le 2026-10-07 :
- `state/outcomes.jsonl`, `state/jury_weights.json`, `prompts/jury/` n'existent
  pas ; `outcomes.record` n'est appelé par aucun module de `clipper/` ;
  l'import CSV a été retiré de l'écran (SPEC-47e2 R1). Le journal est vide.
- Les statistiques TikTok sont relevées (SPEC-47e2, `state/stats/tiktok/
  <compte>/`) : 3 comptes, 187 posts distincts, 111 relevés. Champs présents
  par post : vues, likes, commentaires, `avg_watch_s`, `watched_full`,
  `new_followers` (non nuls sur les posts lus en détail) ; `shares`,
  `retention`, `retention_curve`, `viewers`, `traffic_sources` sont à null
  partout (sélecteurs jamais confirmés, TASK-429d).
- 141 sidecars `output/<video_id>/<clip_id>.json` ; 94 portent `tiktok_post`,
  81 avec un id de post retrouvé dans les relevés, 13 sans id (11 « post
  programmé : son adresse publique n'existe pas encore », 2 « lien du post
  introuvable sur la page Publications »). Aucun sidecar ne porte
  `moment_id` : il se déduit du `clip_id` (`captions._clip_id` :
  `NN` ou `NN-pK`, `moment_id = int(NN)`), et la trace du jury vit dans
  `workspace/<video_id>/moments.json` (`moments[].jury.trace`, 105 moments
  sur 23 vidéos). `clip_id` seul est ambigu entre vidéos (ce que
  `jury_calibration` signale déjà en `ignored_stats`).
- Signal réel : un seul compte a des vues (101 posts, 97 à vues > 0, 93 à
  ≥ 100, 29 à ≥ 1000, max 72 000, médiane 540) ; les deux autres comptes ont
  0 vue sur leurs 86 posts (dont 79 clips Clipper reliés : aucun signal). Sur
  le compte qui a des vues, 10 posts depuis le 2026-10-01 viennent de
  Clipper : 2 reliés par id, 8 non reliés (programmés jamais rattachés après
  coup, ou lien introuvable à la publication immédiate) ; ses 91 posts
  antérieurs (janvier-février 2026) ne sont pas des clips Clipper. Le lien
  post → clip est donc le premier verrou : sans lui, zéro cas exploitable.
- Veille (ADR-ca9a, SPEC-bdd9/df51) : 2 jours d'état, 6 propositions (4 mises
  en file, avec `video_id` dans `seen.json`) ; aucun retour « VOD choisie →
  vues obtenues » n'est donné à Claude.
- YouTube : SPEC-5e50 R6 est acceptée mais `clipper/youtube.py` n'a aucun
  relevé de statistiques et `state/stats/youtube/` n'existe pas.
- Volume : quelques dizaines de posts par semaine au mieux, vues très
  bruitées (0 à 72 000 sur un même compte) : l'apprentissage doit être
  normalisé et protégé contre le bruit, et le coach ne doit rien appliquer
  seul.

## Décision
Amende ADR-1cf0 (qui reste en vigueur : vérité terrain = signaux réels,
poids bornés, prompts par lots versionnés, exploration, conformité hors
apprentissage) en branchant la boucle sur les relevés réels :
1. **Une bibliothèque `clipper/learning.py`** (pas une étape : rien sous
   `workspace/<video_id>/`, n'importe ni `clipper.web` ni une étape, ADR-b16b)
   porte la boucle. Réglages dans son `CONFIG_DEFAULTS` (table `[learning]`),
   état sous `state/learning/` (JSON atomiques). Elle lit les relevés par
   `clipper.tiktok` (lecture seule), les sidecars de `output/` et
   `moments.json`, écrit dans `clipper.outcomes`, appelle
   `clipper.jury_calibration` et `clipper.jury_coach`.
2. **Le worker exécute, le web affiche** (modèle ADR-ca9a §5) : `clipper.worker`
   appelle `learning` à chaque tour ; `clipper/web` lit `state/learning/` et
   dépose des décisions humaines, jamais de calcul ni de LLM (ADR-09ad).
3. **Rattachement post → clip après relevé** : un sidecar `tiktok_post` sans
   id est relié au post relevé du même compte dont la légende correspond (même
   règle que `find_post_link`) à moins de `link_window_h` de `publish_at` ;
   un seul candidat → id et url écrits dans le sidecar et l'entrée de
   publication ; zéro ou plusieurs → rien, raison visible. Jamais deviné.
4. **Versement stats → outcomes, idempotent**, chaque entrée portant
   `video_id`, `clip_id` et `moment_id` (plus jamais un `clip_id` seul) ;
   `qa` du sidecar versée comme résultat (`kind: result`) une fois par clip.
5. **Métrique normalisée, stats mûres** : `views_percentile` = rang (0-1) des
   vues lues au premier relevé à au moins `maturity_days` de la publication,
   parmi les posts mûrs du même compte sur `window_days` ; un compte avec
   moins de `min_account_posts` posts mûrs à vues > 0 n'entre pas dans
   l'apprentissage (ses clips sont listés comme exclus). Ni rétention 3 s ni
   partages tant que le relevé ne les fournit pas (null partout aujourd'hui).
6. **Recalibrage automatique** après chaque versement qui ajoute une entrée :
   `jury_calibration.calibrate` avec les traces de `moments.json`, règles
   d'ADR-1cf0 inchangées (bornes 0,5-1,5, `min_clips`, lissage, conformité
   fixe), `stats_metric` par défaut `views_percentile`.
7. **Coach sur déclencheur, jamais appliqué seul** : `jury_coach.propose`
   tourne seulement si au moins `coach_min_new_cases` cas mûrs reliés sont
   nouveaux depuis le dernier passage ET si `coach_min_interval_days` se sont
   écoulés (coût borné : un appel « coach » par juge + rejeu de
   `lessons_per_call` cas × 2 versions, usage `jury_<juge>`, via `clipper.llm`
   uniquement, ADR-b1c1). Les propositions sont listées dans l'interface avec
   leur métrique avant/après ; **Adopter** (acte humain) écrit la perspective
   dans `[jury.judges.<juge>].perspective` de `config.toml` par le même chemin
   que Réglages ; **Refuser** la clôt. Aucun A/B automatique pour l'instant
   (volume trop faible pour une mesure) : le rejeu comparatif d'ADR-1cf0 et
   la décision humaine tiennent lieu de garde-fou.
8. **Bilan de veille** : `learning` écrit `state/veille/bilan.json` (VOD
   choisies sur `veille_report_days`, clips publiés, `views_percentile` et
   vues à maturité) ; `veille._prompt` l'inclut tel quel dans le choix de
   Claude ; absent → ligne explicite « aucun bilan ».
9. **Aucun repli silencieux** (ADR-ad2e) : une panne de rattachement, de
   versement, de calibration ou de coach est écrite dans
   `state/learning/*.json` (`last_error`) et journalisée une fois, visible
   dans l'interface ; aucune valeur inventée, aucune stat immature utilisée.
10. **YouTube hors boucle** tant qu'aucun relevé YouTube n'existe ; le jour
    où `state/stats/youtube/` existe, les mêmes règles s'appliquent par
    `service`.

## Conséquences
- Première semaine après branchement : les 8 posts non reliés du compte actif
  sont rattachés au relevé suivant (s'ils sont sans ambiguïté), le journal se
  remplit, les poids restent à 1 tant que `min_clips` (20) n'est pas atteint :
  l'effet visible immédiat est l'écran (clips reliés, exclus, poids, bilan de
  veille), pas un changement de jugement.
- Les deux comptes à 0 vue ne contaminent pas l'apprentissage.
- Le coach coûte au plus un lot par `coach_min_interval_days`, et rien ne
  change sans un clic humain.
- Successeurs possibles, hors de cette décision : A/B mesuré entre deux
  versions de prompt quand le volume le permettra ; rétention 3 s et partages
  quand le relevé les lira ; YouTube.
