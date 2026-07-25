# Le Secteur, dérivé du code postal quand la source l'expose

La maille géographique du modèle (le **Secteur**, clé One-Hot) vaut
l'**arrondissement** dans les villes qui en ont, la **commune** partout ailleurs.
Elle est dérivée du **code postal de l'annonce** — Paris 75001–75020, Lyon
69001–69009, Marseille 13001–13016 — pour les sources qui exposent un CP. Les
sources qui n'en exposent aucune (paruvendu) ont leur propre extracteur, qui
produit le même Secteur.

## Contexte

Le modèle apprend le prix par commune via un One-Hot sur `CommuneKey`, extrait du
**nom de commune** dans le titre de l'annonce. Ça marche partout sauf dans les
villes à arrondissements : Paris, Lyon et Marseille sont chacune **une seule
commune INSEE**. Toutes leurs annonces portent le même nom ("Paris") → One-Hot à
une catégorie → signal géographique mort. Or à Paris, l'arrondissement est le
premier facteur de prix (16e ≠ 19e), et c'est précisément ce qu'on veut comparer.

Le discriminant intra-Paris ne vit pas dans le nom (toujours "Paris") mais dans
le **code postal** (75011 → 11e). Deux façons de récupérer l'arrondissement se
présentaient : parser du texte par site, ou standardiser sur le code postal.

Une sonde sur paruvendu (juillet 2026) a tranché la question empiriquement :

- `codeINSEE=75056` (la commune Paris, ce que rend `geo.api.gouv.fr`) est
  **inconnu de paruvendu** → 0 annonce. Seuls les INSEE d'arrondissement
  fonctionnent : `paris-75011&codeINSEE=75111` → 957 annonces.
- Les cartes paruvendu **n'exposent aucun code postal** : ni dans le titre, ni
  dans le href (un identifiant opaque), ni dans le texte de la carte.
- `ray=0` **ne contraint pas** la recherche à l'arrondissement : une recherche
  "11e" rend Courbevoie (92), Le Blanc-Mesnil (93), Paris 14, Paris 15. On ne
  peut donc pas déduire le Secteur de l'arrondissement recherché.
- Densité mesurée sur 90 annonces : **17 % intra-muros**, réparties sur 10
  arrondissements (~1,6 annonce par arrondissement).
- `geo.api.gouv.fr` n'expose pas les arrondissements municipaux (404 sur
  l'endpoint dédié ; `codePostal=75011` rend "Paris / 75056").

Le seul signal géographique de paruvendu est donc le **titre**, dans deux formats
réguliers : `"Appartement 52 m2 Paris 15"` et `"Maison 79 m2 Antony (92)"`.

## Décision

Le **Secteur** est le concept unique sur lequel le modèle fait son One-Hot. Son
extraction dépend de ce que la source expose :

- **Sources exposant un CP** (SeLoger, Ouest-France dont l'URL porte le CP :
  `vannes-56-56260`) → règle unique `CP → Secteur` : CP dans une plage
  d'arrondissement (Paris 75001–75020, Lyon 69001–69009, Marseille 13001–13016)
  → Secteur = arrondissement ; sinon → Secteur = nom de commune.
- **paruvendu**, qui n'expose aucun CP → extracteur dédié sur le titre,
  produisant le même Secteur (`"Paris 15"` → `"Paris 15e"`, `"Antony (92)"` →
  `"Antony"`).

Le CP reste la voie par défaut là où il existe : il est stable et non ambigu, et
généralise sans effort aux trois villes à arrondissements. paruvendu est
l'exception constatée, pas la règle.

Le modèle ne voit qu'un Secteur unifié — aucune logique `if ville == Paris` en
aval de l'extraction.

## Conséquences

- **Schéma data** : la clé géo passe de `CommuneKey` (nom de commune) à un
  `Secteur` unifié. Les sources à CP propagent une colonne `CP`.
- **Deux extracteurs à maintenir** au lieu d'un. Le parseur de titre paruvendu
  est fragile par nature : il casse si paruvendu change le format de ses titres.
  C'est le prix de garder paruvendu comme source.
- **paruvendu est une source faible à Paris** : 17 % d'intra-muros, ~1,6 annonce
  par arrondissement par tranche de 90. Le gros de la donnée parisienne devra
  venir de SeLoger. Cela ne remet pas en cause paruvendu hors Paris, où il reste
  la source principale.
- **Le rayon `km` n'est pas fiable à Paris** : `ray=0` ne restreint pas la
  recherche à l'intra-muros côté paruvendu. Le cadrage géographique se fait donc
  en aval, sur le Secteur extrait, pas sur l'URL de recherche.
- L'ancienne extraction `commune_pv` est **inopérante en Île-de-France** : elle
  exige un `"(dept)"` que `"Paris 15"` n'a pas, et compare au département
  recherché (75), ce qui rejette aussi `"Antony (92)"`. Elle doit accepter
  n'importe quel département et le format `"Paris NN"`.
