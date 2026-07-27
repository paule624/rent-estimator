"""Extraction du Secteur depuis un titre paruvendu.

paruvendu n'expose aucun code postal (cf docs/adr/0002) : le titre est son seul
signal géographique. Les titres ci-dessous sont relevés sur le site.
"""
import scrap
import secteur


def test_titre_paris_donne_l_arrondissement():
    assert secteur.depuis_titre("Appartement 52 m2 Paris 15") == "Paris 15e"


def test_titre_donne_l_arrondissement_dans_toutes_les_villes_qui_en_ont():
    # Titres releves sur paruvendu pour Lyon et Marseille : le format est
    # exactement celui de Paris. Une ville ajoutee a
    # VILLES_A_ARRONDISSEMENTS doit etre lue par cet extracteur, sinon elle
    # scrape mais perd son Secteur.
    assert secteur.depuis_titre("Appartement 83 m2 Lyon 8") == "Lyon 8e"
    assert secteur.depuis_titre("Appartement 76 m2 Lyon 9") == "Lyon 9e"
    assert secteur.depuis_titre("Appartement 22 m2 Marseille 6") == "Marseille 6e"
    assert secteur.depuis_titre("Appartement 39 m2 Marseille 10") == "Marseille 10e"


def test_titre_et_cp_concordent_hors_paris():
    assert secteur.depuis_titre("Appartement 83 m2 Lyon 8") == secteur.depuis_cp("69008", "Lyon")
    assert secteur.depuis_titre("Appartement 39 m2 Marseille 10") == secteur.depuis_cp("13010", "Marseille")


def test_rang_hors_plage_n_est_pas_un_arrondissement():
    # Lyon s'arrete au 9e, Paris au 20e. Un rang au-dela vient d'autre chose
    # que d'un arrondissement (numero de rue, lot) : ne pas fabriquer un
    # Secteur fantome que le One-Hot prendrait pour une categorie.
    assert secteur.depuis_titre("Appartement 30 m2 Lyon 12") is None
    assert secteur.depuis_titre("Appartement 30 m2 Paris 25") is None


def test_titre_commune_donne_la_commune():
    # Le departement varie d'une annonce a l'autre dans un meme run (92, 93,
    # 94...) : l'extraction ne doit pas le comparer a celui de la ville cherchee.
    assert secteur.depuis_titre("Maison 79 m2 Antony (92)") == "Antony"
    assert secteur.depuis_titre("Appartement 29 m2 Saint-Denis (93)") == "Saint-Denis"
    assert secteur.depuis_titre("Appartement 37 m2 Languidic (56)") == "Languidic"


def test_titre_et_cp_donnent_le_meme_secteur():
    # Les deux extracteurs alimentent la meme colonne : un meme arrondissement
    # doit rendre le meme libelle, sinon le One-Hot le coupe en deux.
    assert secteur.depuis_titre("Studio 18 m2 Paris 1") == secteur.depuis_cp("75001", "Paris")
    assert secteur.depuis_titre("Appartement 52 m2 Paris 15") == secteur.depuis_cp("75015", "Paris")


def test_titre_sans_surface_est_une_limite_assumee():
    # ~4 % des titres paruvendu n'ont pas de surface ("Appartement
    # Boulogne-Billancourt (92)"). On ne les resout pas : sans surface,
    # nettoyage_donnees les jette de toute facon au dropna. Les resoudre
    # imposerait de distinguer le type de bien de la commune (les deux sont
    # capitalises), pour zero annonce gagnee.
    assert secteur.depuis_titre("Appartement Boulogne-Billancourt (92)") is None
    assert secteur.depuis_titre("Atelier Villepinte (93)") is None


def test_titre_illisible_ne_donne_pas_de_secteur():
    assert secteur.depuis_titre("Appartement 3 pieces a louer") is None
    assert secteur.depuis_titre("") is None
    assert secteur.depuis_titre(None) is None
