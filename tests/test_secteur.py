import scrap


def test_secteur_paris_est_l_arrondissement():
    assert scrap.cp_vers_secteur("75011", "Paris") == "Paris 11e"


def test_secteur_premier_arrondissement_s_ecrit_1er():
    assert scrap.cp_vers_secteur("75001", "Paris") == "Paris 1er"
    assert scrap.cp_vers_secteur("69001", "Lyon") == "Lyon 1er"


def test_secteur_lyon_est_l_arrondissement():
    assert scrap.cp_vers_secteur("69003", "Lyon") == "Lyon 3e"


def test_secteur_marseille_est_l_arrondissement():
    assert scrap.cp_vers_secteur("13008", "Marseille") == "Marseille 8e"


def test_secteur_ville_sans_arrondissement_est_la_commune():
    assert scrap.cp_vers_secteur("56000", "Vannes") == "Vannes"
    assert scrap.cp_vers_secteur("56890", "Saint-Avé") == "Saint-Avé"
    # Le Morbihan (56) est hors plage malgré sa proximité avec Lyon (69) : on
    # ne matche pas sur le département mais sur la plage exacte.
    assert scrap.cp_vers_secteur("69100", "Villeurbanne") == "Villeurbanne"


def test_secteur_paris_16e_a_deux_codes_postaux():
    # Le 16e est le seul arrondissement à porter deux CP (75016 et 75116) :
    # les deux doivent donner le même Secteur, sinon le modèle le coupe en deux.
    assert scrap.cp_vers_secteur("75016", "Paris") == "Paris 16e"
    assert scrap.cp_vers_secteur("75116", "Paris") == "Paris 16e"


def test_secteur_sans_cp_retombe_sur_la_commune():
    # Une source qui n'expose pas le CP ne doit pas faire tomber le run :
    # l'annonce retombe sur sa commune (à Paris = "Paris", donc hors
    # comparaison par arrondissement — perte assumée, cf docs/adr/0002).
    assert scrap.cp_vers_secteur(None, "Vannes") == "Vannes"
    assert scrap.cp_vers_secteur("", "Vannes") == "Vannes"
    assert scrap.cp_vers_secteur("n/c", "Vannes") == "Vannes"
    assert scrap.cp_vers_secteur(None, "Paris") == "Paris"


def test_secteur_accepte_un_cp_relu_depuis_le_csv():
    # Le CP transite par Data_Loyer.csv : dès qu'une ligne n'a pas de CP,
    # pandas lit toute la colonne en float64 et rend 75011.0, pas "75011".
    assert scrap.cp_vers_secteur(75011.0, "Paris") == "Paris 11e"
    assert scrap.cp_vers_secteur(75011, "Paris") == "Paris 11e"
    assert scrap.cp_vers_secteur(float("nan"), "Vannes") == "Vannes"
