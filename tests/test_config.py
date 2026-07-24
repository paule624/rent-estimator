import importlib
import config


def _isole(tmp_path, monkeypatch):
    """Redirige .config.json vers un fichier temporaire."""
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / ".config.json"))


def test_sauver_et_relire_profil(tmp_path, monkeypatch):
    _isole(tmp_path, monkeypatch)
    p = {"ville": "Vannes", "km": 10, "prix_max": 700, "surface_min": 33, "canal": "discord"}
    config.sauver_profil("vannes", p)
    assert config.get_profil("vannes") == p
    assert "vannes" in config.charger_profils()


def test_dernier_profil_suit_la_sauvegarde(tmp_path, monkeypatch):
    _isole(tmp_path, monkeypatch)
    config.sauver_profil("a", {"ville": "A", "km": 5, "prix_max": 600, "surface_min": 30, "canal": "terminal"})
    config.sauver_profil("b", {"ville": "B", "km": 5, "prix_max": 600, "surface_min": 30, "canal": "terminal"})
    assert config.get_dernier_profil() == "b"
    config.set_dernier_profil("a")
    assert config.get_dernier_profil() == "a"


def test_supprimer_profil(tmp_path, monkeypatch):
    _isole(tmp_path, monkeypatch)
    config.sauver_profil("x", {"ville": "X", "km": 5, "prix_max": 600, "surface_min": 30, "canal": "terminal"})
    config.supprimer_profil("x")
    assert config.get_profil("x") is None
    assert config.get_dernier_profil() is None  # le dernier pointait sur x


def test_env_prioritaire_sur_fichier(tmp_path, monkeypatch):
    _isole(tmp_path, monkeypatch)
    config.sauver(config.charger() | {"DISCORD_WEBHOOK": "depuis_fichier"})
    assert config.get("DISCORD_WEBHOOK") == "depuis_fichier"
    monkeypatch.setenv("DISCORD_WEBHOOK", "depuis_env")
    assert config.get("DISCORD_WEBHOOK") == "depuis_env"
