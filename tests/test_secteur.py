import scrap
import secteur


def test_secteur_paris_est_l_arrondissement():
    assert secteur.depuis_cp("75011", "Paris") == "Paris 11e"


def test_secteur_premier_arrondissement_s_ecrit_1er():
    assert secteur.depuis_cp("75001", "Paris") == "Paris 1er"
    assert secteur.depuis_cp("69001", "Lyon") == "Lyon 1er"


def test_secteur_lyon_est_l_arrondissement():
    assert secteur.depuis_cp("69003", "Lyon") == "Lyon 3e"


def test_secteur_marseille_est_l_arrondissement():
    assert secteur.depuis_cp("13008", "Marseille") == "Marseille 8e"


def test_secteur_ville_sans_arrondissement_est_la_commune():
    assert secteur.depuis_cp("56000", "Vannes") == "Vannes"
    assert secteur.depuis_cp("56890", "Saint-Avé") == "Saint-Avé"
    # Le Morbihan (56) est hors plage malgré sa proximité avec Lyon (69) : on
    # ne matche pas sur le département mais sur la plage exacte.
    assert secteur.depuis_cp("69100", "Villeurbanne") == "Villeurbanne"


def test_secteur_paris_16e_a_deux_codes_postaux():
    # Le 16e est le seul arrondissement à porter deux CP (75016 et 75116) :
    # les deux doivent donner le même Secteur, sinon le modèle le coupe en deux.
    assert secteur.depuis_cp("75016", "Paris") == "Paris 16e"
    assert secteur.depuis_cp("75116", "Paris") == "Paris 16e"


def test_secteur_sans_cp_retombe_sur_la_commune():
    # Une source qui n'expose pas le CP ne doit pas faire tomber le run :
    # l'annonce retombe sur sa commune (à Paris = "Paris", donc hors
    # comparaison par arrondissement — perte assumée, cf docs/adr/0002).
    assert secteur.depuis_cp(None, "Vannes") == "Vannes"
    assert secteur.depuis_cp("", "Vannes") == "Vannes"
    assert secteur.depuis_cp("n/c", "Vannes") == "Vannes"
    assert secteur.depuis_cp(None, "Paris") == "Paris"


def test_secteur_ouestfrance_vient_du_cp_de_l_url():
    # L'URL Ouest-France porte le CP ("vannes-56-56260") : c'est une source a
    # CP, elle passe donc par la regle CP -> Secteur (cf docs/adr/0002).
    href = ("https://www.ouestfrance-immo.com/immobilier/location/appartement/"
            "vannes-56-56260/2-pieces-1.htm")
    assert secteur.depuis_url_of(href) == "Vannes"
    assert secteur.depuis_url_of("/immobilier/location/maison/saint-ave-56-56890/t3-2.htm") == "Saint Ave"
    # Meme URL dans une ville a arrondissements -> le CP prend le dessus.
    assert secteur.depuis_url_of("/immobilier/location/appartement/paris-75-75011/x.htm") == "Paris 11e"
    assert secteur.depuis_url_of("url/sans/commune") is None


def test_secteur_accepte_un_cp_relu_depuis_le_csv():
    # Le CP transite par Data_Loyer.csv : dès qu'une ligne n'a pas de CP,
    # pandas lit toute la colonne en float64 et rend 75011.0, pas "75011".
    assert secteur.depuis_cp(75011.0, "Paris") == "Paris 11e"
    assert secteur.depuis_cp(75011, "Paris") == "Paris 11e"
    assert secteur.depuis_cp(float("nan"), "Vannes") == "Vannes"
