---
id: TASK-aa57433fc16a
type: task
slug: tiktok-v-rification-de-contenu-bloqu-e-sur-v-rif
title: "TikTok : vérification de contenu bloquée sur « Vérification en cours » : la relancer (décocher/recocher) après 2 min"
created: 2026-10-06T18:21:09Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - tests/test_tiktok.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts, sans réseau (page simulée comme les tests existants de tiktok.py) : en mode content_check = wait, si « Vérification en cours » reste affiché plus de [tiktok] content_check_retrigger_s (nouveau réglage dans CONFIG_DEFAULTS, défaut 120) sans résultat, Clipper décoche puis recoche l'interrupteur « Vérification de contenu simple » pour relancer le scan, le journalise (INFO, compte + numéro de relance), puis reprend l'attente ; au plus [tiktok] content_check_retriggers relances (défaut 3), toujours dans la limite content_check_timeout_s (inchangé) ; interrupteur grisé ou introuvable au moment de relancer : journalisé et l'attente continue telle quelle (aucune relance silencieuse simulée) ; la case doit être de nouveau cochée après la relance, sinon arrêt explicite unexpected_page (jamais de publication sans vérification en mode wait) ; résultat « Aucun problème constaté » ou problème signalé : comportement actuel inchangé. Entrée CHANGELOG [Non publié].
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/875bd30babbe@0dd43ec
    tree: scope/615498d3cb6a
    criteria: 8012aa7b436a
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Relevé réel 2026-10-06 ~20:08 Paris, compte 1ad53325b65d, publication programmée (Q_Vb1uNVkXg/02, 07/10 09:00) : « Vérification en cours » affiché plus de 10 min alors que les vérifications précédentes du compte prenaient ~1 min (journal 2026-10-06 00:10:12 -> 00:11:13). L'utilisateur demande de relancer le scan en décochant/recochant l'interrupteur au bout de 2 min. Voir await_content_check et disable_content_check (cas interrupteur grisé).
