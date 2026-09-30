---
id: LOG-2efcaf18bd29
type: log
title: "RAPPORT DE BUG (a envoyer a @haksolot/ank, pret a copier) : Titre - 'ank status' reste bloque"
created: 2026-09-30T11:23:40Z
author: w-717757eda946
scope:
  - tools/ank-viz
about: TASK-717757eda946
seq: 4
schema: 4
version: 1
---

 plusieurs minutes, independamment de la taille ou du contenu du depot. Version : ank 0.8.0 (298c01a), binaire natif ank-win32-x64 (npm), Windows 11, Git for Windows (mingw64). Depot : 389 commits, .git partage entre 5 'git worktree'. Symptome : 'ank status --json' prend 163-208 s selon les essais, contre 0,4-2,3 s pour 'ank find --json' et 0,4-0,8 s pour 'ank graph --json' dans le meme depot. Le temps CPU du processus ('time' shell) est quasi nul (user 0-0,17 s, sys 0,05-0,14 s) pour ces 163-208 s de mur : la quasi-totalite du temps est une attente, pas un calcul. Reproduit a l'identique dans un 'git worktree' qui ne contient AUCUN des gros dossiers non suivis du depot principal (pas de workspace/, .worktrees/, research/), ce qui infirme un scan de l'arbre de travail comme cause. GIT_TRACE=1 sur le binaire natif montre la sequence : git rev-parse --verify --quiet main^{commit} ; git cat-file -p main:.ank/entities, .ank/tasks, .ank/adr ; git hash-object --stdin-paths ; git cat-file --batch ; git rev-list --full-history --format=... HEAD ; git rev-list HEAD -- <8 chemins de scope litteraux> ; enfin git diff-tree --stdin -r -M -z --name-status, apres laquelle plus aucune ligne de trace n'apparait (donc plus aucun sous-processus git demarre) pendant le reste du blocage (90 s a plus de 200 s selon l'essai). Hypothese non confirmee (binaire ferme, pas de source disponible) : l'echange stdin/stdout avec ce diff-tree --stdin reste ouvert (vraisemblablement pour calculer, par commit x par chemin de scope, les fichiers touches) est anormalement lent sous Windows, ou bloque en back-pressure. 'remote:false' dans la sortie et aucun 'ls-remote' trace : pas un appel reseau. Reproductible sans --remote (chemin local seul). Impact : rend inutilisable tout usage synchrone de 'ank status' sur ce depot (ex. tools/ank-viz), contourne cote client par une lecture en arriere-plan avec cache (TASK-7177).
