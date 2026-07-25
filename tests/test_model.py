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


def test_nettoyage_deduplique_malgre_une_surface_au_dixieme(tmp_path):
    # SeLoger donne la surface au dixieme (50,4 m²), paruvendu a l'entier.
    # Sans arrondi dans la cle, le meme bien compte double et sur-pondere les
    # annonces multi-diffusees dans l'apprentissage.
    lignes = [
        [600, 50, "Vannes", 3, 4, "Maison 50 m2 Vannes", "u1", "paruvendu"],
        [600, 50.4, "Vannes", 3, 4, "Maison a louer Vannes", "u2", "seloger"],
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 1


def test_nettoyage_garde_la_surface_exacte(tmp_path):
    # L'arrondi sert la cle de dedoublonnage, pas les donnees : le modele
    # apprend sur la surface reelle.
    lignes = [
        [600, 50.4, "Vannes", 3, 4, "Maison a louer Vannes", "u1", "seloger"],
        [700, 62.8, "Vannes", 3, 4, "Appartement a louer Vannes", "u2", "seloger"],
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert set(df["Surface"]) == {50.4, 62.8}


def test_nettoyage_impute_dpe_manquant(tmp_path):
    lignes = [
        [500, 40, "Vannes", 2, 4, "Appt 40 m2 Vannes", "u1", "paruvendu"],
        [520, 42, "Séné", 2, None, "Appt 42 m2 Séné", "u2", "ouestfrance"],
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 2               # la ligne sans DPE n'est PAS jetée
    assert df["DPE"].notna().all()    # DPE imputé


def test_le_modele_n_apprend_pas_sur_les_hors_marche(tmp_path):
    # Une hors marche est gardee pour etre evaluee, pas pour enseigner : si une
    # erreur de lecture entrainait le modele, tout le marche paraitrait sous-cote.
    lignes = [[600 + i, 50, "Vannes", 3, 4, f"Appt {i} Vannes", f"u{i}", "paruvendu"]
              for i in range(40)]
    lignes.append([200, 50, "Vannes", 3, 4, "Appt brade Vannes", "z1", "paruvendu"])
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert df["HorsMarche"].any()          # le cas est bien construit

    _, x, y = model.model_entrainement(df)

    assert len(x) == len(y) == int((~df["HorsMarche"]).sum())
    assert not df.loc[x.index, "HorsMarche"].any()


def test_hors_marche_est_evaluee_mais_classee_apres_le_marche(tmp_path):
    # Sa decote est mecaniquement la plus forte : sans tri dedie, elle prendrait
    # la tete de la notif et tronquerait les vrais bons plans (cf ADR 0004).
    lignes = ([[600 + i, 50, "Vannes", 3, 4, f"Appt {i} Vannes", f"v{i}", "paruvendu"]
               for i in range(20)]                              # Vannes ~12 €/m²
              + [[900 + i, 50, "Séné", 3, 4, f"Appt {i} Séné", f"s{i}", "paruvendu"]
                 for i in range(20)]                            # Séné ~18 €/m²
              + [[620, 50, "Séné", 3, 4, "Appt sous-cote Séné", "deal", "paruvendu"]]
              + [[200, 50, "Vannes", 3, 4, "Appt brade Vannes", "z1", "paruvendu"]])
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    m, x, y = model.model_entrainement(df)
    deals = model.bon_plan(m, x, y, df, budget_max=None, surface_min=None)

    par_lien = deals.set_index("Lien")
    assert "deal" in par_lien.index                    # bon plan du marche observe
    assert "z1" in par_lien.index                      # hors marche, evaluee quand meme
    assert par_lien.loc["z1", "Estimation"] > 0
    assert par_lien.loc["z1", "Decote"] < par_lien.loc["deal", "Decote"]   # decote plus forte
    assert deals["Lien"].tolist().index("deal") < deals["Lien"].tolist().index("z1")


def test_secteur_trop_mince_est_marque_pas_masque(tmp_path):
    # Un secteur sous le seuil ne disparait pas des bons plans : il est montre
    # avec l'aveu d'incertitude. Masquer reviendrait a cacher une piste.
    lignes = ([[1400 + i * 30, 40 + i, "Paris 15e", 2, 4,
                f"Appt Paris 15e {i}", f"a{i}", "paruvendu"] for i in range(10)]
              + [[900, 40, "Paris 5e", 2, 4, "Appt Paris 5e", "b1", "paruvendu"]])
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    m, x, y = model.model_entrainement(df)
    deals = model.bon_plan(m, x, y, df, budget_max=None, surface_min=None)

    assert "Fiable" in deals.columns
    par_secteur = dict(zip(deals["Secteur"], deals["Fiable"]))
    assert par_secteur.get("Paris 5e") is False    # 1 annonce -> sous le seuil
    if "Paris 15e" in par_secteur:
        assert par_secteur["Paris 15e"] is True    # 10 annonces -> fiable


def test_fiable_se_compte_sur_le_marche_observe(tmp_path):
    # Un secteur ou rien n'a entraine sort un One-Hot a zero : l'estimation
    # ignore la localisation. Compter les hors marche le ferait passer pour
    # fiable alors qu'elles se comptent elles-memes (cf ADR 0004).
    # 200 annonces de marche : il en faut assez pour que le percentile 2,5 %
    # puisse couper les 6 de Séné sans les diluer.
    lignes = ([[600 + i, 50, "Vannes", 3, 4, f"Appt {i} Vannes", f"v{i}", "paruvendu"]
               for i in range(200)]
              + [[300 + i, 50, "Séné", 3, 4, f"Appt brade {i} Séné", f"s{i}", "paruvendu"]
                 for i in range(6)])          # 6 annonces, mais toutes hors marche
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert df[df["Secteur"] == "Séné"]["HorsMarche"].all()

    m, x, y = model.model_entrainement(df)
    deals = model.bon_plan(m, x, y, df, budget_max=None, surface_min=None)

    sene = deals[deals["Secteur"] == "Séné"]
    assert len(sene) > 0                       # montrees, jamais masquees
    assert not sene["Fiable"].any()            # 6 annonces, 0 apprise -> pas fiable


def test_nettoyage_garde_un_marche_parisien(tmp_path):
    # Les bornes ne doivent pas etre calees sur un marche precis : a 30-40
    # €/m², Paris etait integralement jete par un plafond fixe a 30.
    lignes = [[1400, 40, f"Paris {i}e", 2, 4, f"Appt 40 m2 Paris {i}e", f"u{i}", "paruvendu"]
              for i in range(1, 21)]                       # 35 €/m²
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 20


def test_annonce_sous_le_marche_est_marquee_pas_jetee(tmp_path):
    # Une annonce sous-cotee est, par definition, anormalement peu chere au m² :
    # la jeter revenait a supprimer la cible de l'outil (cf ADR 0004).
    lignes = [[600 + i, 50, "Vannes", 3, 4, f"Appt {i} Vannes", f"u{i}", "paruvendu"]
              for i in range(40)]                               # ~12 €/m², le marche
    lignes.append([200, 50, "Vannes", 3, 4, "Appt brade Vannes", "z1", "paruvendu"])  # 4 €/m²
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))

    par_lien = df.set_index("Lien")
    assert "z1" in par_lien.index                  # gardee
    assert bool(par_lien.loc["z1", "HorsMarche"])  # mais marquee
    assert not bool(par_lien.loc["u20", "HorsMarche"])


def test_annonce_hors_du_clamp_absolu_reste_jetee(tmp_path):
    # Deux sorts distincts : le clamp jette (erreur de lecture), le percentile
    # marque (prix douteux mais possible). A 1 €/m² il n'y a pas de doute.
    lignes = [[600 + i, 50, "Vannes", 3, 4, f"Appt {i} Vannes", f"u{i}", "paruvendu"]
              for i in range(40)]
    lignes.append([50, 50, "Vannes", 3, 4, "Appt illisible Vannes", "z1", "paruvendu"])
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))

    assert "z1" not in set(df["Lien"])


def test_nettoyage_filtre_outliers(tmp_path):
    lignes = [
        [500, 40, "Vannes", 2, 4, "Appt 40 m2 Vannes", "u1", "paruvendu"],     # 12.5 €/m² OK
        [5000, 40, "Vannes", 2, 4, "Appt luxe 40 m2 Vannes", "u2", "paruvendu"],  # 125 €/m² outlier
    ]
    df = model.nettoyage_donnees(_ecrire_csv(tmp_path, lignes))
    assert len(df) == 1
