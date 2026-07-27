"""Source paruvendu : lecture d'une page de résultats.

paruvendu était la seule source dont le parsing exigeait un navigateur — six
fonctions prenant un locator Playwright et empilant chacune une valeur dans une
liste parallèle. Sept listes à garder alignées par indice, un `try/except` par
fonction pour garantir un `append` même en échec : l'invariant tenait le
DataFrame entier et n'était écrit nulle part.

La fixture est RECONSTRUITE depuis les sélecteurs visés (voir son en-tête) :
elle fixe le contrat du parseur, pas la forme réelle des pages du site.
"""
import pathlib

import pytest

import sources

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "paruvendu_liste.html"


@pytest.fixture
def annonces():
    return sources.annonces_paruvendu(FIXTURE.read_text())


def test_une_ligne_par_carte(annonces):
    assert len(annonces) == 3
    assert list(annonces.columns) == sources.COLONNES


def test_le_prix_se_lit_malgre_les_espaces_de_milliers(annonces):
    # U+202F entre les milliers, U+00A0 avant l'euro : sans les couvrir,
    # "1 250 €" se lit 1, et l'annonce passe pour l'affaire du siecle.
    assert list(annonces["Prix"]) == [1250, 2450, 420]


def test_le_titre_porte_la_surface_et_le_secteur(annonces):
    assert list(annonces["Surface"]) == [52, 79, 18.5]
    assert list(annonces["Secteur"]) == ["Paris 15e", "Antony", "Vannes"]


def test_le_studio_compte_une_piece(annonces):
    # « 1 pièce » au singulier : ne lire que le pluriel perdait tous les
    # studios, qui partaient ensuite au dropna du nettoyage.
    assert list(annonces["Pieces"]) == [3, 4, 1]


def test_le_nombre_de_pieces_n_est_pas_celui_des_chambres(annonces):
    # « 3 pièces » et « 1 chambre » sont deux nombres voisins dans la même
    # liste de caractéristiques.
    assert annonces.iloc[0]["Pieces"] == 3


def test_les_pieces_se_trouvent_quel_que_soit_leur_rang(annonces):
    # Le site ne garantit pas l'ordre des caractéristiques : sur le studio,
    # « 0 chambre » précède « 1 pièce ». Ne lire que la première en ferait un
    # T0, que le nettoyage jetterait ensuite pour surface par pièce infinie.
    assert annonces.iloc[2]["Pieces"] == 1


def test_le_dpe_absent_ne_fait_pas_tomber_la_ligne(annonces):
    assert list(annonces["DPE"][:2]) == [5, 3]      # C, E
    assert annonces.iloc[2]["DPE"] is None or annonces["DPE"].isna().iloc[2]


def test_les_liens_relatifs_deviennent_absolus(annonces):
    assert all(l.startswith("https://www.paruvendu.fr/") for l in annonces["Lien"])


def test_le_pied_de_liste_donne_le_nombre_de_pages():
    assert sources.nombre_pages_paruvendu("Annonces 1 à 29 sur 58") == 3
    assert sources.nombre_pages_paruvendu("Aucun compteur ici") == 1
