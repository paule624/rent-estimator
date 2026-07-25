# Une annonce hors marché est évaluée, mais n'entraîne pas le modèle

Le filtre anti-aberration écartait les 2,5 % d'annonces les moins chères au m²
avant toute estimation. Or une annonce sous-cotée est, par définition,
anormalement peu chère au m² : le filtre travaillait contre l'outil, sur
exactement la population qu'il cherche. Désormais ces annonces sont **évaluées
et affichées, mais retirées de l'entraînement** — trop douteuses pour enseigner,
trop intéressantes pour être jetées.

## Contexte

Mesuré sur un corpus Paris de 1 359 annonces brutes (569 après nettoyage), avec
des bornes calées à 25,2 – 59,3 €/m² :

| Sort | Nombre |
| --- | --- |
| Hors du clamp absolu `3 – 60 €/m²` | 125 |
| Sous la borne basse (percentile 2,5) | 12 |
| Au-dessus de la borne haute (percentile 97,5) | 12 |
| Dans le marché observé | 420 |

Les 12 du bas se scindent en deux moitiés nettes. Six sous 22 €/m² —
`Maison 64 m² Paris 12 à 665 €`, `Appartement 12 m² Paris 8 à 170 €` — sont
invraisemblables à Paris : erreurs de lecture ou logements qui ne relèvent pas du
marché libre. Six entre 21 et 25,2 €/m² — `89 m² Paris 19 à 2 069 €`,
`124 m² Paris 16 à 2 900 €` — sont parfaitement crédibles, sous-cotées de 20 à
40 %, et c'était exactement la cible de l'outil.

La tension est réelle des deux côtés. Sans borne basse, une erreur de parsing
(cf le bug `_num` sur l'espace fine U+202F) produit un €/m² absurde, le modèle
apprend dessus, et tout le marché finit par paraître sous-coté. Avec la borne
basse, une vraie affaire disparaît avant d'être estimée.

L'asymétrie observée penche d'un côté : **12 annonces coupées en bas contre 137
en haut**. Les erreurs de lecture gonflent bien plus souvent qu'elles ne
dégonflent.

## Décision

Trois sorts au lieu de deux, sur deux populations au lieu d'une :

| Zone | Sort |
| --- | --- |
| Sous le plancher absolu `3 €/m²` | **Jetée.** Erreur de lecture quasi certaine |
| Entre le plancher et les percentiles | **Hors marché** : évaluée, pas entraînée |
| Dans les percentiles | Entraînée **et** évaluée |

Le mot *aberration* ne vaut plus que pour le plancher absolu, qui seul jette
encore. (Le plafond symétrique de la version initiale est tombé — voir la
révision en fin d'ADR.)

La zone hors marché est **symétrique**. Une annonce chère n'est pas forcément
aberrante : dans un secteur cossu et peu représenté, elle sort du percentile
global du run sans rien avoir d'anormal. Le coût de la symétrie est nul, mesuré :
les 12 hors marché du haut ressortent avec une décote positive et sont éliminées
par le seuil `-15 %`. Aucune ne pollue les bons plans.

Une annonce hors marché reste un **Bon plan** au sens du glossaire si sa décote
le justifie — c'est un marqueur, pas une troisième catégorie.

## Conséquences

**Deux chemins de prédiction.** Le marché observé garde `cross_val_predict`
(hors-pli) ; les hors marché passent par `model.predict()` sur le modèle
entraîné sur le marché observé. Le risque de fuite a été vérifié et ne tient
pas : une annonce hors marché n'est pas dans l'entraînement, sa prédiction est
donc du hors-échantillon franc, de même nature que le hors-pli. Les décotes
restent comparables.

**Les hors marché monopolisent la tête du classement.** Leur décote est
mécaniquement la plus forte : sur le corpus Paris, 6 des 10 premiers bons plans
sont hors marché, et ce sont les six douteux, pas les six crédibles. Combiné au
plafond de 5 messages par notification, le classement par décote seule
remplirait la notif de ce dont on doute le plus et tronquerait les vrais bons
plans. Elles vont donc dans un **bloc séparé en fin de notification**, et le
résumé les **compte à part** (`3 bon(s) plan(s) · 2 à vérifier`) — le titre est
ce qui décide si la notification est ouverte, il ne doit pas gonfler.

**`Fiable` se compte sur le marché observé seul.** Le comptage par secteur
portait sur toute la population ; c'était juste tant qu'il n'y en avait qu'une.
Sinon une annonce hors marché seule dans son secteur se compterait elle-même et
passerait pour fiable, alors que son One-Hot sort à zéro et que son estimation
ignore la localisation. Les deux marqueurs s'empilent sans hiérarchie : l'un
doute du prix affiché, l'autre de l'estimation.

**Les percentiles restent à 2,5 % / 97,5 %.** Aucune métrique ne peut arbitrer
cette valeur : un jeu de test tiré du cœur du marché récompense toujours
l'entraînement le plus étroit, et construire un test honnête supposerait de
connaître le vrai loyer des annonces litigieuses, ce qui est précisément la
question. Mesuré et écarté pour cette raison : à 15 %, le R² monte à 0,946 sans
que le modèle soit meilleur. Le seuil devient d'ailleurs secondaire — ce qu'il
écarte revient par l'autre porte. À revoir sur observation terrain, pas sur
métrique.

## Alternatives écartées

**Ne mettre le percentile qu'en haut**, en laissant le clamp absolu seul en bas.
Bien moins de code, une seule population. Écartée : elle laisserait la
`Maison 64 m² Paris 12 à 665 €` entrer dans l'**entraînement**, ce que la borne
basse existait précisément pour empêcher. Elle traite le symptôme en rouvrant la
cause.

**Trier les hors marché avec les autres**, simplement marquées. Une seule liste,
un seul concept. Écartée pour la raison ci-dessus : la troncature des
notifications, décidée juste avant, deviendrait un tirage au sort défavorable.

**Plafonner leur nombre** (3 maximum). Écartée : limite la casse sans rien
résoudre, et le plafond serait arbitraire.

## Révision du 2026-07-25 — le plafond absolu tombe

La version initiale gardait un clamp symétrique `3 – 60 €/m²` qui **jetait** des
deux côtés, et signalait en dette que le plafond « deviendrait le filtre actif à
Paris ». Mesuré depuis : il jetait **125 logements sur 569, soit 22 % du marché
parisien**. Pas des anomalies — `Paris 10e, 45 m², 2 711 €` à 60,2 €/m², et des
studios de 9 à 16 m² entre 70 et 90 €/m², ordinaires dans cette ville. Le clamp
faisait donc à Paris exactement ce que cet ADR refuse au percentile : supprimer
des logements réels avant toute estimation, et des deux populations à la fois.

**Le plafond est retiré. Le plancher à 3 €/m² reste.** L'asymétrie tient à ce
que chaque erreur produit :

- Une lecture trop **basse** fabrique un faux bon plan spectaculaire — le bug
  `_num` sur l'espace fine, « 4 600 € » lu 4. Elle doit être arrêtée avant de
  sortir.
- Une lecture trop **haute** ne fabrique rien : sa décote est positive, le seuil
  `-15 %` l'élimine. Son seul dégât possible était d'entraîner le modèle, et le
  percentile l'en empêche déjà en la marquant hors marché.

Conséquence mesurée : Paris entraîne sur 539 annonces au lieu de 420, et la
borne haute du marché observé passe de 59,3 à 106,6 €/m² — non parce que des
valeurs absurdes sont entrées dans le calcul, mais parce qu'un cinquième du
marché en était exclu. Vannes ne bouge pas d'un chiffre (8,2 – 23,0 dans les
deux cas), ce qui était la condition pour toucher à ce réglage.

## Dette relevée en passant, non traitée ici

- ~~`dropna(subset=["Pieces"])` supprime 741 lignes sur 1 319 du corpus Paris.~~
  **Faux, corrigé le 2026-07-25.** Ventilation de ces 741 lignes par titre : 405
  bureaux, 223 boutiques et « autres », 94 locaux, 18 parkings, 1 entrepôt.
  **Zéro logement.** Ce `dropna` ne perdait pas de données, il rattrapait les
  non-logements du bug corrigé par la révision de l'ADR 0003. Sur un corpus
  Vannes il coûte 3 lignes sur 68, dues à un « Pièce » au singulier chez
  Ouest-France, corrigé depuis.
