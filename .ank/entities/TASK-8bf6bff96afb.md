---
id: TASK-8bf6bff96afb
type: task
slug: test-de-fum-e-r-el-1-petit-appel-claude-par-usag
title: "test de fumée réel : 1 petit appel Claude par usage LLM + mini-vidéo de bout en bout (5 min)"
created: 2026-09-30T07:23:28Z
author: nicoc@zedk_ordi
status: done
scope:
  - tests/integration/test_smoke_real.py
  - tests/integration/__init__.py
  - tests/test_smoke_coverage.py
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Le test par usage couvre tous les usages LLM listés (test unitaire qui vérifie que la liste couvre tous les usages présents dans le code) ; sauté par défaut ; un passage réel complet noté dans ank log (durée, coût, résultat par usage) ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/87b52ba6861a@debe915
    tree: scope/88156ecf6a24
    criteria: c04d52f86280
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

On découvre les erreurs de l'API réelle (ex. 400 cache_control) au milieu d'une vidéo d'1 h. Ajouter tests/integration/test_smoke_real.py (skipif par défaut, CLIPPER_CLAUDE_INTEGRATION=1) : pour CHAQUE usage LLM du pipeline (vocab, transcript_fix, moments, jury_avocat/monteur/retention/conformite/spectateur, vision, parts, captions, emphasis, qa), construit la vraie requête via le vrai code de l'étape sur une entrée minuscule (quelques segments, 1-2 images générées) et fait 1 vrai appel claude -p ; vérifie réponse valide au schéma, pas d'erreur API, et note tokens/coût. Plus une option mini-vidéo : pipeline complet sur un extrait de 5 min d'une vidéo de workspace/ (chemin donné par variable d'environnement CLIPPER_SMOKE_VIDEO), dans un workspace temporaire, en config auto. Documenter la commande dans docs/GUIDE.md (section dépannage/développement). Coût visé < 1 USD pour le passage par usage.
