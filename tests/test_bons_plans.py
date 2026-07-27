"""La partition marché observé / Hors marché (cf docs/adr/0004).

Elle décide de la mise en page du terminal ET de celle de la notification. Une
règle écrite deux fois se révise une fois : c'est exactement ce qui s'est passé
quand l'ADR 0004 a séparé les deux populations. Une seule implémentation, et une
seule forme pour l'absence — pas un DataFrame vide d'un côté, None de l'autre.
"""
import pandas as pd

import bons_plans


def _deals(hors):
    return pd.DataFrame({
        "Lien": [f"u{i}" for i in range(len(hors))],
        "Prix": [600] * len(hors),
        "HorsMarche": hors,
    })


def test_les_hors_marche_partent_a_part():
    marche, a_verifier = bons_plans.scinder(_deals([False, True, False]))
    assert list(marche["Lien"]) == ["u0", "u2"]
    assert list(a_verifier["Lien"]) == ["u1"]


def test_l_absence_a_toujours_la_meme_forme():
    """Aucun appelant ne doit avoir à distinguer « pas de colonne », « aucune
    hors marché » et « aucun bon plan » : les trois rendent des DataFrames
    vides, jamais None."""
    sans_colonne = pd.DataFrame({"Lien": ["u0"], "Prix": [600]})
    for deals in (None, pd.DataFrame(), sans_colonne, _deals([False])):
        marche, a_verifier = bons_plans.scinder(deals)
        assert isinstance(marche, pd.DataFrame)
        assert isinstance(a_verifier, pd.DataFrame)
        assert len(a_verifier) == 0


def test_une_colonne_absente_laisse_tout_dans_le_marche():
    marche, _ = bons_plans.scinder(pd.DataFrame({"Lien": ["u0"], "Prix": [600]}))
    assert list(marche["Lien"]) == ["u0"]


def test_le_terminal_et_la_notification_comptent_pareil(capsys):
    """Les deux sorties décrivent le même lot : si elles partitionnent
    différemment, le titre de la notif contredit l'écran sans que rien ne le
    signale."""
    import main
    import notif

    deals = pd.DataFrame(
        [["Vannes", 50, 3, 600, 750, -20.0, "paruvendu", True, False, "https://ex.fr/1"],
         ["Vannes", 45, 2, 550, 700, -21.0, "seloger", True, False, "https://ex.fr/2"],
         ["Vannes", 45, 2, 550, 1800, -70.0, "seloger", True, True, "https://ex.fr/3"]],
        columns=["Secteur", "Surface", "Pieces", "Prix", "Estimation", "Decote",
                 "Source", "Fiable", "HorsMarche", "Lien"])

    main.afficher_deals(deals)
    sortie = capsys.readouterr().out
    resume, _ = notif._construire(deals, None)

    assert "2 BON(S) PLAN(S)" in sortie and "2 nouveau(x) bon(s) plan(s)" in resume
    assert "1 À VÉRIFIER" in sortie and "1 à vérifier" in resume
