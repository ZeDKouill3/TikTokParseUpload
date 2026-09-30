---
id: TASK-f3e17a5d069f
type: task
slug: spec-successeur-de-spec-6a476ca57f39-titres-d-cr
title: "Spec : successeur de SPEC-6a476ca57f39 — titres d'écran sobres (sans emoji par défaut, sans superlatifs, phrase du clip ou fait concret)"
created: 2026-09-30T11:43:17Z
author: nicoc@zedk_ordi
status: done
scope:
  - AGENTS.md
blocked_by: []
done_criteria: |
  Nouvelle spec créée par ank new spec --supersedes SPEC-6a476ca57f39 (proposée, jamais ank accept), reprenant SPEC-6a476ca57f39 à l'identique sauf la règle du titre d'écran (screen_title) : 6 mots au plus ; AUCUN emoji par défaut (option de config pour en autoriser un) ; ton sobre : pas de superlatifs ni de mots d'emphase clickbait (liste d'exemples interdits : pur, total, explose, choc, incroyable, fou, dingue, glaçant, assourdissant, dévoilé...) ; de préférence une phrase réellement prononcée dans le clip (citation courte, guillemets français autorisés) ou un fait concret et précis du clip ; jamais de contenu absent du clip ; tableau d'exemples avant/après (au moins les 4 donnés dans le corps) ; le contrôle automatique (qa ou validation de la réponse LLM) refuse un titre avec emoji quand l'option est désactivée (erreur explicite, ADR-ad2e) ; AGENTS.md cite la nouvelle spec comme proposée. Aucun code. Attention : TASK-9e7b rédige en parallèle un successeur de SPEC-3a88 (format stream) : ne pas y toucher.
criteria_by: creator
proof:
  - type: assertion
    ref: SPEC-6a867ae54f94
    criteria: 02d4a61f99dd
    via: submitted
schema: 4
version: 3
---

Retour utilisateur 2026-09-30 sur les clips de démo : « tes titres sont trop kitsch » (titres sur la vidéo). Exemples réels produits par le pipeline et versions sobres proposées par l'orchestrateur :
- « Rage pure sur Silent Hill 😡 » -> « « C'est des salopards » »
- « Panique totale 😱 » -> « Y'en a un qui m'a vu »
- « Pharmacie en pleine crise 💊 » -> « Qui ouvre une pharmacie comme ça ? »
- « 🔎 TF1, le silence assourdissant » -> « Pourquoi TF1 n'en a pas parlé »
Autres titres produits : « 😱 L'affaire Bruel explose », « 🚨 L'affaire PPDA dévoilée », « Révictimisation : un tabou glaçant 😔 », « Bruel : le mot de la fin 🎤 ». Le titre est généré par l'étape captions (clipper/captions.py) ; l'implémentation viendra après ratification. Preuve : --proof assertion:<id de la spec>.
