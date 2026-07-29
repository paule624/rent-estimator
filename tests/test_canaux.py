"""Un Canal : le moyen de recevoir les bons plans à la fin d'un run (CONTEXT.md).

Il en existait cinq, déclarés à cinq endroits — dont la liste recopiée en dur
dans l'analyseur de la ligne de commande. Un canal ajouté au registre
apparaissait dans le menu et se faisait refuser par `--notif`.
"""
import pandas as pd
import pytest

import canaux
import main
import notif


@pytest.fixture
def canal_essai(monkeypatch):
    """Un canal de plus, ajouté au seul registre. Tout ce qui connaît les
    canaux doit le voir sans avoir été touché."""
    envoyes = []
    monkeypatch.setitem(canaux.CANAUX, "essai", canaux.Canal(
        libelle="Canal d'essai", champs=(),
        envoyer=lambda resume, detail: envoyes.append((resume, detail))))
    return envoyes


def test_un_canal_ajoute_au_registre_est_accepte_en_ligne_de_commande(canal_essai):
    for nom in canaux.CANAUX:
        assert main._parser().parse_args(["--notif", nom]).notif == nom


def test_un_canal_inconnu_reste_refuse():
    with pytest.raises(SystemExit):
        main._parser().parse_args(["--notif", "pigeon"])


def test_un_canal_ajoute_au_registre_est_offert_par_le_menu(canal_essai):
    assert "Canal d'essai" in [c.title for c in main._canal_choices()]


def test_le_canal_choisi_est_celui_qui_envoie(canal_essai):
    deals = pd.DataFrame(
        [["Vannes", 50, 600, -20.0, "https://ex.fr/1", True, False]],
        columns=["Secteur", "Surface", "Prix", "Decote", "Lien", "Fiable", "HorsMarche"])

    notif.notifier_deals(deals, None, canal="essai")

    assert len(canal_essai) == 1
    resume, detail = canal_essai[0]
    assert "1 nouveau(x) bon(s) plan(s)" in resume
    assert "https://ex.fr/1" in detail


def test_une_alerte_part_sur_le_canal_choisi(canal_essai):
    # Une Alerte (run planté / trop peu d'annonces) emprunte le même Canal que
    # les bons plans, mais n'en est pas un : un simple message texte.
    notif.alerter("⚠️ Vannes : 0 annonce moissonnée", canal="essai")

    assert len(canal_essai) == 1
    resume, detail = canal_essai[0]
    assert "0 annonce moissonnée" in resume
    assert "0 annonce moissonnée" in detail
