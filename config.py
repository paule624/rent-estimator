"""Config locale persistante (canaux de notif) et chemins des artefacts de run.
La config est stockée dans .config.json, jamais commitée.
Priorité : variable d'environnement > .config.json."""
import os
import json

RACINE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(RACINE, ".config.json")

# ── Artefacts de run ─────────────────────────────────────────
# Tout ce qu'un run produit vit dans un seul dossier, ignoré par git : les
# données scrapées, les bons plans, l'historique et le cache des pages détail.
#
# Le dossier est ancré sur le dépôt, JAMAIS sur le dossier courant. Sous cron
# le cwd vaut $HOME : des chemins relatifs y écriraient un second historique,
# vide, et chaque exécution planifiée reverrait toutes les annonces comme
# nouvelles. RENT_ESTIMATOR_OUTPUT permet d'écrire ailleurs (disque partagé,
# dossier de test).
DOSSIER_SORTIE = os.environ.get("RENT_ESTIMATOR_OUTPUT") or os.path.join(RACINE, "output")

CSV_DONNEES = os.path.join(DOSSIER_SORTIE, "Data_Loyer.csv")
CSV_DEALS = os.path.join(DOSSIER_SORTIE, "Appartement_interessant.csv")
CSV_HISTORIQUE = os.path.join(DOSSIER_SORTIE, "historique.csv")
CACHE_DETAILS = os.path.join(DOSSIER_SORTIE, "cache_of.json")


def assurer_dossier_sortie():
    """Crée le dossier de sortie au besoin. À appeler avant toute écriture."""
    os.makedirs(DOSSIER_SORTIE, exist_ok=True)


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
