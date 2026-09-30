---
id: TASK-8abc2ab932e9
type: task
slug: sortie-console-plus-verbeuse-progression-dans-ch
title: "Sortie console plus verbeuse : progression dans chaque étape, une ligne par appel LLM, résumé final"
created: 2026-09-30T10:44:38Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/pipeline.py
  - clipper/__main__.py
  - clipper/transcribe.py
  - clipper/moments.py
  - clipper/jury.py
  - clipper/vision.py
  - clipper/parts.py
  - clipper/captions.py
  - clipper/reframe.py
  - clipper/subtitles.py
  - clipper/render.py
  - clipper/qa.py
  - clipper/download.py
  - clipper/audio.py
  - clipper/llm
  - tests/test_logging_verbose.py
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Avec -v (INFO), la console montre, sans coût notable (< 1 % du temps de l'étape) : début/fin de chaque étape avec durée ; progression des étapes longues au plus toutes les 30 s ou tous les 10 % (download : % et débit ; transcribe : minutes audio traitées / total, facteur temps réel ; reframe/render/qa : clip i/N avec durée ; vision : moment i/N) ; une ligne par appel LLM (usage, modèle, tokens entrée/sortie/cache, coût, durée ; réussite/échec/réessai) ; jury : décision par candidat (score final, retenu/rejeté/exploration) ; moments : nombre de candidats, retenus, raison des rejets ; à la fin du run : résumé (durée par étape, nombre de clips, statuts qa, coût LLM total et par usage, chemin de output/) ; -vv (DEBUG) ajoute le détail ; sans -v, sortie actuelle inchangée ; scenes.py hors scope (une autre tâche y ajoute sa progression) ; tests unitaires (caplog) qui prouvent les lignes émises et leur fréquence bornée ; docs/GUIDE.md décrit -v / -vv.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/3b12a627cf40@cc9ffd9
    tree: scope/8a37dba67cce
    criteria: 66ad727462f4
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-09-30 : « je veux plus de verbeux dans les sorties, ce n'est pas ce qui coûtera en ressources ; pour la console de calcul et les consoles à venir ». Constat : pendant la démo Twitch (3 h), la seule sortie de -v pendant 30+ min est 'etape scenes' : impossible de savoir si ça avance ou si c'est bloqué. Journalisation via logging (déjà utilisé), pas de print ; les données viennent de ce qui existe déjà (llm_usage.jsonl, pipeline.json, retours des étapes). Ne rien changer au comportement des étapes (ADR-b16b : une étape n'importe pas une autre étape).
