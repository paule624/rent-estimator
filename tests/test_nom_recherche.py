"""Le compartiment porte le nom de la Recherche, pas du dernier Profil ouvert.

Une recherche lancee sans etre sauvee heritait du nom du dernier profil : un run
Pontivy atterrissait dans output/vannes-2/, ecrasait ses donnees et melangeait
les deux historiques — exactement ce que le cloisonnement doit empecher.
"""
import main


VANNES = {"ville": "Vannes", "km": 10, "prix_max": 700,
          "surface_min": 34, "canal": "discord"}
PONTIVY = {"ville": "Pontivy", "km": 0, "prix_max": None,
           "surface_min": None, "canal": "terminal"}


def _profils(monkeypatch, sauves, dernier):
    monkeypatch.setattr(main.config, "get_profil", lambda n: sauves.get(n))
    monkeypatch.setattr(main.config, "get_dernier_profil", lambda: dernier)


def test_profil_rejoue_donne_son_nom(monkeypatch):
    _profils(monkeypatch, {"Vannes-2": VANNES}, "Vannes-2")
    assert main._nom_recherche(VANNES) == "Vannes-2"


def test_recherche_non_sauvee_prend_sa_ville(monkeypatch):
    # Le dernier profil reste "Vannes-2" : la recherche Pontivy ne doit pas
    # emprunter son compartiment.
    _profils(monkeypatch, {"Vannes-2": VANNES}, "Vannes-2")
    assert main._nom_recherche(PONTIVY) == "Pontivy"


def test_premiere_recherche_sans_aucun_profil(monkeypatch):
    _profils(monkeypatch, {}, None)
    assert main._nom_recherche(PONTIVY) == "Pontivy"
