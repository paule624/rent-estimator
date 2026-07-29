"""Saisie des criteres : un champ laisse vide vaut "pas de contrainte".

Les valeurs montrees en gris dans les prompts sont des exemples, pas des
valeurs appliquees : rien ne se glisse dans une recherche sans etre demande.
"""
import pytest

import main
import model
import recherche


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
    # entier_ou_none rendrait None (= "aucune contrainte") sur ces deux-la : le
    # validateur doit les intercepter AVANT, sinon un filtre saute en silence.
    assert main.valider_entier_optionnel("10.5") is not True
    assert main.valider_entier_optionnel("7km") is not True


# ── Alerte : un run qui n'aboutit pas doit le dire sur son Canal ─────────────
# Le run planifié tourne sans témoin ; une Alerte est le seul signal d'échec.
@pytest.fixture
def run_sans_ecran(monkeypatch):
    """Neutralise la saisie et capture les Alertes. Le moissonnage est piloté
    par le test via `executer`, injecté juste après."""
    alertes = []
    cherchee = recherche.Recherche(ville="Vannes", km=10, canal="discord", nom="essai")
    monkeypatch.setattr(main, "recolte_parametres", lambda: (cherchee, False))
    monkeypatch.setattr(main.notif, "alerter",
                        lambda message, canal="terminal": alertes.append((message, canal)))
    return alertes


def test_trop_peu_d_annonces_emet_une_alerte_sans_planter(run_sans_ecran, monkeypatch):
    def executer(_):
        raise model.DonneesInsuffisantes("seulement 3 annonce(s) exploitable(s)")
    monkeypatch.setattr(main.recherche, "executer", executer)

    main.main()                      # ne doit PAS relever : échec attendu

    assert len(run_sans_ecran) == 1
    message, canal = run_sans_ecran[0]
    assert "Vannes" in message and "3 annonce" in message
    assert canal == "discord"


def test_une_moisson_vide_emet_une_alerte(run_sans_ecran, monkeypatch):
    monkeypatch.setattr(main.recherche, "executer", lambda _: None)

    main.main()

    assert len(run_sans_ecran) == 1
    message, canal = run_sans_ecran[0]
    assert "0 annonce moissonnée" in message
    assert canal == "discord"


def test_un_crash_inattendu_alerte_puis_releve(run_sans_ecran, monkeypatch):
    def executer(_):
        raise RuntimeError("net::ERR_NETWORK_CHANGED")
    monkeypatch.setattr(main.recherche, "executer", executer)

    # La trace doit remonter (le log reste le témoin), mais l'Alerte part avant.
    with pytest.raises(RuntimeError):
        main.main()

    assert len(run_sans_ecran) == 1
    message, canal = run_sans_ecran[0]
    assert "planté" in message and "Vannes" in message
    assert canal == "discord"
