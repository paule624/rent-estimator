import scrap


def test_num_extrait_nombre():
    assert scrap._num("700 €") == 700
    assert scrap._num("1 250 €") == 1250
    assert scrap._num("25 m²") == 25
    assert scrap._num("12,5") == 12.5
    assert scrap._num("") is None
    assert scrap._num(None) is None


def test_slug():
    assert scrap._slug("Vannes") == "vannes"
    assert scrap._slug("Saint-Avé") == "saint-ave"
    assert scrap._slug("Sainte-Anne-d'Auray") == "sainte-anne-d-auray"


def test_commune_paruvendu():
    assert scrap.commune_pv("Appartement 37 m2 Languidic (56)", "56") == "Languidic"
    assert scrap.commune_pv("Maison 120 m² Séné (56)", "56") == "Séné"
    assert scrap.commune_pv("Duplex 45 m2 Vannes (56)", "56") == "Vannes"
    assert scrap.commune_pv("texte sans commune", "56") is None
    assert scrap.commune_pv(None, "56") is None


def test_commune_ouestfrance():
    href = "https://www.ouestfrance-immo.com/immobilier/location/appartement/vannes-56-56260/2-pieces-1.htm"
    assert scrap.commune_of(href, "56") == "Vannes"
    href2 = "/immobilier/location/maison/saint-ave-56-56890/t3-2.htm"
    assert scrap.commune_of(href2, "56") == "Saint Ave"
    assert scrap.commune_of("url/sans/commune", "56") is None
