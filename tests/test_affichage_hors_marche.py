"""L'affichage terminal separe ce qui est sur de ce qui est a verifier.

Meme raison que la notification (ADR 0004) : une hors marche a la decote la
plus forte sans avoir la meilleure credibilite, et le nombre annonce en tete
sert a decider si on lit la suite.
"""
import pandas as pd
import main


def _deals(lignes):
    cols = ["Secteur", "Surface", "Pieces", "Prix", "Estimation", "Decote",
            "Source", "Fiable", "HorsMarche", "Lien"]
    return pd.DataFrame(lignes, columns=cols)


def test_affichage_separe_les_hors_marche(capsys):
    deals = _deals([
        ["Vannes", 50, 3, 600, 750, -20.0, "paruvendu", True, False, "https://ex.fr/normal"],
        ["Vannes", 45, 2, 550, 1800, -70.0, "seloger", True, True, "https://ex.fr/doute"],
    ])
    main.afficher_deals(deals)
    sortie = capsys.readouterr().out

    assert "1 BON(S) PLAN(S)" in sortie          # le compte ne gonfle pas
    assert "1 À VÉRIFIER" in sortie
    assert sortie.index("https://ex.fr/normal") < sortie.index("https://ex.fr/doute")


def test_affichage_inchange_sans_hors_marche(capsys):
    deals = _deals([
        ["Vannes", 50, 3, 600, 750, -20.0, "paruvendu", True, False, "https://ex.fr/1"],
    ])
    main.afficher_deals(deals)
    sortie = capsys.readouterr().out

    assert "1 BON(S) PLAN(S)" in sortie
    assert "VÉRIFIER" not in sortie
