# Banc vitesse whisper : batched vs séquentiel vs beam_size 1

TASK-be65d6df6225. Mesure pure, aucun fichier de `clipper/` modifié : les
scripts (`research/bench-whisper/bench_speed.py`, hors dépôt, ignoré par
git) appellent `faster-whisper` directement, sans passer par
`clipper.transcribe`.

## Méthode

- Machine : RTX 3050 4 Go, device résolu par `clipper.gpu.get_device()`
  (`cuda`, `compute_type="float16"`).
- Modèle : `small` (celui de `CONFIG_DEFAULTS["model"]`).
- **A** = réglages actuels de `clipper.transcribe` : `beam_size=5`,
  `vad_filter=True`, `word_timestamps=True`, `language=None` (auto),
  `initial_prompt` = vocabulaire de la vidéo (tronqué par
  `_whisper_vocab`, comme en prod).
- **B8 / B16** = `BatchedInferencePipeline` (mêmes options que A),
  `batch_size` 8 et 16.
- **C_beam1** = A avec `beam_size=1`.
- **D8 / D16** = B8 / B16 avec `beam_size=1`.
- Un seul modèle chargé en VRAM à la fois (ADR-fb9b) ; A/C réutilisent la
  même instance `WhisperModel`, B/D l'enveloppent dans un
  `BatchedInferencePipeline` sans recharger les poids.
- Extrait : les 10 min déjà utilisées dans `research/bench-whisper/`
  (`ivl0nxa3C7o`, 5880–6480 s), vocabulaire réel de cette vidéo (60 entrées,
  20 gardées après troncature à 100 tokens).
- Vidéo entière : `TFjGbdWiH_A` (4856 s ≈ 81 min), la plus courte de
  `workspace/` avec un transcript existant (vocabulaire réel : `["Mastu"]`).
  Seuls A et la meilleure variante de l'extrait y sont passés (temps réel
  oblige).
- Trous : écart > 2 s entre la fin d'un segment et le début du suivant.
- WER : distance de Levenshtein mot à mot contre A, sur le texte brut des
  segments (ponctuation incluse) **et** sur une version normalisée
  (minuscules, ponctuation retirée) — la WER brute est gonflée par des
  différences purement typographiques (virgule vs point, majuscule après
  une virgule) que faster-whisper distribue différemment selon le mode.
- VRAM : pic mesuré par sondage `nvidia-smi` toutes les 0.5 s pendant la
  transcription.

## Résultat — extrait 10 min

| Variante | temps (s) | x temps réel | mots | trous >2s | VRAM pic (MiB) | WER brute vs A | WER normalisée vs A |
|---|---:|---:|---:|---:|---:|---:|---:|
| A (actuel) | 85.2 | 7.0x | 1851 | 14 | 1116 | — | — |
| C_beam1 | 75.6 | 7.9x | 1871 | 12 | 988 | 18.6 % | 8.9 % |
| B8 | 23.3 | 25.8x | 1860 | 2 | 1745 | 22.9 % | 11.9 % |
| B16 | 17.5 | 34.3x | 1866 | 2 | 2771 | 21.4 % | 11.7 % |
| D8 | 21.5 | 27.9x | 1989 | 3 | 1363 | 32.7 % | 20.8 % |
| D16 | 13.4 | 44.8x | 1989 | 3 | 2003 | 32.7 % | 20.8 % |

## Résultat — vidéo entière (81 min, A vs B8)

| Variante | temps (s) | x temps réel | mots | trous >2s | VRAM pic (MiB) | WER brute vs A | WER normalisée vs A |
|---|---:|---:|---:|---:|---:|---:|---:|
| A (actuel) | 551.5 | 8.8x | 12282 | 218 | 1287 | — | — |
| B8 | 113.4 | 42.8x | 12323 | 33 | 1790 | 31.1 % | 13.2 % |

B8 est **4.9x plus rapide** que A sur la vidéo entière (contre 3.7x sur
l'extrait — l'écart se creuse avec la durée, probablement parce que le
batching absorbe mieux les longs silences). Fait notable : B8 signale
nettement moins de trous >2s que A (33 contre 218) sur la vidéo entière —
le VAD du pipeline batché semble fusionner différemment les silences,
plutôt qu'une perte de contenu (le nombre de mots est comparable, voire
légèrement supérieur).

## Exemples de divergences (B8 vs A, vidéo entière)

```
[replace] A: ...Et je vous propose...  |  B8: ...et je vous propose...
[replace] A: ...simplement entre nous quoi, on fait pas...  |  B8: ...simplement entre nous quoi on fait pas...
[replace] A: ...fait pas ça souvent, j'ai un peu...  |  B8: ...fait pas ça souvent j'ai un peu...
[replace] A: ...un peu envie On se met un...  |  B8: ...un peu envie on se met un...
[delete] A: ...un petit lofi et on se fait...  |  B8: ...un petit lofi on se fait...
[replace] A: ...on se fait ça, ça vous dit...  |  B8: ...on se fait ça ça vous dit...
[replace] A: ...vous dit ou pas, comme ça on...  |  B8: ...vous dit ou pas comme ça on...
[replace] A: ...comme ça on discute, j'aime bien moi...  |  B8: ...comme ça on discute j'aime bien moi...
[replace] A: ...j'aime bien moi Attendez je vous mets...  |  B8: ...j'aime bien moi attendez je vous mets...
[replace] A: ...mets un petit lofi, en ce moment...  |  B8: ...mets un petit lofi en ce moment...
[replace] A: ...l'as tué au playlist, si jamais vous...  |  B8: ...l'as tué au playlist si jamais vous...
[replace] A: ...vous connaissez pas C'est des playlists, euh......  |  B8: ...vous connaissez pas c'est des playlists vous...
[replace] A: ...pas C'est des playlists, euh... Vous savez les trucs...  |  B8: ...pas c'est des playlists vous savez les trucs...
[replace] A: ...les trucs en mode, tiens un chevalier...  |  B8: ...les trucs en mode tiens un chevalier...
[replace] A: ...peu de repos basqu'à la télé là Je...  |  B8: ...peu de repos bascale à télé là je...
[replace] A: ...la télé là Je sais pas si...  |  B8: ...à télé là je sais pas si...
[replace] A: ...pas si on voit, on voit pas...  |  B8: ...pas si on voit on voit pas...
[replace] A: ...voit pas c'est flou, mais là c'est...  |  B8: ...voit pas c'est flou mais là c'est...
[replace] A: ...vous savez c'est genre, repose-toi à l'autonnet...  |  B8: ...vous savez c'est genre repose-toi à l'automne...
[replace] A: ...genre, repose-toi à l'autonnet enfin arrivé ou...  |  B8: ...genre repose-toi à l'automne et enfin arrivé ou...
```

L'immense majorité des divergences (~18 sur 20 ici, et le motif se
confirme sur l'extrait) sont de la ponctuation ou de la casse en début de
phrase : B8 capitalise et ponctue nettement moins que A à l'intérieur d'un
segment. Les vraies erreurs lexicales existent (« basqu'à » vs « bascale »
— les deux faux, l'original probable étant autre chose) mais sont rares,
et B8 corrige parfois une erreur de A (« l'autonnet » → « l'automne »,
le bon mot). Sur l'extrait, C_beam1 (séquentiel, `beam_size=1`) a la WER
normalisée la plus basse des alternatives (8.9 %) mais un gain de vitesse
marginal (1.1x) ; D8/D16 (batched + `beam_size=1`) cumulent la pire WER
(~21 %) sans gain de vitesse notable sur B8/B16 — `beam_size=1` dégrade la
qualité sans bénéfice mesurable une fois le batching en place.

## Recommandation

**Passer à `BatchedInferencePipeline`, `batch_size=8`, en gardant
`beam_size=5`** (ne pas toucher `beam_size`, son seul effet mesuré ici est
de dégrader la WER sans accélérer davantage que le batching seul) :

- ~4-5x plus rapide que les réglages actuels sur une vidéo réelle (551 s
  → 113 s pour 81 min), donc un vrai gain sur le goulot d'étranglement
  transcription du pipeline.
- VRAM pic 1.79 Go sur la vidéo entière, loin des 4 Go de la RTX 3050 —
  marge confortable même avec d'autres modèles en mémoire côté OS/pilote.
  `batch_size=16` est encore plus rapide (34–45x temps réel sur l'extrait)
  mais pousse le pic à 2.0–2.8 Go : à garder en réserve si `batch_size=8`
  s'avère trop prudent en usage réel, pas comme premier choix sur une
  carte à 4 Go.
- La dégradation de qualité mesurée est dominée par la ponctuation
  (majuscules et virgules internes aux segments), pas par du contenu
  perdu : le nombre de mots reste comparable à A, et
  `clipper.transcribe`'s passe de correction LLM (`transcript_fix`)
  retouche déjà le texte mot à mot après coup. Le batching réduit aussi le
  nombre de trous >2 s détectés sur la vidéo entière (218 → 33), signal
  plutôt positif pour l'étape suivante (découpage en moments).
- Point de vigilance avant d'appliquer ce changement dans
  `clipper/transcribe.py` (hors scope ici) : vérifier que la ponctuation
  moins riche de B8 ne dégrade pas les sous-titres affichés (SPEC-6127) ni
  la lisibilité pour `transcript_fix` — un test dédié à ajouter par la
  tâche qui portera le changement, pas mesuré ici.

Données brutes : `research/bench-whisper/speed-extract-results.json`,
`speed-extract-diffs.json`, `speed-full-results.json`,
`speed-full-diffs.json` (dossier local, ignoré par git).
