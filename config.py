"""Config locale persistante (canaux de notif). Stockée dans .config.json,
jamais commitée. Priorité : variable d'environnement > .config.json."""
import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".config.json")


def charger():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def sauver(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def get(key):
    """Valeur depuis l'env (prioritaire) sinon depuis .config.json."""
    return os.environ.get(key) or charger().get(key)


# ── Profils : {ville, km, prix_max, surface_min, canal} ──────
def charger_profils():
    return charger().get("profils", {})


def get_profil(nom):
    return charger_profils().get(nom)


def sauver_profil(nom, profil):
    cfg = charger()
    cfg.setdefault("profils", {})[nom] = profil
    cfg["dernier_profil"] = nom
    sauver(cfg)


def supprimer_profil(nom):
    cfg = charger()
    cfg.get("profils", {}).pop(nom, None)
    if cfg.get("dernier_profil") == nom:
        cfg["dernier_profil"] = None
    sauver(cfg)


def get_dernier_profil():
    return charger().get("dernier_profil")


def set_dernier_profil(nom):
    cfg = charger()
    cfg["dernier_profil"] = nom
    sauver(cfg)
