---
id: TASK-44aae8fe7bc1
type: task
slug: readme-refait-niveau-pro-logo-terminal-anim-et-s
title: "README refait, niveau pro : logo, terminal animé et schéma animé du pipeline (SVG), sections complètes"
created: 2026-09-30T10:21:53Z
author: nicoc@zedk_ordi
status: done
scope:
  - README.md
  - docs/assets
  - tests/test_readme_assets.py
blocked_by: []
done_criteria: |
  README.md refait en français, niveau projet open source pro : en-tête centré avec le logo (clipper/web/static/logo.svg, ou une copie docs/assets/logo.svg), nom, accroche d'une ligne, badges (version 0.1.0 pré-version, Python 3.11, licence si un fichier LICENSE existe sinon pas de badge licence, plateforme Windows/CUDA optionnel) ; docs/assets/demo-terminal.svg : animation SVG autonome (CSS keyframes, sans JavaScript, rendue par GitHub dans <img>) qui rejoue une vraie session 'python -m clipper -v run <url>' construite à partir d'un vrai journal (research/retranscribe/reserve-test.log ou research/madajel/demo2.log), identifiants de vidéo remplacés par un id neutre, chemins perso retirés, 15-25 s en boucle ; docs/assets/pipeline.svg : schéma animé des étapes (download -> transcribe -> scenes/audio -> moments + jury -> vision -> parts -> captions -> reframe -> subtitles -> render -> qa -> output/<id>/<clip>.mp4 + .json), lisible en thème clair ET sombre de GitHub ; sections : Ce que ça fait, Démo (les 2 SVG + emplacement commenté <!-- demo-clip.gif --> pour un futur GIF de clip), Points forts, Installation (wheel de la release + sources avec uv), Démarrage rapide, Formats (letterbox / stream), Preset par chaîne et CTA abonnement, Modes review/auto, Interface web, Coûts et performances (renvoi docs/benchmarks/rtx3050.md), Configuration, Documentation, Développement (tests, ank), Limites et feuille de route ; aucun contenu vidéo tiers ni capture de vidéos tierces ; aucun chiffre inventé ; test unitaire : les SVG sont du XML valide sans <script> et chaque lien relatif du README pointe vers un fichier existant.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/61af9e76a804@18331b2
    tree: scope/de7ff01598b4
    criteria: 1c6b0e71af5c
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

Demande utilisateur 2026-09-30 pour la release v0.1.0 : « refais le readme aussi, tu sais faire des petites animations de démo ? et mets le logo aussi », release « digne de ce nom, bien complète, et pro ». Les notes de release (docs/releases/v0.1.0.md) sont faites par un autre worker : ne pas y toucher, mais le README peut y renvoyer. Le test unitaire va dans un fichier sous docs/assets ? Non : il faut un fichier de test dans le scope -> placer le test dans tests/test_readme_assets.py n'est pas dans le scope ; si besoin, ank release avec la raison et l'orchestrateur amendera le scope (préférer : demander l'amendement tôt). Un GIF d'un vrai clip viendra plus tard (film CC-BY Tears of Steel), laisser l'emplacement.
