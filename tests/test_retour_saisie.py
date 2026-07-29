"""Corriger une saisie sans tout recommencer : un recapitulatif editable a la
fin. Pas de retour possible entre deux questions — la correction se fait au recap.

Le pilote est `_demander_champ` : chaque test lui injecte une file de reponses
scriptees, ce qui rejoue le flux entier sans jamais lancer questionary.
"""
import main


def _scripter(monkeypatch, reponses):
    """Fait rendre a _demander_champ les valeurs de `reponses`, dans l'ordre."""
    it = iter(reponses)
    monkeypatch.setattr(main, "_demander_champ", lambda champ, courant: next(it))


# ── collecte sequentielle ────────────────────────────────────
def test_collecte_dans_l_ordre(monkeypatch):
    _scripter(monkeypatch, ["Vannes", 10, 700, 30, "terminal"])
    v = main._collecter_champs()
    assert v == {"ville": "Vannes", "km": 10, "prix_max": 700,
                 "surface_min": 30, "canal": "terminal"}


def test_abandon_pendant_la_saisie(monkeypatch):
    _scripter(monkeypatch, ["Vannes", main.ABANDON])
    assert main._collecter_champs() is None


def test_rayon_vide_vaut_commune_seule(monkeypatch):
    _scripter(monkeypatch, ["Vannes", None, None, None, "terminal"])
    v = main._collecter_champs()
    assert v["km"] == 0
    assert v["prix_max"] is None and v["surface_min"] is None


# ── recapitulatif editable ───────────────────────────────────
_BASE = {"ville": "Vannes", "km": 10, "prix_max": 700,
         "surface_min": 30, "canal": "terminal"}


def _recap(monkeypatch, selections, valeurs):
    """Scripte les choix du menu recap et les re-saisies de champ."""
    sel = iter(selections)
    val = iter(valeurs)
    monkeypatch.setattr(main, "_choisir_champ_a_corriger",
                        lambda v, label_valider="": next(sel))
    monkeypatch.setattr(main, "_demander_champ", lambda champ, courant: next(val))


def test_recap_corrige_un_champ_puis_lance(monkeypatch):
    _recap(monkeypatch, ["prix_max", main.VALIDER], [650])
    out = main._reviser(dict(_BASE))
    assert out["prix_max"] == 650


def test_recap_lance_sans_rien_toucher(monkeypatch):
    _recap(monkeypatch, [main.VALIDER], [])
    out = main._reviser(dict(_BASE))
    assert out == _BASE


def test_recap_abandon(monkeypatch):
    monkeypatch.setattr(main, "_choisir_champ_a_corriger",
                        lambda v, label_valider="": None)
    assert main._reviser(dict(_BASE)) is None


def test_recap_rayon_vide_redevient_zero(monkeypatch):
    # Vider le rayon au recap doit valoir "commune seule", pas None.
    _recap(monkeypatch, ["km", main.VALIDER], [None])
    out = main._reviser(dict(_BASE))
    assert out["km"] == 0


def test_resume_de_chaque_champ_ne_plante_pas():
    # Chaque ligne ne doit lire QUE son champ : un dict litteral evaluait
    # CANAUX[ville] et plantait (KeyError sur un nom de ville).
    assert main._resume_champ("ville", "Redon") == "ville : Redon"
    assert main._resume_champ("km", 0) == "rayon : commune seule"
    assert main._resume_champ("km", 10) == "rayon : 10km"
    assert main._resume_champ("prix_max", None) == "budget max : sans plafond"
    assert main._resume_champ("prix_max", 700) == "budget max : ≤700€"
    assert main._resume_champ("surface_min", None) == "surface mini : sans minimum"
    assert main._resume_champ("surface_min", 33) == "surface mini : ≥33m²"
    assert "canal" in main._resume_champ("canal", "terminal")


# ── prompts unitaires (le seul endroit ou questionary est touche) ─
class _Rep:
    def __init__(self, val):
        self.val = val

    def ask(self):
        return self.val


def test_prompt_entier_rend_la_valeur(monkeypatch):
    monkeypatch.setattr(main.questionary, "text", lambda *a, **k: _Rep("700"))
    assert main._prompt_entier("prix_max", None) == 700


def test_prompt_entier_vide_vaut_none(monkeypatch):
    monkeypatch.setattr(main.questionary, "text", lambda *a, **k: _Rep(""))
    assert main._prompt_entier("prix_max", None) is None


def test_prompt_entier_ctrl_c_abandonne(monkeypatch):
    monkeypatch.setattr(main.questionary, "text", lambda *a, **k: _Rep(None))
    assert main._prompt_entier("prix_max", None) is main.ABANDON


def test_prompt_ville_redemande_si_vide(monkeypatch):
    reps = iter(["", "  ", "Vannes"])
    monkeypatch.setattr(main.questionary, "text", lambda *a, **k: _Rep(next(reps)))
    assert main._prompt_ville(None) == "Vannes"
