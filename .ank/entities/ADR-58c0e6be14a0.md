---
id: ADR-58c0e6be14a0
type: adr
slug: publication-et-statistiques-youtube-shorts-par-p
title: Publication et statistiques YouTube (Shorts) par pilotage d'un vrai navigateur sur YouTube Studio, comme TikTok
created: 2026-10-03T08:47:11Z
author: nicoc@zedk_ordi
status: accepted
scope:
  - clipper/youtube.py
  - clipper/browser.py
  - clipper/publish.py
  - clipper/worker.py
  - clipper/web/**
  - clipper/assets/youtube_selectors.toml
constraint: |
  Toute action sur YouTube en tant que compte de publication (publication immédiate ou programmée, lecture des statistiques) passe par clipper.youtube ; aucun autre module ne publie sur YouTube (le téléchargement des vidéos sources reste dans clipper.download). Backend browser : Playwright sur un vrai Chrome visible, profil persistant par compte sous state/browser/<compte>/ (clipper.browser) ; connexion faite à la main par l'utilisateur, jamais de saisie d'identifiant ni de mot de passe ; profil jamais versionné ni copié hors de state/. Captcha, vérification Google, page ou élément inattendu = arrêt immédiat, publication remise en attente avec capture et raison journalisées ; aucun contournement. Rythme humain, plafonds par compte en config, un seul compte piloté à la fois tous services confondus. Aucun test par défaut ne touche YouTube, le réseau ni un vrai navigateur.
ratified: 2bc7d5329f7d
verified:
  - by: nicoc@zedk_ordi
    at: 2026-10-03T09:13:57Z
schema: 4
version: 2
---

## Contexte
L'utilisateur veut publier aussi les clips sur YouTube (Shorts) depuis Clipper, comme sur TikTok. L'API YouTube Data impose, tant que l'app Google n'est pas validée (audit), que les vidéos envoyées restent privées, et son quota par défaut limite à quelques envois par jour. Choix utilisateur du 2026-10-03 : faire comme TikTok, par le navigateur (YouTube Studio), publication et statistiques. Le circuit TikTok (ADR-1a58, SPEC-9225, SPEC-e500, SPEC-1ed3, SPEC-47e2) marche en réel.

## Décision
- clipper/youtube.py : publish(clip, compte, immédiat ou programmé côté YouTube) et fetch_stats(compte), backend browser (Playwright sur vrai Chrome, profil persistant de clipper.browser), sur YouTube Studio ; plus tard un backend api possible.
- Mêmes règles que TikTok : connexion manuelle dans un Chrome normal sur le profil, jamais d'identifiant saisi ; repères dans un seul fichier (clipper/assets/youtube_selectors.toml), relevés sur la vraie page ; arrêt sûr sur toute page ou élément inattendu ; rythme humain, plafonds par compte, un seul compte piloté à la fois (tous services confondus).
- Les comptes portent un service (tiktok ou youtube) ; Publication et Statistiques listent les comptes des deux services ; un même clip peut être publié sur un compte TikTok et sur un compte YouTube (une publication par compte).
- Le code commun aux deux services (rythme, arrêt sûr, captures, verrou d'un seul compte piloté) peut être mis en commun dans clipper/browser.py.

## Conséquences
- Risque de vérification Google (captcha, « confirmez votre identité ») assumé par l'utilisateur ; chaque arrêt est visible (ADR-ad2e).
- Les pages YouTube Studio changent : un seul fichier de repères à corriger.
- Les Shorts sont reconnus par YouTube d'après le format (vertical, 3 min max) ; nos clips 9:16 de 30 à 120 s le respectent.
