---
id: TASK-1b5a73188dba
type: task
slug: documentation-de-l-installeur-portable-docs-inst
title: "Documentation de l'installeur portable : docs/INSTALLATION.md, README (installation sans outils de dev), versions.md critère n°1, CHANGELOG (SPEC installeur R10)"
created: 2026-10-03T22:51:33Z
author: plan-portable
status: open
scope:
  - docs/INSTALLATION.md
  - README.md
  - docs/versions.md
  - CHANGELOG.md
  - tests/test_docs_installation.py
blocked_by: [TASK-b82ee001ec52, TASK-9623bdba2126]
done_criteria: |
  SPEC-38f7761891f6 R10 tenue : (1) docs/INSTALLATION.md : parcours utilisateur sans outils de développement, en français, dans cet ordre : prérequis (Windows 10/11 64 bits, compte Claude, Chrome seulement pour publier), télécharger le zip de la Release, dézipper, double-clic Installer.bat, étape de connexion à Claude, où sont le programme et les données (chemins par défaut de SPEC R2), premier clip (contenu de PREMIER-CLIP.txt), GPU (automatique, CPU sinon), mise à jour (relancer un zip plus récent), désinstallation (données conservées sauf demande), diagnostic (clipper doctor), et une section « Problèmes fréquents » avec au moins : claude non connecté, Chrome absent, port 8000 occupé, antivirus/SmartScreen sur un .bat téléchargé ; (2) README.md : nouvelle section « Installation sans outils de développement » placée avant l'installation actuelle, qui devient « Installation développeur » (contenu inchangé), avec lien vers docs/INSTALLATION.md ; (3) docs/versions.md : critère n°1 de la v1.0.0 reformulé : « sur un PC neuf, le zip portable de la Release mène à un premier clip sans aide » ; (4) CHANGELOG.md : entrée « Non publié » décrivant l'installeur ; (5) tests : un test lit docs/INSTALLATION.md et README.md et vérifie la présence des titres de section exigés ci-dessus et des deux chemins par défaut ; tests README existants verts (tests/test_readme_assets.py). Aucun nom de personne ni de chaîne réelle. python -m pytest -q tests/test_docs_installation.py tests/test_readme_assets.py vert. (6) Une fois docs/INSTALLATION.md créé, le scope d'ADR-e1dac9ba2284 et de SPEC-38f7761891f6 est étendu à docs/INSTALLATION.md (ank amend <id> --scope ...), et ank check ne signale plus de scope mort pour ces deux entités.
criteria_by: creator
verify: [tests]
schema: 4
version: 3
---

Tâche 5 de SPEC-38f7761891f6 (ADR-e1dac9ba2284). À écrire une fois les scripts (tâche 3) et le builder (tâche 4) faits, pour documenter ce qui existe et non ce qui était prévu : relire installer/install.ps1 et PREMIER-CLIP.txt avant d'écrire. Ton du README existant (français, direct). Le nom du zip et les options de Installer.bat viennent du code, pas de mémoire.
