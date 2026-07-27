"""Construction des URLs de recherche paruvendu.

Une ville ordinaire = une recherche. Une ville a arrondissements = une
recherche par arrondissement, seule facon d'obtenir une donnee propre par
Secteur (cf docs/adr/0002).
"""
from types import SimpleNamespace

import sources


def _ville():
    return SimpleNamespace(nom="Vannes", slug="vannes", cp="56000", insee="56260",
                           dept="56", lat=47.65, lng=-2.76)


def test_ville_ordinaire_donne_une_seule_recherche():
    urls = sources._urls_paruvendu("Vannes", "vannes", "56000", "56260", km=10)
    assert len(urls) == 1
    assert "vannes-56000" in urls[0]
    assert "codeINSEE=56260" in urls[0]


def test_paris_donne_une_recherche_par_arrondissement():
    # geo.api.gouv.fr rend l'INSEE de la commune Paris (75056), que paruvendu
    # ne connait pas : il faut les INSEE d'arrondissement (751NN).
    urls = sources._urls_paruvendu("Paris", "paris", "75056", "75056", km=0)
    assert len(urls) == 20
    assert "paris-75001" in urls[0] and "codeINSEE=75101" in urls[0]
    assert "paris-75011" in urls[10] and "codeINSEE=75111" in urls[10]
    assert "paris-75020" in urls[19] and "codeINSEE=75120" in urls[19]
    # L'INSEE de la commune ne doit apparaitre dans aucune recherche.
    assert not any("codeINSEE=75056" in u for u in urls)


def test_lyon_et_marseille_ont_leurs_propres_bases_insee():
    lyon = sources._urls_paruvendu("Lyon", "lyon", "69123", "69123", km=0)
    assert len(lyon) == 9
    assert "lyon-69001" in lyon[0] and "codeINSEE=69381" in lyon[0]

    marseille = sources._urls_paruvendu("Marseille", "marseille", "13055", "13055", km=0)
    assert len(marseille) == 16
    assert "marseille-13001" in marseille[0] and "codeINSEE=13201" in marseille[0]


def test_ouestfrance_sans_budget_n_a_pas_de_filtre_prix():
    # Un budget laisse vide veut dire "sans plafond" : le filtre prix doit
    # disparaitre de l'URL, pas s'y ecrire "prix=0_None".
    sans = SimpleNamespace(ville="Vannes", km=10, prix_max=None)
    url = sources.urls_ouestfrance(sans, _ville())[0]
    assert "prix=" not in url
    assert "rayon=10" in url

    avec = SimpleNamespace(ville="Vannes", km=10, prix_max=700)
    assert "prix=0_700" in sources.urls_ouestfrance(avec, _ville())[0]


def test_le_rayon_passe_par_lol_pas_par_ray():
    # `ray` est inerte cote paruvendu : ray=10 et ray=50 rendent le meme
    # resultat. Tout le rayon passe par `lol`.
    url = sources._urls_paruvendu("Vannes", "vannes", "56000", "56260", km=10)[0]
    assert "lol=10" in url
    assert "ray=" not in url
