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
