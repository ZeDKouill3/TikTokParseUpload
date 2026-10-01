# Maquette Statistiques TikTok

Ouvrir `index.html` dans le navigateur (`file://` suffit). Aucun réseau : le
style, les polices et les icônes sont ceux de `../maquette-web-v2/` (chemins
relatifs). Données factices, compte neutre `ma_chaine`.

- En haut : compte TikTok, chaîne Clipper liée, période 7 / 28 / 60 jours,
  date du dernier relevé, bouton « Relever maintenant » (relevé simulé).
- **Vue d'ensemble** : 5 tuiles avec évolution vs période précédente, courbe
  par jour (clic sur une tuile ou sur le sélecteur pour changer de métrique).
- **Publications** : tableau triable ; clic sur une ligne = détail du post
  (chiffres clés, rétention, sources de trafic ou « dès 100 vues », liens).
- Barre « Maquette » : montre les états Aucun relevé / Relevé en cours /
  Aucune publication. Le compte `@ma_chaine.tests` n'a jamais été relevé ;
  le premier post de `@ma_chaine.clips` est « en cours de traitement ».

Hash : `#/vue`, `#/publications`, `#/publications/<id>` ; paramètres
`?demo=empty|scanning|noposts`, `?acct=tests`, `?period=7|28|60`, `?shot=1`.
