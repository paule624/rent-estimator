"""Chaque recherche a son sous-dossier dans output/.

Sans cloisonnement, un run sur Paris écrase les données de Vannes, et les deux
historiques se mélangent : la détection des nouveautés comparerait un marché à
un autre.
"""
import os

import pytest

import config
import historique


@pytest.fixture(autouse=True)
def recherche_neutre():
    yield
    config.definir_recherche(None)


def test_sans_recherche_tout_reste_a_la_racine():
    config.definir_recherche(None)
    assert config.dossier_run() == config.DOSSIER_SORTIE


def test_une_recherche_ouvre_son_sous_dossier():
    config.definir_recherche("Vannes-2")
    assert config.dossier_run() == os.path.join(config.DOSSIER_SORTIE, "vannes-2")
    assert config.chemin_donnees().endswith(os.path.join("vannes-2", "Data_Loyer.csv"))
    assert config.chemin_deals().endswith(os.path.join("vannes-2", "Appartement_interessant.csv"))
    assert config.chemin_cache().endswith(os.path.join("vannes-2", "cache_of.json"))


def test_deux_recherches_ne_partagent_pas_leur_historique():
    config.definir_recherche("Vannes-2")
    vannes = config.chemin_historique()
    config.definir_recherche("Paris")
    assert config.chemin_historique() != vannes


def test_l_historique_suit_la_recherche_en_cours():
    """historique.py lit son chemin à l'usage, pas à l'import."""
    config.definir_recherche("Vannes-2")
    assert "vannes-2" in historique.chemin()
    config.definir_recherche("Paris")
    assert "paris" in historique.chemin()


def test_un_nom_de_profil_devient_un_nom_de_dossier_sur():
    config.definir_recherche("Saint-Avé / test 2")
    assert os.sep not in os.path.relpath(config.dossier_run(), config.DOSSIER_SORTIE)


def test_un_nom_vide_ne_cree_pas_de_sous_dossier():
    config.definir_recherche("///")
    assert config.dossier_run() == config.DOSSIER_SORTIE
