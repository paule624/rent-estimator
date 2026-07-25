import pandas as pd
import model


def _ecrire_csv(tmp_path, lignes):
    cols = ["Prix", "Surface", "Secteur", "Pieces", "DPE", "Titre", "Lien", "Source"]
    p = tmp_path / "data.csv"
    pd.DataFrame(lignes, columns=cols).to_csv(p, index=False)
    return str(p)


def test_normalise():
    assert model._normalise("Saint-Avé") == "saint-ave"
    assert model._normalise("VANNES") == "vannes"
    assert model._normalise("Séné") == "sene"


def test_nettoyage_vire_colocations(tmp_path):
    lignes = [
        [500, 40, "Vannes", 2, 4, "Appartement 40 m2 Vannes", "u1", "paruvendu"],
        [400, 65, "Vannes", 4, 4, "Chambre en Colocation 65 m2 Vannes", "u2", "ouestfrance"],
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 1
    assert "Colocation" not in df.iloc[0]["Titre"]


def test_nettoyage_deduplique(tmp_path):
    # Même bien sur deux sources → une seule ligne
    lignes = [
        [600, 50, "Vannes", 3, 4, "Maison 50 m2 Vannes", "u1", "paruvendu"],
        [600, 50, "Vannes", 3, 4, "Location maison 50 m2 Vannes", "u2", "ouestfrance"],
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 1


def test_nettoyage_impute_dpe_manquant(tmp_path):
    lignes = [
        [500, 40, "Vannes", 2, 4, "Appt 40 m2 Vannes", "u1", "paruvendu"],
        [520, 42, "Séné", 2, None, "Appt 42 m2 Séné", "u2", "ouestfrance"],
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 2               # la ligne sans DPE n'est PAS jetée
    assert df["DPE"].notna().all()    # DPE imputé


def test_nettoyage_garde_un_marche_parisien(tmp_path):
    # Les bornes ne doivent pas etre calees sur un marche precis : a 30-40
    # €/m², Paris etait integralement jete par un plafond fixe a 30.
    lignes = [[1400, 40, f"Paris {i}e", 2, 4, f"Appt 40 m2 Paris {i}e", f"u{i}", "paruvendu"]
              for i in range(1, 21)]                       # 35 €/m²
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 20


def test_nettoyage_filtre_outliers(tmp_path):
    lignes = [
        [500, 40, "Vannes", 2, 4, "Appt 40 m2 Vannes", "u1", "paruvendu"],     # 12.5 €/m² OK
        [5000, 40, "Vannes", 2, 4, "Appt luxe 40 m2 Vannes", "u2", "paruvendu"],  # 125 €/m² outlier
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 1
