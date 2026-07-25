"""Ouest-France ecrit "Pièce" au singulier pour un T1.

Releve sur le site le 2026-07-25 : la fiche d'un T1 porte "Pièce : 1", pas
"Pièces : 1". Le lire au pluriel seul perdait tous les studios — 3 annonces sur
68 du dernier run Vannes, jetees ensuite par le dropna sans laisser de trace.
"""
import scrap


def _fiche(lignes):
    corps = "".join(
        f'<div class="detail-caracteristiques__line">{l}</div>' for l in lignes)
    return f"<html><body>{corps}</body></html>"


def test_studio_avec_piece_au_singulier():
    html = _fiche(["Loyer : 510 €", "Surface habitable : 28 m²", "Pièce : 1"])
    assert scrap._of_caracteristiques(html) == (28, 1)


def test_appartement_avec_pieces_au_pluriel():
    html = _fiche(["Surface habitable : 65 m²", "Pièces : 3"])
    assert scrap._of_caracteristiques(html) == (65, 3)


def test_fiche_sans_caracteristiques():
    assert scrap._of_caracteristiques("<html><body></body></html>") == (None, None)
