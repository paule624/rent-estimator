"""Source SeLoger.

SeLoger ne resout un lieu que si l'URL porte un `polyline` : le contour de la
zone cherchee, encode au format Google (verifie en reel, cf docs/adr/0003).
Le placeId est facultatif, le polyline ne l'est pas. On fabrique donc le
cercle nous-memes a partir des coordonnees de la ville et de --km.
"""
import base64
import json
import math
import pathlib
import urllib.parse

import scrap


def _distance_km(a, b):
    """Distance approchée entre deux (lat, lng), suffisante pour vérifier un rayon."""
    lat_moy = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111.32,
                      (a[1] - b[1]) * 111.32 * math.cos(lat_moy))


def test_polyline_encode_au_format_google():
    # Exemple canonique de la doc Google Encoded Polyline Algorithm Format.
    # C'est SeLoger qui impose ce format : on ne peut pas en inventer un autre.
    assert scrap._polyline([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) \
        == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_cercle_couvre_le_rayon_demande():
    # Vannes, coordonnees geo.api.gouv.fr. Tous les points doivent tomber a la
    # distance demandee : c'est ce cercle que SeLoger utilise comme perimetre,
    # donc --km n'est honore que s'il est exact.
    centre = (47.6559, -2.7603)
    points = scrap._cercle(*centre, 10)
    assert all(abs(_distance_km(centre, p) - 10) < 0.2 for p in points)


def test_cercle_est_ferme():
    # Un contour ouvert n'est pas une zone : SeLoger ne le resout pas.
    centre = (47.6559, -2.7603)
    points = scrap._cercle(*centre, 10)
    assert points[0] == points[-1]
    assert len(points) > 8  # assez de points pour approcher un cercle


def _locations(url):
    """Décode le paramètre `locations` d'une URL SeLoger (base64 d'un JSON)."""
    brut = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["locations"][0]
    return json.loads(base64.urlsafe_b64decode(brut + "=" * (-len(brut) % 4)))


def test_url_porte_le_rayon_demande():
    url = scrap.url_seloger("vannes", "56", 47.6559, -2.7603, 10)
    zone = _locations(url)
    assert zone["radius"] == 10
    assert zone["polyline"]  # sans contour, SeLoger ne resout aucun lieu
    assert "distributionTypes=Rent" in url


def test_rayon_nul_cherche_la_commune_seule():
    # --km 0 est un choix legitime : chercher dans la commune, pas autour.
    # Un cercle de rayon nul n'est pas une zone et SeLoger ne rend rien ; la
    # forme par commune, elle, repond (verifie en reel). Voir docs/adr/0003.
    url = scrap.url_seloger("vannes", "56", 47.6559, -2.7603, 0)
    assert "locations=" not in url
    assert "immo-vannes-56" in url


def test_centre_lit_les_coordonnees_dans_le_bon_ordre():
    # geo.api.gouv.fr rend du GeoJSON : coordinates = [lng, lat], l'inverse de
    # l'ordre usuel. Inverser les deux enverrait la recherche en pleine mer
    # sans que rien ne plante.
    commune = {"nom": "Vannes", "code": "56260", "codesPostaux": ["56000"],
               "centre": {"type": "Point", "coordinates": [-2.7485, 47.6577]}}
    assert scrap._centre(commune) == (47.6577, -2.7485)


def _fixture(nom):
    return (pathlib.Path(__file__).parent / "fixtures" / nom).read_text()


def test_champs_d_une_annonce():
    # 1re carte de la fixture : "520 € /mois",
    # "2 pieces · 1 chambre · 83,2 m² · Etage 2/2".
    # Le piege est "1 chambre" : le nombre de pieces est 2, pas 1.
    df = scrap.annonces_seloger(_fixture("seloger_vannes.html"))
    premiere = df.iloc[0]
    assert premiere["Prix"] == 520
    assert premiere["Surface"] == 83.2   # SeLoger donne la surface au dixieme
    assert premiere["Pieces"] == 2
    assert premiere["Lien"].startswith("https://www.seloger.com/")


def test_lien_ne_traine_pas_la_recherche_derriere_lui():
    # SeLoger reinjecte toute la recherche dans le lien de chaque annonce,
    # polyline compris, plus un fragment de suivi : ~700 caracteres la ou 80
    # suffisent. Les bons plans partent par Telegram et Discord, ou une
    # poignee de liens pareils fait deborder le message.
    df = scrap.annonces_seloger(_fixture("seloger_vannes.html"))
    for lien in df["Lien"]:
        assert "?" not in lien and "#" not in lien
        assert lien.endswith(".htm")
        assert len(lien) < 120


def test_titre_ne_ramasse_pas_les_caracteristiques():
    # Le Titre nourrit le filtre anti-colocation de nettoyage_donnees, qui
    # cherche "coloc|chambre". Les caracteristiques SeLoger disent "1 chambre"
    # sur presque toutes les cartes : les laisser dans le Titre ferait jeter
    # la source entiere comme si c'etait de la colocation.
    df = scrap.annonces_seloger(_fixture("seloger_vannes.html"))
    assert df["Titre"].iloc[1] == "Appartement à louer"
    # ... sans pour autant perdre les vraies colocations, qui doivent partir.
    assert df["Titre"].iloc[0] == "Colocation à louer"


def test_secteur_hors_ville_a_arrondissements():
    # "Zone Rurale Nord Ouest, Vannes (56000)" : le quartier est ignore, la
    # maille reste la commune (cf CONTEXT.md, Secteur).
    df = scrap.annonces_seloger(_fixture("seloger_vannes.html"))
    assert set(df["Secteur"]) == {"Vannes"}


def test_secteur_est_l_arrondissement_a_paris():
    # "Auteuil Nord, Paris 16eme arrondissement (75016)" -> "Paris 16e", le
    # meme libelle que les autres sources, sinon le One-Hot coupe en deux.
    df = scrap.annonces_seloger(_fixture("seloger_paris.html"))
    assert set(df["Secteur"]) == {"Paris 16e", "Paris 15e"}
    assert df["Secteur"].iloc[0] == scrap.cp_vers_secteur("75016", "Paris")


def test_loyer_a_quatre_chiffres():
    # Fixture Paris, 1re carte : "4 600 € /mois" avec une espace fine
    # insecable entre les milliers. Lu 4, ce loyer passerait pour le bon plan
    # du siecle et remonterait en tete des resultats.
    df = scrap.annonces_seloger(_fixture("seloger_paris.html"))
    assert df["Prix"].iloc[0] == 4600


def test_contrat_de_sortie():
    # Les trois sources alimentent un meme concat : memes colonnes, meme ordre,
    # DPE deja traduit en note numerique (paruvendu le fait aussi).
    df = scrap.annonces_seloger(_fixture("seloger_vannes.html"))
    assert list(df.columns) == scrap.COLONNES
    assert set(df["Source"]) == {"seloger"}
    assert df["DPE"].iloc[0] == scrap.DPE_MAP["C"]


class _PageFictive:
    """Navigateur minimal : rend la fixture, puis casse a la pagination.

    On simule ici la frontiere externe (le navigateur), pas les rouages du
    scraper : ce qui est verifie reste un comportement observable.
    """

    def __init__(self, html):
        self.html = html

    def goto(self, *a, **k):
        pass

    def wait_for_timeout(self, *a, **k):
        pass

    def evaluate(self, *a, **k):
        pass

    def content(self):
        return self.html

    def locator(self, *a, **k):
        raise RuntimeError("le site a change de structure en cours de route")

    def close(self):
        pass


class _ContexteFictif:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


def test_une_panne_en_cours_de_pagination_ne_perd_pas_les_pages_lues():
    # Une banniere qui intercepte le clic suffit a faire echouer la pagination.
    # Rendre un resultat vide dans ce cas jette des annonces deja lues et
    # coute toute la source, alors que la premiere page etait bonne.
    page = _PageFictive(_fixture("seloger_vannes.html"))
    df = scrap.scrape_seloger(_ContexteFictif(page), "https://exemple")
    assert len(df) == 3


def test_page_sans_annonce_rend_le_contrat_vide():
    # Le concat de run_scraping ecarte les frames vides : encore faut-il
    # qu'elles portent les colonnes.
    df = scrap.annonces_seloger("<html><body>rien ici</body></html>")
    assert df.empty
    assert list(df.columns) == scrap.COLONNES
