import scrap


def test_num_extrait_nombre():
    assert scrap._num("700 €") == 700
    assert scrap._num("1 250 €") == 1250
    assert scrap._num("25 m²") == 25
    assert scrap._num("12,5") == 12.5
    assert scrap._num("") is None
    assert scrap._num(None) is None


def test_num_lit_les_milliers_quel_que_soit_l_espace():
    # SeLoger separe les milliers par U+202F (espace fine insecable) et colle
    # U+00A0 avant l'euro. Sans les couvrir, "4 600 €" se lit 4 : un loyer
    # parisien passerait pour l'affaire du siecle.
    assert scrap._num("4 600 € /mois") == 4600
    assert scrap._num("2 450 €") == 2450
    assert scrap._num("1 250 €") == 1250


def test_slug():
    assert scrap._slug("Vannes") == "vannes"
    assert scrap._slug("Saint-Avé") == "saint-ave"
    assert scrap._slug("Sainte-Anne-d'Auray") == "sainte-anne-d-auray"


def test_nombre_pages_depuis_le_pied_de_liste():
    assert scrap._nombre_pages("Annonces 1 a 29 sur 934") == 33
    assert scrap._nombre_pages("Annonces 1 a 29 sur 58") == 3


def test_une_seule_page_quand_le_compteur_est_absent():
    # Une recherche qui tient en une page n'affiche aucun compteur : sans ce
    # repli, le scraper plantait sur toutes les recherches a faible volume
    # (typiquement un arrondissement avec lol=0).
    assert scrap._nombre_pages("Aucun compteur ici") == 1
    assert scrap._nombre_pages("") == 1
    assert scrap._nombre_pages(None) == 1


# L'extraction geographique est couverte par tests/test_secteur.py et
# tests/test_secteur_titre.py : commune_pv/commune_of ont ete remplacees par
# les extracteurs de Secteur (cf docs/adr/0002).
