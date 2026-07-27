"""Le registre des Sources pilote la moisson.

Trois sites, trois façons de naviguer, un seul contrat : une Source dit quelles
URLs la couvrent et sait lire une page de résultats. L'orchestrateur ne nomme
plus aucun site — avant, en ajouter un demandait de toucher la construction des
URLs, son déballage, et la boucle elle-même.
"""
from types import SimpleNamespace

import pandas as pd
import pytest

import sources


def _source(nom, urls, lire=None):
    return sources.Source(
        nom=nom,
        urls=lambda recherche, ville: urls,
        lire=lire or (lambda html: pd.DataFrame()),
        moissonner=lambda context, url, lire: pd.DataFrame(
            [[600, 50, "Vannes", 3, 4, url, url, nom]], columns=sources.COLONNES),
    )


def _recherche():
    return SimpleNamespace(ville="Vannes", km=10, prix_max=700)


def _ville():
    return SimpleNamespace(nom="Vannes", slug="vannes", cp="56000", insee="56260",
                           dept="56", lat=47.65, lng=-2.76)


def test_le_registre_pilote_la_moisson():
    faux = [_source("a", ["u1", "u2"]), _source("b", ["u3"])]
    df = sources.moissonner_toutes(object(), _recherche(), _ville(), sources=faux)
    assert list(df["Source"]) == ["a", "a", "b"]


def test_une_source_en_panne_ne_coute_que_la_sienne():
    """Une panne réseau sur un site ne doit pas emporter les deux autres : un
    run à deux sources sur trois vaut mieux qu'un run perdu."""
    casse = sources.Source(
        nom="casse", urls=lambda r, v: ["u"], lire=lambda html: pd.DataFrame(),
        moissonner=_exploser)
    df = sources.moissonner_toutes(object(), _recherche(), _ville(),
                                   sources=[casse, _source("b", ["u3"])])
    assert list(df["Source"]) == ["b"]


def _exploser(context, url, lire):
    raise RuntimeError("le site ne répond pas")


def test_aucune_annonce_ne_rend_rien_plutot_qu_une_erreur():
    vide = sources.Source(
        nom="vide", urls=lambda r, v: [], lire=lambda html: pd.DataFrame(),
        moissonner=_exploser)
    assert sources.moissonner_toutes(object(), _recherche(), _ville(),
                                     sources=[vide]) is None
