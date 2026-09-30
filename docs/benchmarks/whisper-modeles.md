# Banc whisper `small` vs `large-v3-turbo` (RTX 3050 Laptop 4 Go)

TASK-b6b731ad188a. Mesure pure, aucun fichier de `clipper/` modifié par le
script (`research/whisper-banc/bench.py`, hors dépôt, ignoré par git) : il
appelle `faster-whisper` et `clipper.llm` directement, sans passer par
`clipper.transcribe.transcribe()`.

## Méthode

- Machine : RTX 3050 Laptop 4 Go, device résolu par `clipper.gpu.get_device()`
  (`cuda`, `compute_type="float16"`, identique pour les deux modèles : c'est
  `clipper.gpu` qui fixe le `compute_type`, jamais codé en dur par modèle).
- Extraits (ffmpeg, wav 16 kHz mono, 10 min chacun) :
  - `7VaA8XUKrAY` (débat TV, parole FR dense), 600–1200 s.
  - `v2887271276` (stream de jeu), 3000–3600 s.
- Options whisper identiques aux réglages actuels de `clipper.transcribe` :
  `BatchedInferencePipeline`, `batch_size=8`, `beam_size=5`, `vad_filter=True`,
  `word_timestamps=True`, `language=None` (détection auto), **sans**
  `initial_prompt` (vocabulaire) : le banc isole l'effet du modèle whisper
  seul, pas l'effet du vocabulaire (déjà mesuré séparément,
  `docs/bench-whisper-vitesse.md`).
- Un seul modèle chargé en VRAM à la fois (ADR-fb9b) : `small` entièrement
  passé (2 extraits + correction), modèle libéré (`gc.collect()` +
  `torch.cuda.empty_cache()`), puis `large-v3-turbo` chargé.
- VRAM : pic mesuré par sondage `nvidia-smi` toutes les **1 s**, uniquement
  pendant le chargement + la transcription de chaque modèle (jamais en
  boucle hors banc, écran bleu 0x7E du 2026-09-30 lié au pilote NVIDIA).
- `transcript_fix` : **1 appel réel `clipper.llm.ask` par modèle** (pas
  `clipper.transcribe.transcribe()`, qui aurait découpé en tranches de
  `fix_chunk_words`) — les mots des deux extraits de ce modèle, concaténés
  dans l'ordre (`7VaA8XUKrAY` puis `v2887271276`), envoyés en une seule
  requête (2649 mots pour `small`, 2625 pour `large-v3-turbo`, sous la
  fenêtre `fix_chunk_words=3000` par défaut). Backend et modèle réels de
  `config.toml` (racine du dépôt, pas le worktree) : `claude-cli`, usage
  `transcript_fix` non surchargé donc niveau `fast` (sonnet).
- Divergences : `difflib.SequenceMatcher` mot à mot (casse ignorée) entre les
  deux modèles, sur le texte brut whisper (avant `transcript_fix`) ; 10
  passages par extrait, ±4 mots de contexte.

**Choix d'interprétation (clause ambiguë du critère, journalisé dans
`ank log`)** : « nombre et coût réel des corrections transcript_fix sur
chaque version (1 appel réel par version) » — lu comme 1 appel par **modèle**
(small vs large-v3-turbo), sur les mots des deux extraits combinés, plutôt
que 1 appel par (modèle × extrait) qui aurait fait 4 appels. Conséquence :
les chiffres de correction ci-dessous ne distinguent pas quel extrait a
généré quelle correction.

## Résultats — transcription

| Modèle | Extrait | temps | x temps réel | mots | langue (proba) |
|---|---|---:|---:|---:|---:|
| `small` | `7VaA8XUKrAY` | 12.2 s | 49.1x | 2156 | fr (0.9946) |
| `small` | `v2887271276` | 3.7 s | 162.0x | 493 | fr (0.9912) |
| `large-v3-turbo` | `7VaA8XUKrAY` | 18.9 s | 31.7x | 2150 | fr (0.9990) |
| `large-v3-turbo` | `v2887271276` | 5.7 s | 105.2x | 475 | fr (0.9976) |

| Modèle | chargement | **pic VRAM** |
|---|---:|---:|
| `small` | 2.4 s | **1393 MiB** |
| `large-v3-turbo` | 72.3 s (téléchargement HF inclus, une fois) | **3291 MiB** |

`large-v3-turbo` reste ~2-3x plus rapide que le temps réel (31–105x) donc
largement suffisant pour le pipeline, mais transcrit ~1.5-1.6x plus lentement
que `small` (moins de trous/mots perdus, cohérent avec un modèle plus gros).
La probabilité de langue détectée est systématiquement plus haute avec
`large-v3-turbo` (0.999 vs 0.991–0.995).

## Résultats — `transcript_fix` (1 appel réel par modèle)

| Modèle | mots envoyés | corrections renvoyées | appliquées | refusées (index/mot ne correspond pas) | coût réel |
|---|---:|---:|---:|---:|---:|
| `small` | 2649 | 34 | 31 | 3 | 0.4324 $ |
| `large-v3-turbo` | 2625 | 11 | 9 | 2 | 0.1874 $ |

`large-v3-turbo` a besoin de **3x moins de corrections** (11 vs 34) et coûte
**57 % moins cher** en `transcript_fix` sur cet échantillon — cohérent avec
une transcription whisper de départ plus propre.

## Divergences (20 passages, `small` vs `large-v3-turbo`, texte brut whisper)

### `7VaA8XUKrAY` (débat TV, parole FR dense)

| `small` | `large-v3-turbo` |
|---|---|
| qui était ouverte sur la base | ouverte sur la base |
| sur la base de signalement et de plaintes de | sur la base de signalements et de plaintes de |
| plaintes de femmes qui **trahaient** comme masseuses dans des | plaintes de femmes qui **travaillaient** comme masseuses dans des |
| dans des instituts de soins. Ça a forcément envoyé | dans des instituts de soins, ça a forcément envoyé |
| forcément envoyé un signal négatif, ça a dit quoi | forcément envoyé un signal négatif. Ça a dit quoi |
| rien à voir, classement **s'ensuite**. Sa carrière à lui | rien à voir, classement **sans suite**. Sa carrière à lui |
| carrière à lui a continué, sans **ambush**. Il a | carrière à lui a continué sans **embûche**. Il a |
| lui a continué, sans **ambush**. Il a été présent | lui a continué sans **embûche**. Il a été présent |
| Le message envoyé, c'est, moi je continue ma | Le message envoyé, c'est moi je continue ma |
| moi je continue ma vie, et vous, vous avez | moi je continue ma vie et vous, vous avez |

Sur cet extrait, `large-v3-turbo` corrige sans exception des erreurs réelles
de `small` : deux hallucinations lexicales franches (« trahaient » →
« travaillaient », « sans ambush » → « sans embûche »), une confusion
homophonique (« classement s'ensuite » → « classement sans suite »), le reste
étant de la ponctuation plus cohérente. Aucune régression observée sur cet
extrait.

### `v2887271276` (stream de jeu)

| `small` | `large-v3-turbo` |
|---|---|
| Numbeur 16. C'est où | Number 16. C'est où |
| 16. C'est où Numbeur 16 ? Tu m | 16. C'est où number 16 ? Tu m |
| 'avait vu. Je disais donc, c'est où Numbeur | 'avait vu. Je disais donc. C'est où number |
| donc, c'est où Numbeur 16 ? Numbeur 15. | donc. C'est où number 16 ? Number 15. |
| où Numbeur 16 ? Numbeur 15. Burger King. Foot | où number 16 ? Number 15. Burger King. **Foute** |
| Numbeur 15. Burger King. **Foot Lettuce**. Ah non mais là... Ah | Number 15. Burger King. **Foute l'étuce**. Non mais là. Mais |
| Lettuce. Ah non mais là... Ah mais c'est pareil, | l'étuce. Non mais là. Mais c'est pareil. |
| Ah mais c'est pareil, il a qu'à regarder ! 16. Qu'est-ce | là. Mais c'est pareil. 16. **Where is 16** |
| 'à regarder ! 16. Qu'est-ce qu'il y a ? Bah ouais, ça | c'est pareil. 16. Where is 16 ? Bah ouais. **Saligo**. |
| y a ? Bah ouais, ça **l'igo**. Heu... Peut-être **me île**. | is 16 ? Bah ouais. Saligo. Peut-être **me heal**. |

Sur cet extrait, résultat mitigé voire dégradé : ni « Numbeur » (small) ni
« Number »/« number » (large-v3-turbo) ne sont corrects (le locuteur dit
vraisemblablement « numéro »), mais `large-v3-turbo` **code-switch vers
l'anglais** à plusieurs reprises (« Number », « Where is 16 »), ce qui est
linguistiquement plus faux dans un contexte où le reste de la phrase est en
français. « Foot Lettuce » (small, au moins deux mots reconnaissables) devient
« Foute l'étuce » (large-v3-turbo, non-sens). Seul « me heal » (vs « me île »)
est potentiellement un gain si le locuteur utilisait vraiment un anglicisme
de jeu vidéo (« heal » = soigner), mais ça reste une hypothèse, pas une
lecture certaine du contexte.

## Analyse VRAM

Seuil du critère : marge suffisante si pic VRAM `large-v3-turbo` < 3,2 Go.
**3291 MiB = 3,21 Go (binaire) — au-dessus du seuil**, quelle que soit la
convention (décimale : 3291 MiB ≈ 3,45 Go ; binaire : 3291 / 1024 ≈ 3,21 Go).
Sur une carte à 4096 MiB total, ça laisse ~800 MiB de marge pour l'OS, le
pilote et tout autre processus GPU pendant la transcription — nettement moins
confortable que les ~2,7 Go de marge de `small` (1393 MiB pic).

## Recommandation

**Garder `small` comme modèle par défaut** (`CONFIG_DEFAULTS["model"]`
inchangé dans `clipper/transcribe.py`). Les deux conditions du critère de
bascule ne sont pas réunies simultanément :

- **VRAM** : `large-v3-turbo` dépasse le seuil de marge (3291 MiB > 3,2 Go),
  sur la carte 4 Go de la machine de développement — pas la marge « large »
  que `small` offre aujourd'hui (1,68 Go mesuré en usage réel,
  `docs/benchmarks/rtx3050.md`).
- **Qualité** : gain net et sans réserve sur la parole dense et propre
  (`7VaA8XUKrAY` : hallucinations lexicales corrigées, 3x moins de
  corrections `transcript_fix` nécessaires, coût de correction divisé par
  2,3), mais résultat mitigé à dégradé sur le stream de jeu
  (`v2887271276` : code-switching vers l'anglais, mots inventés) — or une
  bonne partie du contenu traité par ce pipeline est du stream de jeu
  (format SPEC-76dc). Le gain n'est donc pas généralisable à tout le
  catalogue de vidéos.

`large-v3-turbo` reste une option valable **au cas par cas** (vidéo de parole
propre type débat/interview, sans autre modèle lourd en VRAM en parallèle) :
transcription et VRAM restent dans des ordres de grandeur utilisables (19 s
pour 10 min, 3,21 Go pic), mais ça n'en fait pas un défaut sûr pour toutes
les vidéos du pipeline. Pas de changement de `CONFIG_DEFAULTS["model"]`, pas
de nouveau test unitaire requis (condition du critère non remplie) ;
`config.example.toml` mis à jour avec un renvoi vers ce document pour un
usage ponctuel opt-in.

Données brutes : `research/whisper-banc/{small,large-v3-turbo}.json`
(segments complets), `research/whisper-banc/fix-*.json` (réponses
`transcript_fix`), `research/whisper-banc/diffs.json`, `results.json`,
`run.log` (dossier local, ignoré par git).
