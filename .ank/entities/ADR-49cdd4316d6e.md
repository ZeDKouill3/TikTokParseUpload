---
id: ADR-49cdd4316d6e
type: adr
slug: interface-page-html-locale-servie-par-fastapi-av
title: "Interface : page HTML locale servie par FastAPI, avec validation de config par les fonctions pures des étapes"
created: 2026-10-09T01:07:01Z
author: nicoc@zedk_ordi
status: proposed
scope:
  - clipper/web/**
constraint: |
  L'interface est une page HTML/CSS/JS statique (sans étape de build) servie par un serveur FastAPI local dans clipper/web/. Elle ne fait qu'appeler clipper.pipeline et lire workspace/ et output/, plus (exception fermée) les fonctions pures de validation/lecture de config nommées dans cet ADR ; aucune logique de traitement vidéo, audio ou LLM dans clipper/web/. Pas de tkinter/customtkinter.
supersedes: ADR-09ad233678f2
schema: 4
version: 1
---

## Contexte
ADR-09ad (accepté le 2026-09-25) dit que l'interface « ne fait qu'appeler
clipper.pipeline et lire workspace/ et output/ ». L'audit du 2026-10-09
(`research/reviews/drift-0910.md`, I2) constate que `clipper/web/app.py` importe
trois modules d'étape (`moments`, `reframe`, `render`) pour VALIDER un preset
depuis l'écran Styles et pour libeller la grille choisie : appels purs, sans
traitement vidéo ni appel LLM, mais contraires à la lettre de la contrainte.
Sans amendement, chaque nouvel écran qui valide une table de config enfreindrait
un peu plus la contrainte.

Décision prise : reprendre ADR-09ad à l'identique et lui ajouter UNE exception
fermée, plutôt que de déplacer ces validateurs hors des modules d'étape (ils
vivent à côté des `CONFIG_DEFAULTS` qu'ils valident, ce qui est la convention du
dépôt : les réglages d'un module vivent dans le module).

## Décision
Reprise à l'identique d'ADR-09ad :
- `python -m clipper serve` lance FastAPI (uvicorn) sur localhost.
- Page : coller une URL YouTube, suivre la progression par étape, revoir les
  moments proposés (aperçu, ajuster début/fin, accepter/refuser), lancer le
  rendu, voir les clips.
- Progression via polling ou SSE ; le traitement tourne dans un worker séparé du
  thread HTTP.
- L'interface ne fait qu'appeler `clipper.pipeline` et lire `workspace/` et
  `output/` ; aucune logique de traitement vidéo, audio ou LLM dans
  `clipper/web/`. Pas de tkinter/customtkinter.

Ajout (exception fermée) : `clipper/web/` peut aussi appeler les fonctions PURES
de validation ou de lecture de config des modules d'étape, et SEULEMENT la liste
fermée suivante, relevée dans `clipper/web/app.py` :

| Module | Symbole | Usage dans `app.py` |
|---|---|---|
| `clipper.moments` | `resolve_rubric_path` | résoudre et libeller `[moments] rubric_path` (`app.py` ~l.1306 et ~l.1318) |
| `clipper.moments` | `_BUILTIN_RUBRICS` (table de constantes, lecture) | savoir si la valeur est une grille embarquée (~l.1309) |
| `clipper.moments` | `MomentsError` (exception) | convertir en réponse d'erreur (~l.1307) |
| `clipper.reframe` | `_settings` | valider la table `[reframe]` d'un preset (~l.1622, ~l.1706) |
| `clipper.reframe` | `_letterbox_geometry` | valider la géométrie letterbox sur la source de référence (~l.1707) |
| `clipper.reframe` | `ReframeError` (exception) | convertir en `ConfigError` (~l.1623, ~l.1709) |
| `clipper.render` | `_settings` | lire la table `[render]` d'un preset (~l.1708) |
| `clipper.render` | `check_cta_handle_gap` | valider `[render] cta_handle_gap` (~l.1708) |
| `clipper.render` | `RenderError` (exception) | convertir en `ConfigError` (~l.1709) |

Vérifié dans le code (2026-10-09) : aucune de ces fonctions ne traite de la
vidéo ni de l'audio, n'appelle `clipper.llm`, ne lance un sous-processus, ni
n'écrit de fichier. `moments.resolve_rubric_path` calcule un chemin
(`importlib.resources`, `Path`) ; `reframe._settings` fusionne
`CONFIG_DEFAULTS` et `config.section("reframe")` puis vérifie des valeurs
(`_validate_split_geometry`, `_validate_letterbox_geometry`, qui ne font que des
calculs sur des rectangles) ; `reframe._letterbox_geometry` est de l'arithmétique
sur des rectangles ; `render._settings` fusionne des tables ;
`render.check_cta_handle_gap` teste un entier. La seule lecture hors config est
celle du fichier de grille par `app.py` lui-même (`Path.read_bytes`).
(`_settings(None)` lit le `config.toml` courant via `clipper.config.load_config` :
lecture seule.)

Ce qui reste INTERDIT à `clipper/web/`, sans exception :
- appeler `run` d'un module d'étape, ou toute autre fonction d'étape qui lit ou
  écrit des données de travail (`detect_facecam`, `reframe`, `render`,
  `transcribe`…) ; l'enchaînement passe par `clipper.pipeline` et le worker
  (ADR-b16b, ADR-35b7) ;
- tout traitement vidéo ou audio ;
- tout appel LLM (`clipper.llm.ask` ou un backend) ;
- toute écriture sous `workspace/` ou `output/` hors de ce que fait déjà
  `clipper.pipeline` appelé depuis l'interface ;
- étendre la liste ci-dessus sans nouvel ADR (ajouter une fonction à la liste =
  amender cette décision).

Hors périmètre de cette exception : `clipper.llm` n'est pas un module d'étape ;
`app.py` y lit sa configuration (`_settings`, `_BACKENDS`, ~l.1445, ~l.1473)
sans jamais appeler `ask`. Cet usage, déjà en place, relève de ADR-b1c1 (tout
appel LLM passe par `clipper.llm`) et n'est pas élargi ici.

## Conséquences
- L'interface reste remplaçable et le pipeline tourne sans elle (CLI), comme
  dans ADR-09ad.
- Le message d'erreur d'un preset invalide à l'écran Styles est exactement celui
  du module (« [reframe] ... »), sans duplication de la règle dans `clipper/web/`.
- Dette connue : l'interface dépend de symboles à tiret bas (`_settings`,
  `_letterbox_geometry`, `_BUILTIN_RUBRICS`). Les renommer en noms publics sans
  changer leur comportement est permis et n'exige pas d'ADR ; les déplacer vers
  `clipper/config.py` ou `clipper/channel.py` reste possible plus tard et
  rendrait cette exception inutile (alors la supprimer par un nouvel ADR).
- Test de garde recommandé (tâche à part) : un test qui liste les attributs
  `moments_mod.*`, `reframe_mod.*`, `render_mod.*` utilisés dans
  `clipper/web/app.py` et échoue s'il sort de la liste fermée ci-dessus.

## Références
ADR-09ad (remplacé), ADR-b16b (une étape n'importe jamais `clipper.web`, seul
`clipper.pipeline` enchaîne), ADR-b1c1 (tout appel LLM passe par `clipper.llm`),
ADR-ad2e (jamais de repli silencieux : l'erreur du validateur remonte telle
quelle), ADR-35b7 (console v2 : worker séparé). Audit :
`research/reviews/drift-0910.md`, point I2.
