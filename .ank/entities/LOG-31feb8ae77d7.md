---
id: LOG-31feb8ae77d7
type: log
title: "MESURE: appel reel isole (claude -p --debug api --debug-file), sans --strict-mcp-config : le debug"
created: 2026-09-30T08:17:57Z
author: w-321b062a4dc8
scope:
  - clipper/llm
  - clipper/jury.py
  - tests/test_llm.py
  - tests/test_jury.py
about: TASK-321b062a4dc8
seq: 2
schema: 4
version: 1
---

 log liste 6 serveurs MCP GLOBAUX charges (claude.ai Claude Docs/TinyPages/Canva/Google Drive/Google Calendar/Gmail, ~/.claude.json de l'utilisateur), MALGRE --setting-sources "" --no-session-persistence --tools "" (ces flags ne filtrent que settings.json user/project/local, pas mcpServers qui est une autre surface de config). Timestamps du meme log : [API REQUEST] envoye a 08:12:48.940Z, alors que Canva et TinyPages ne terminent leur connexion qu'a 08:12:50.184Z et 08:12:50.240Z (>1s APRES l'envoi) -- la liste de tools jointe a la requete depend donc d'une course entre le delai d'envoi et la connexion asynchrone de chaque serveur MCP, non deterministe et plus sensible sous charge (plusieurs claude -p paralleles = variance accrue), ce qui correspond exactement a l'intermittence liee au parallelisme mesuree par TASK-f89f. Avec --strict-mcp-config (meme commande) : 0 serveur MCP charge (verifie, grep sur debug log), appel reussi, cache_read_tokens>0 (cache toujours partage). Hypothese : chaque serveur MCP connecte a temps ajoute son propre bloc cache_control (mise en cache independante par le CLI de chaque groupe de tools distant), ce qui explique un total de blocs variable pouvant depasser 4 (notre 1 bloc cache_prefix + le bloc systeme deja pose par Claude Code + 0 a 6 blocs MCP selon la course), sans lien avec le role/modele/contenu -- coherent avec les observations de TASK-f89f (course entre processus, role/modele variables). 2 tentatives de rejouer le 400 en reel (script scratchpad/repro_400.py, 2 leaders paralleles opus+sonnet avec cache_prefix, 4 essais = 8 appels ; puis pytest -k jury x2 = 10 appels) n'ont PAS reproduit le 400 cette fois (taux mesure precedemment 2/5, echantillon insuffisant pour l'exclure) -- mais la cause mesuree (blocs MCP hors controle, racy) explique le mecanisme independamment d'un nouveau repro direct. Correctif : ajouter --strict-mcp-config a ClaudeCLIBackend.build_command (aucun --mcp-config fourni => 0 serveur MCP, deterministe, aucun effet sur l'auth OAuth contrairement a --bare).
