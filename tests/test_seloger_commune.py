"""Recherche SeLoger sur une commune seule (--km 0).

Cette branche passait par la forme par commune `immo-{slug}-{dept}/`, qui ne
porte aucun filtre de type de bien. Un run sur Paris a rendu 1200 annonces dont
405 bureaux, 94 locaux commerciaux et 18 parkings — 43 % de non-logements
scrapés, puis jetés au nettoyage faute de nombre de pièces.
"""
import base64
import json

import scrap


def _zone(url):
    """Décode le paramètre `locations` d'une URL classified-search."""
    brut = url.split("locations=")[1].split("&")[0]
    return json.loads(base64.urlsafe_b64decode(brut + "=" * (-len(brut) % 4)))


def test_la_commune_seule_restreint_aux_logements(monkeypatch):
    monkeypatch.setattr(scrap, "_contour_commune", lambda insee: [(47.65, -2.75), (47.66, -2.74), (47.65, -2.75)])
    url = scrap.url_seloger("vannes", "56", 47.658, -2.760, 0, insee="56260")
    assert "estateTypes=Apartment,House" in url
    assert "distributionTypes=Rent" in url


def test_la_commune_seule_porte_son_contour(monkeypatch):
    contour = [(47.65, -2.75), (47.66, -2.74), (47.65, -2.75)]
    monkeypatch.setattr(scrap, "_contour_commune", lambda insee: contour)
    zone = _zone(scrap.url_seloger("vannes", "56", 47.658, -2.760, 0, insee="56260"))
    assert zone["polyline"] == scrap._polyline(contour)
    assert zone["radius"] == 0


def test_sans_contour_on_retombe_sur_la_forme_par_commune(monkeypatch):
    """Le repli reste : mieux vaut des bureaux à trier que zéro annonce."""
    monkeypatch.setattr(scrap, "_contour_commune", lambda insee: None)
    url = scrap.url_seloger("vannes", "56", 47.658, -2.760, 0, insee="56260")
    assert url == "https://www.seloger.com/immobilier/locations/immo-vannes-56/"


def test_le_rayon_reste_un_cercle():
    zone = _zone(scrap.url_seloger("vannes", "56", 47.658, -2.760, 10, insee="56260"))
    assert zone["radius"] == 10
    assert zone["polyline"] == scrap._polyline(scrap._cercle(47.658, -2.760, 10))


def test_le_contour_est_echantillonne_et_referme(monkeypatch):
    """1210 points pour Vannes : l'URL doit rester d'une taille raisonnable."""
    anneau = [[-2.79 + i / 10000, 47.67 + i / 10000] for i in range(1210)]
    monkeypatch.setattr(scrap, "_geojson_commune",
                        lambda insee: {"type": "Polygon", "coordinates": [anneau]})
    points = scrap._contour_commune("56260")
    assert len(points) <= scrap.CONTOUR_MAX_POINTS + 1
    assert points[0] == points[-1]
    # GeoJSON donne (lng, lat) ; on travaille en (lat, lng).
    assert points[0] == (47.67, -2.79)


def test_une_commune_avec_des_iles_garde_son_anneau_principal(monkeypatch):
    grand = [[-2.79 + i / 1000, 47.67] for i in range(50)]
    ilot = [[-3.0, 47.5], [-3.01, 47.51], [-3.0, 47.5]]
    monkeypatch.setattr(scrap, "_geojson_commune",
                        lambda insee: {"type": "MultiPolygon", "coordinates": [[ilot], [grand]]})
    points = scrap._contour_commune("56260")
    assert len(points) > len(ilot)


def test_une_api_muette_ne_fait_pas_planter(monkeypatch):
    monkeypatch.setattr(scrap, "_geojson_commune", lambda insee: None)
    assert scrap._contour_commune("56260") is None
