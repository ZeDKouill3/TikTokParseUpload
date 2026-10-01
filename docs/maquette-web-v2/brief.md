# Brief — interface de gestion clipper (v2)

Objectif : passer de la page actuelle (soumettre une URL, valider des moments,
voir des clips) à une vraie console de gestion, pour faire tourner clipper « à la
chaîne » avant la prod. L'autopost TikTok vient APRÈS, mais l'interface doit
déjà prévoir sa place (file de publication, comptes, planning).

Contraintes ratifiées : ADR-09ad (page statique HTML/CSS/JS sans étape de
build, servie par FastAPI local, aucune logique vidéo/audio/LLM dans
clipper/web/, elle appelle clipper.pipeline et lit workspace/ + output/),
ADR-b16b (étapes indépendantes, seul clipper.pipeline enchaîne), ADR-ad2e
(mode review/auto, aucune valeur de secours silencieuse : un échec se voit),
SPEC-6a47 (sidecar .json d'un clip), SPEC-76dc (agencement stream split).
Réglages = CONFIG_DEFAULTS des modules (clipper/config.py).

Utilisateur : francophone, veut du MODERNE, ERGONOMIQUE, INTUITIF, avec des
ANIMATIONS (transitions, micro-interactions, progression vivante). Français
dans l'UI. Dépôt public : jamais le nom d'une vraie chaîne/personne dans le
code du dépôt (exemples neutres « ma_chaine »). Maquette locale sous
research/web-ui/ : là on peut montrer un exemple réaliste.

## Écrans / fonctions (base, à challenger)
1. Tableau de bord : vidéos en cours (étape, progression live, ETA), file
   d'attente, erreurs / vidéos « en attente » (EXIT_QUEUED) avec la raison,
   clips à valider, prochaines publications, coût LLM du jour / de la semaine
   (workspace/<id>/llm_usage.jsonl), état GPU/CPU simple.
2. Chaînes : une chaîne = source (chaîne YouTube/Twitch, surveillance des
   nouvelles VOD on/off), preset (réglages : agencement letterbox/stream/split,
   style sous-titres, badge, titre, CTA, grille de notation), compte TikTok
   cible (plus tard), mode review/auto, créneaux de publication. Éditeur visuel
   d'agencement (cf. research/ma_chaine/editeur/editeur.html : glisser/
   redimensionner webcam/jeu/badge sur un canevas 1080x1920, aperçu sur une
   vraie image) et aperçu du style des sous-titres.
3. Vidéos : liste + ajout par URL (choix de la chaîne/preset), fiche vidéo
   avec frise des 12 étapes (download, transcribe, scenes, audio, moments,
   vision, parts, captions, reframe, subtitles, render, qa), durée par étape,
   journal, relancer une étape (--force), annuler.
4. Revue des moments (mode review) : lecteur de la source, moments proposés
   avec score, raisons du jury, bornes début/fin ajustables sur une timeline,
   accepter/refuser/ajuster, lancer le rendu.
5. Clips : galerie 9:16 avec lecteur, sidecar (titre d'écran, description,
   hashtags, parties d'une série), problèmes QA, éditer titre/description,
   approuver/refuser, re-rendre, télécharger, copier la description.
6. Publication (préparer l'autopost) : file « à publier » par chaîne,
   calendrier des créneaux (glisser-déposer), statut (planifié / publié /
   échec), en attendant l'API : bouton télécharger + copier la description.
7. Statistiques : résultats par clip (vues... plus tard via outcomes.py),
   coûts, temps de traitement.
8. Réglages : backend LLM et modèles par usage, dossiers, mode global.

## À ajouter si oublié (proposé par l'orchestrateur)
Notifications (toast + navigateur) quand une vidéo finit/échoue/attend ;
thème sombre/clair ; responsive mobile (validation depuis le téléphone) ;
raccourcis clavier en revue (A accepter, R refuser, J/K suivant) ; annuler
(undo) après une action ; recherche/filtres ; accès distant sécurisé plus tard
(login simple) ; progression en temps réel (SSE) ; états vides soignés et
squelettes de chargement.
