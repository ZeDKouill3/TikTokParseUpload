---
id: TASK-8ba9ce0f2076
type: task
slug: publication-tiktok-une-v-rification-de-contenu-j
title: "Publication TikTok : une vérification de contenu jamais terminée met le clip en échec sans arrêter tout le compte"
created: 2026-10-09T11:23:04Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/worker.py
  - tests/test_worker.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat réel 09/10 (logs/journal-2026-10-09.log 12:25-12:38) : la vérification de contenu TikTok de v2894981843/02 (compte 17c3783183e1) ne s'est jamais terminée (3 relances puis délai [tiktok] content_check_timeout_s = 900 s, arrêt de code « content_check », clipper/tiktok.py ~l.17 et ~l.837) ; clipper/worker.py (~l.1092-1095) traite cet arrêt comme les autres arrêts sûrs R4 : _fail(..., halted=True) met TOUT le compte à l'arrêt (« arrêt de publication enregistré »), alors que le blocage tient à ce clip (le même clip a bloqué deux fois, les autres posts du compte passaient). (1) Un arrêt de code content_check (délai de vérification de contenu dépassé) met l'entrée en échec avec une raison explicite (« vérification de contenu TikTok jamais terminée pour ce clip : choisis un autre clip ou réessaie plus tard ») SANS arrêter le compte (halted=False), journal error et événement console comme aujourd'hui ; le worker passe aux autres entrées dues. (2) Tous les autres arrêts sûrs (captcha, connexion, refus, page inattendue...) gardent halted=True, inchangés. (3) Garde-fou : si 2 arrêts content_check de suite surviennent sur le même compte pour 2 clips différents, le compte est arrêté comme avant (le problème vient alors du compte, pas du clip), raison écrite. (4) Tests CPU sans réseau ni navigateur (fakes existants de tests/test_worker.py) : content_check sur un clip -> entrée failed, compte non arrêté, l'entrée due suivante du même compte est publiée ; deux content_check de suite sur deux clips -> compte arrêté ; captcha -> compte arrêté (inchangé). CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/2ebbf369048f@6c5f467
    tree: scope/ea24733f65e3
    criteria: 2abb9e2040b8
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
