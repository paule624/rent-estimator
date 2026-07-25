# SeLoger se cherche par contour, pas par identifiant de lieu

Une recherche SeLoger est décrite par le paramètre `locations` : le base64 d'un
JSON. Ce JSON doit porter un **`polyline`** — le contour de la zone cherchée,
encodé au format Google. Nous le **fabriquons** : un cercle de `--km` autour des
coordonnées de la ville, que `geo.api.gouv.fr` nous donne déjà.

`--km 0` (la commune seule) reste sur `classified-search` et porte le **contour
réel de la commune**, que `geo.api.gouv.fr` rend aussi. La forme par commune
`/immobilier/locations/immo-{slug}-{dept}/` n'est plus qu'un repli si l'API géo
est muette.

> **Révisé le 2026-07-25.** La première version faisait passer `--km 0` par la
> forme par commune, faute de zone à décrire quand le rayon est nul. Un run sur
> Paris a montré ce que cette forme coûte : elle ne porte aucun filtre de type
> de bien, et rendait **405 bureaux, 94 locaux commerciaux et 18 parkings sur
> 1200 annonces** — 43 % de non-logements, scrapés puis jetés au nettoyage
> faute de nombre de pièces. Le contour de la commune décrit une zone valide là
> où un cercle de rayon nul n'en décrit aucune, ce qui permet de rester sur la
> seule forme d'URL qui restreigne le type de bien. Vérifié en réel : Vannes
> 60/60 sans un seul bureau, Paris 58 logements sur 60 et zéro pièce manquante.

## Contexte

SeLoger est la troisième source, ajoutée pour densifier les villes où paruvendu
est mince : Paris n'y sortait que ~160 annonces, dont 9 secteurs sur 19 sous le
seuil de fiabilité (cf ADR 0002 et CONTEXT.md, *Estimation peu fiable*).

Trois formes d'URL ont été essayées sur le site réel :

| Forme | Résultat |
| --- | --- |
| `list.htm?places=[{"inseeCodes":[…]}]` | `ERR_HTTP_RESPONSE_CODE_FAILURE` — API retirée |
| `/immobilier/locations/immo-vannes-56/` | 125 annonces, **pas de rayon** |
| `/recherche/location/immobilier/bretagne/vannes-56000/` | 0 annonce en accès direct — ne vaut qu'en cible de redirection |
| `/classified-search?locations=<base64>` | la forme vivante, **avec rayon** |

Sur la dernière, le contenu de `locations` a été isolé champ par champ :

| Contenu de `locations` | Annonces |
| --- | --- |
| `{placeId, radius}` | **0** |
| `{placeId, coordinates}` | **0** |
| `{placeId, radius, polyline}` | 30 |
| `{radius, polyline}` — sans placeId | 30 |
| `{radius, polyline}` avec un polyline **calculé par nous** | 30 |

## Décision

Construire `locations` nous-mêmes, avec `radius` et un `polyline` calculé :
`_cercle()` produit le contour, `_polyline()` l'encode.

Conséquences directes :

- **Pas de résolution de lieu chez SeLoger.** Le `placeId` est facultatif, donc
  aucun appel à leur autocomplétion, aucun identifiant opaque à maintenir. Les
  coordonnées viennent de `geo.api.gouv.fr`, déjà interrogé pour l'INSEE.
- **`--km` est honoré exactement**, puisque c'est nous qui traçons le cercle.
- **Une seule recherche par ville, arrondissements compris.** Contrairement à
  paruvendu, chaque carte SeLoger porte son code postal : Paris se couvre en une
  URL au lieu de vingt, et `cp_vers_secteur` fait le reste (ADR 0002).

## Ce que le site impose par ailleurs

- **`pg=` est inerte** : il rend toujours la première page. La pagination passe
  par le bouton « page suivante », et par `dispatch_event("click")` — la page
  empile des habillages (consentement, promotions) qui interceptent un clic par
  coordonnées.
- **La bannière de consentement est retirée du DOM**, pas acceptée : le site ne
  propose pas de refus en un clic, et accepter le pistage à la place de
  l'utilisateur ne nous appartient pas. Le contexte navigateur est jetable.
- **Une panne de pagination ne coûte que les pages restantes.** Les pages déjà
  lues sont rendues telles quelles ; c'est ce qui distingue une source
  partiellement lue d'une source perdue.

## Alternatives écartées

**Rester sur la forme par commune** (sans rayon), en documentant que SeLoger
ignore `--km`. Écartée : le rayon est atteignable pour ~40 lignes de calcul, et
une source au périmètre différent des deux autres fausserait la comparaison
entre Secteurs. La révision de 2026-07-25 lui a retiré son dernier usage.

**Filtrer les non-logements après coup**, sur le titre, plutôt que dans l'URL.
Écartée : le tri se ferait bien, mais après avoir payé le scraping — 517
annonces inutiles sur Paris, soit près de la moitié du temps de la source. Le
site sait filtrer, autant le lui demander.

**Récupérer le polyline depuis le site** en pilotant son champ de recherche.
Écartée : plus lent, plus fragile, et inutile puisqu'un cercle calculé répond.

**Leboncoin et PAP** restent écartés (anti-bot, bruit C2C) — décisions
antérieures inchangées.
