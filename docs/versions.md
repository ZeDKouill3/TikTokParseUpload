# Versions de Clipper

Numérotation : versionnage sémantique, `MAJEUR.MINEUR.CORRECTIF`.

- `0.x.y` : en développement ; la config, les écrans et les fichiers d'état peuvent encore changer.
- `1.0.0` : première version stable ; une mise à jour ne casse plus la config ni les données sans migration automatique.
- Après 1.0.0 : `1.1.0` nouveauté compatible, `1.0.1` correction, `2.0.0` changement qui casse.

## Feuille de route

| Version | Contenu | Condition |
|---|---|---|
| v0.1.0 | Pipeline vidéo longue -> clips 9:16 (letterbox, stream), jury, sous-titres, première console | publiée |
| v0.2.0 | Console web v2 (tableau de bord, vidéos, clips, revue, chaînes, statistiques, réglages), écran Comptes (coffre de l'OS), grille gaming, confiance du jury, publication et statistiques TikTok par navigateur (testées en réel) | maintenant |
| v0.3.0 | Publication pilotée depuis l'écran Publication, « prêt à publier » automatique, corrections du sixième tour de la console | après ces tâches |
| v0.4.0 | Mode auto de bout en bout : vidéo en entrée, clips publiés sans intervention | après une semaine d'usage réel |
| v1.0.0 | Stable | quand tous les critères ci-dessous sont tenus |

## Critères de la v1.0.0

1. **Installation propre** : sur un PC neuf, suivre le README (`tools/setup.ps1`) mène à un premier clip publié, sans aide.
2. **Une semaine d'usage réel sans retouche du code** : vidéos traitées et clips publiés ; aucune perte silencieuse ni blocage sans raison affichée.
3. **Formats figés et documentés** : `config.toml`, presets de chaîne, fichiers d'état (`state/`, `workspace/<id>/pipeline.json`) et sidecars de clip ; tout changement ultérieur passe par une migration automatique.
4. **Tests** : suite complète verte, test de fumée réel (`CLIPPER_CLAUDE_INTEGRATION=1`) et test réel TikTok (`CLIPPER_TIKTOK_REAL=1`) verts sur la version publiée.
5. **Documentation** : README à jour (installation, chaînes, comptes, publication, risques TikTok) et journal des changements par version.
