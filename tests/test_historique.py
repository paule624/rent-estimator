import pandas as pd
import historique
import notif


def _deals(rows):
    cols = ["Lien", "Prix", "Secteur", "Surface", "Pieces", "Decote"]
    return pd.DataFrame(rows, columns=cols)


def test_detecter_tout_nouveau_si_historique_vide():
    deals = _deals([["u1", 500, "Vannes", 40, 2, -20]])
    nouveaux, baisses = historique.detecter(deals, pd.DataFrame(columns=historique.COLS))
    assert len(nouveaux) == 1
    assert len(baisses) == 0


def test_detecter_nouveau_lien():
    deals = _deals([["u1", 500, "Vannes", 40, 2, -20], ["u2", 600, "Séné", 50, 3, -15]])
    hist = pd.DataFrame([["u1", 500, "Vannes", 40, 2, -20, "2026-01-01"]], columns=historique.COLS)
    nouveaux, baisses = historique.detecter(deals, hist)
    assert set(nouveaux["Lien"]) == {"u2"}
    assert len(baisses) == 0


def test_detecter_baisse_de_prix():
    deals = _deals([["u1", 450, "Vannes", 40, 2, -28]])   # 450 < 500 vu avant
    hist = pd.DataFrame([["u1", 500, "Vannes", 40, 2, -20, "2026-01-01"]], columns=historique.COLS)
    nouveaux, baisses = historique.detecter(deals, hist)
    assert len(nouveaux) == 0
    assert set(baisses["Lien"]) == {"u1"}


def test_detecter_pas_de_baisse_si_prix_stable():
    deals = _deals([["u1", 500, "Vannes", 40, 2, -20]])
    hist = pd.DataFrame([["u1", 500, "Vannes", 40, 2, -20, "2026-01-01"]], columns=historique.COLS)
    nouveaux, baisses = historique.detecter(deals, hist)
    assert len(nouveaux) == 0
    assert len(baisses) == 0


def test_charger_historique_migre_l_ancienne_colonne_commune(tmp_path, monkeypatch):
    # Les historiques ecrits avant l'introduction du Secteur portent une
    # colonne "Commune" : on la migre a la lecture, sinon l'historique se
    # retrouve avec les deux colonnes a moitie vides.
    ancien = tmp_path / "historique.csv"
    pd.DataFrame(
        [["u1", 500, "Vannes", 40, 2, -20, "2026-01-01"]],
        columns=["Lien", "Prix", "Commune", "Surface", "Pieces", "Decote", "Date"],
    ).to_csv(ancien, index=False)
    monkeypatch.setattr(historique, "chemin", lambda: str(ancien))

    hist = historique.charger_historique()

    assert "Secteur" in hist.columns
    assert "Commune" not in hist.columns
    assert hist.iloc[0]["Secteur"] == "Vannes"


def test_notification_avoue_une_estimation_peu_fiable():
    # L'avertissement doit voyager jusqu'au canal : un bon plan pousse sur
    # Discord sans son doute se lit comme une certitude.
    cols = ["Lien", "Prix", "Secteur", "Surface", "Pieces", "Decote", "Fiable"]
    deals = pd.DataFrame(
        [["u1", 900, "Paris 5e", 40, 2, -22, False],
         ["u2", 800, "Paris 15e", 42, 2, -18, True]],
        columns=cols,
    )
    _, message = notif._construire(deals, None)

    ligne_5e = [l for l in message.split("\n\n") if "Paris 5e" in l][0]
    ligne_15e = [l for l in message.split("\n\n") if "Paris 15e" in l][0]
    assert "peu fiable" in ligne_5e.lower()
    assert "peu fiable" not in ligne_15e.lower()


def test_notification_sans_colonne_fiable_ne_plante_pas():
    # Un historique ou un export anterieur au marqueur n'a pas la colonne.
    cols = ["Lien", "Prix", "Secteur", "Surface", "Pieces", "Decote"]
    deals = pd.DataFrame([["u1", 900, "Vannes", 40, 2, -22]], columns=cols)
    _, message = notif._construire(deals, None)
    assert "Vannes" in message


def test_notifier_deals_vide_ne_plante_pas():
    # aucun deal → ne doit rien lever
    notif.notifier_deals(pd.DataFrame(), pd.DataFrame())
