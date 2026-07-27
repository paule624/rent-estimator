"""Un run complet, du marché moissonné aux Bons plans, sans navigateur.

C'est la seule couture qui manquait : le moissonnage était importé par son nom
dans main, donc rien ne pouvait le remplacer. Les seuls tests possibles
portaient sur des fonctions pures extraites pour la testabilité, pendant que
les vrais accidents — un CSV écrit ailleurs, une source qui perd ses studios,
un seuil qui déplace un marché — vivaient dans l'enchaînement.

Ici le moissonnage est un paramètre : un CSV tenu à la main remplace Chrome.
"""
import os

import pandas as pd
import pytest

import config
import recherche as module_recherche


@pytest.fixture(autouse=True)
def sortie_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_SORTIE", str(tmp_path))
    yield
    config.definir_recherche(None)


def _marche():
    """Un marché vannetais ordinaire (~12 €/m²) plus une affaire à -30 %."""
    lignes = [[600 + i, 50, "Vannes", 3, 4, f"Appt {i} Vannes", f"v{i}", "paruvendu"]
              for i in range(40)]
    lignes.append([420, 50, "Vannes", 3, 4, "Appt sous-cote Vannes", "deal", "paruvendu"])
    return pd.DataFrame(lignes, columns=["Prix", "Surface", "Secteur", "Pieces",
                                         "DPE", "Titre", "Lien", "Source"])


def _recherche(**kw):
    return module_recherche.Recherche(ville="Vannes", km=10, nom="essai", **kw)


def test_un_run_complet_se_rejoue_sans_navigateur():
    resultat = module_recherche.executer(_recherche(), moissonner=lambda r: _marche())

    assert "deal" in set(resultat.deals["Lien"])
    assert os.path.exists(resultat.chemin)


def test_le_premier_run_annonce_tout_comme_nouveau():
    resultat = module_recherche.executer(_recherche(), moissonner=lambda r: _marche())

    assert len(resultat.nouveaux) == len(resultat.deals)
    assert len(resultat.baisses) == 0


def test_le_second_run_ne_re_annonce_rien():
    """L'Historique est ce qui distingue un run du précédent : rejoué sur le
    même marché, un run ne doit plus rien signaler."""
    module_recherche.executer(_recherche(), moissonner=lambda r: _marche())
    resultat = module_recherche.executer(_recherche(), moissonner=lambda r: _marche())

    assert len(resultat.nouveaux) == 0
    assert len(resultat.baisses) == 0


def test_une_baisse_de_prix_est_signalee():
    module_recherche.executer(_recherche(), moissonner=lambda r: _marche())

    baisse = _marche()
    baisse.loc[baisse["Lien"] == "deal", "Prix"] = 380
    resultat = module_recherche.executer(_recherche(), moissonner=lambda r: baisse)

    assert list(resultat.baisses["Lien"]) == ["deal"]


def test_le_compartiment_est_ouvert_avant_la_moisson():
    """Chaque Recherche a son compartiment : sans lui, un run sur Paris écrase
    les données de Vannes et les deux historiques se mélangent. Il doit être
    en place AVANT le moissonnage, qui y écrit déjà son Data_Loyer.csv."""
    vus = []
    module_recherche.executer(
        _recherche(), moissonner=lambda r: vus.append(config.chemin_donnees()) or _marche())

    assert os.path.join("essai", "Data_Loyer.csv") in vus[0]
    assert os.path.join("essai", "Appartement_interessant.csv") in \
        os.path.abspath(config.chemin_deals())
    assert os.path.exists(config.chemin_historique())


def test_une_moisson_vide_ne_produit_pas_de_resultat():
    assert module_recherche.executer(_recherche(), moissonner=lambda r: None) is None


def test_le_budget_et_la_surface_de_la_recherche_sont_appliques():
    serree = _recherche(prix_max=400, surface_min=60)
    resultat = module_recherche.executer(serree, moissonner=lambda r: _marche())

    assert len(resultat.deals) == 0     # l'affaire est a 420 € et 50 m²
