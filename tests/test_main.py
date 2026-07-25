"""Saisie des criteres : un champ laisse vide vaut "pas de contrainte".

Les valeurs montrees en gris dans les prompts sont des exemples, pas des
valeurs appliquees : rien ne se glisse dans une recherche sans etre demande.
"""
import main


def test_champ_vide_vaut_aucune_contrainte():
    assert main.entier_ou_none("") is None
    assert main.entier_ou_none("   ") is None
    assert main.entier_ou_none(None) is None


def test_champ_rempli_donne_sa_valeur():
    assert main.entier_ou_none("700") == 700
    assert main.entier_ou_none("  33 ") == 33
    assert main.entier_ou_none("0") == 0


def test_profil_sans_contrainte_se_lit_en_clair():
    # Un profil sans plafond ne doit pas s'afficher "≤None€" dans le menu.
    label = main._profil_label(
        "paris",
        {"ville": "Paris", "km": 0, "prix_max": None, "surface_min": None,
         "canal": "discord"},
    )
    assert "None" not in label
    assert "paris" in label and "discord" in label


def test_saisie_refusee_si_ce_n_est_pas_un_nombre():
    # Le prompt valide avant de rendre la main : une faute de frappe ne doit
    # pas se transformer silencieusement en "aucune contrainte".
    assert main.valider_entier_optionnel("") is True
    assert main.valider_entier_optionnel("700") is True
    assert main.valider_entier_optionnel("abc") is not True
    assert main.valider_entier_optionnel("-5") is not True
