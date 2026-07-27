"""Le Secteur : la maille géographique sur laquelle le modèle apprend le prix.

Il vaut l'arrondissement dans les villes qui en ont, la commune partout
ailleurs (cf CONTEXT.md et docs/adr/0002). Chaque source l'expose à sa façon —
code postal, URL, titre, adresse de carte — d'où quatre extracteurs.

Ils vivent ensemble parce qu'ils partagent un invariant que rien d'autre ne
tient : **un même Secteur doit rendre la même clé quelle que soit la source**.
Deux écritures différentes du même lieu font deux catégories One-Hot, chacune
apprenant sur la moitié des annonces, et la comparaison entre Secteurs — la
raison d'être du modèle — se perd sans que rien ne le signale.
"""
import re
import unicodedata

# Villes à arrondissements. Toute leur surface est une seule commune INSEE,
# donc le nom de commune ne discrimine rien : c'est l'arrondissement qui porte
# le prix. Voir docs/adr/0002.
#   cp     : plage des codes postaux d'arrondissement (identifie un Secteur)
#   insee  : INSEE du 1er arrondissement, les suivants s'incrémentent de 1.
#            paruvendu ne connaît QUE ces INSEE, pas celui de la commune
#            (75056 pour Paris) que rend geo.api.gouv.fr.
VILLES_A_ARRONDISSEMENTS = {
    "Paris": {"cp": (75001, 75020), "insee": 75101},
    "Lyon": {"cp": (69001, 69009), "insee": 69381},
    "Marseille": {"cp": (13001, 13016), "insee": 13201},
}

# Le 16e arrondissement de Paris porte deux CP (75016 et 75116). Sans cet
# alias, 75116 tomberait hors plage et couperait le 16e en deux secteurs.
ALIAS_CP = {75116: 75016}


def cle(nom):
    """Clé One-Hot d'un Secteur : la forme sous laquelle le modèle le compare.

    Sans accents, sans casse, et surtout **sans dépendre du séparateur** : le
    slug d'une URL Ouest-France se relit "Saint Ave" là où les deux autres
    sources écrivent "Saint-Avé". Ne réduire que les accents laissait ces deux
    graphies former deux catégories distinctes — le modèle apprenait deux fois
    un demi-marché sur la même commune, et chaque moitié passait sous le seuil
    de fiabilité."""
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _libelle_arrondissement(ville, rang):
    """Libellé unique d'un arrondissement, partagé par tous les extracteurs :
    un même arrondissement doit rendre la même chaîne."""
    return f"{ville} {rang}{'er' if rang == 1 else 'e'}"


def depuis_cp(cp, commune):
    """Secteur d'une annonce dont la source expose un code postal : c'est la
    voie par défaut, stable et non ambiguë. Voir docs/adr/0002."""
    try:
        # via float() : pandas rend un CP relu du CSV en float (75011.0)
        # dès qu'une ligne de la colonne est vide.
        code = int(float(cp))
    except (TypeError, ValueError):
        return commune          # source sans CP exploitable
    code = ALIAS_CP.get(code, code)
    for ville, plages in VILLES_A_ARRONDISSEMENTS.items():
        debut, fin = plages["cp"]
        if debut <= code <= fin:
            return _libelle_arrondissement(ville, code - debut + 1)
    return commune


def depuis_url_of(href):
    """Secteur depuis une URL Ouest-France, qui porte commune ET code postal :
    '.../appartement/vannes-56-56260/...' -> 'Vannes'."""
    if not href:
        return None
    m = re.search(r"/([a-zà-ÿ\-]+)-\d{2}-(\d{5})/", href)
    if not m:
        return None
    return depuis_cp(m.group(2), m.group(1).replace("-", " ").title())


def depuis_titre(titre):
    """Secteur depuis un titre paruvendu, seule source géo de ce site.
    Ex "Appartement 52 m2 Paris 15" -> "Paris 15e".

    Le format est identique dans les trois villes à arrondissements (relevé sur
    le site) : on les balaie toutes plutôt que de coder Paris en dur. Un rang
    hors plage ne désigne pas un arrondissement, on le laisse au cas commune.
    """
    if not titre:
        return None
    for ville, plages in VILLES_A_ARRONDISSEMENTS.items():
        m = re.search(rf"\b{ville}\s+(\d{{1,2}})\b", titre)
        if not m:
            continue
        rang = int(m.group(1))
        debut, fin = plages["cp"]
        if 1 <= rang <= fin - debut + 1:
            return _libelle_arrondissement(ville, rang)
    # "<type> <surface> m2 <Commune> (<dept>)" — le dept varie d'une annonce
    # a l'autre, on ne le contraint pas.
    m = re.search(r"m[²2]\s+(.+?)\s*\(\s*\d{2,3}\s*\)", titre)
    return m.group(1).strip() if m else None


def depuis_adresse(adresse):
    """Secteur depuis une adresse de carte SeLoger, qui porte le code postal :
    'Zone Rurale Nord Ouest, Vannes (56000)' -> 'Vannes'.

    Le quartier qui précède la commune est ignoré : la maille du modèle est
    l'arrondissement, pas le quartier (cf CONTEXT.md)."""
    if not adresse:
        return None
    m = re.search(r"([^,]+?)\s*\((\d{5})\)\s*$", adresse)
    if not m:
        return None
    return depuis_cp(m.group(2), m.group(1).strip())
