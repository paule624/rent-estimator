"""Les hors marche ne prennent pas la tete de la notification.

Leur decote est mecaniquement la plus forte sans etre la plus credible. Comme
la notification est plafonnee a 5 messages, les laisser en tete reviendrait a
tronquer les vrais bons plans au profit de ce dont on doute le plus (ADR 0004).
"""
import pandas as pd
import notif


def _deals(lignes):
    cols = ["Secteur", "Surface", "Prix", "Decote", "Lien", "Fiable", "HorsMarche"]
    return pd.DataFrame(lignes, columns=cols)


def test_le_resume_compte_les_hors_marche_a_part():
    nouveaux = _deals([
        ["Vannes", 50, 600, -20.0, "https://ex.fr/1", True, False],
        ["Vannes", 45, 550, -70.0, "https://ex.fr/2", True, True],
    ])
    resume, _ = notif._construire(nouveaux, None)

    assert "1 nouveau(x) bon(s) plan(s)" in resume
    assert "1 à vérifier" in resume


def test_les_hors_marche_ferment_le_message():
    nouveaux = _deals([
        ["Vannes", 50, 600, -20.0, "https://ex.fr/normal", True, False],
        ["Vannes", 45, 550, -70.0, "https://ex.fr/doute", True, True],
    ])
    _, corps = notif._construire(nouveaux, None)

    assert corps.index("https://ex.fr/normal") < corps.index("https://ex.fr/doute")
    assert "Hors marché" in corps


def test_sans_hors_marche_le_message_ne_change_pas():
    """Le cas courant — petit run Vannes — doit rester identique a avant."""
    nouveaux = _deals([["Vannes", 50, 600, -20.0, "https://ex.fr/1", True, False]])
    resume, corps = notif._construire(nouveaux, None)

    assert resume == "1 nouveau(x) bon(s) plan(s)"
    assert "vérifier" not in corps
    assert "Hors marché" not in corps
