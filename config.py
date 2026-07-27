"""Config locale persistante (canaux de notif) et chemins des artefacts de run.
La config est stockée dans .config.json, jamais commitée.
Priorité : variable d'environnement > .config.json."""
import os
import sys
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

# Chaque recherche a son sous-dossier. Sans cloisonnement, un run sur Paris
# écrase les données de Vannes, et surtout les deux historiques se mélangent :
# la détection des nouveautés comparerait un marché à un autre.
_recherche = None


def definir_recherche(nom):
    """Cloisonne les artefacts du run dans output/<nom>/. À appeler une fois,
    dès que la recherche est connue. `None` remet tout à la racine."""
    global _recherche
    _recherche = _slug(nom) if nom else None


def _slug(nom):
    garde = [c if c.isalnum() or c in "-_" else "-" for c in str(nom).strip().lower()]
    return "".join(garde).strip("-") or None


def dossier_run():
    return os.path.join(DOSSIER_SORTIE, _recherche) if _recherche else DOSSIER_SORTIE


def chemin(nom):
    return os.path.join(dossier_run(), nom)


def chemin_donnees():
    """Le marché scrapé, photographie à l'instant T — réécrit à chaque run.
    Il ne s'accumule pas : le modèle s'entraînerait sur des annonces mortes."""
    return chemin("Data_Loyer.csv")


def chemin_deals():
    return chemin("Appartement_interessant.csv")


def chemin_historique():
    """Le seul artefact qui s'accumule : c'est lui qui porte la mémoire des
    annonces vues, donc la détection des nouveautés et des baisses."""
    return chemin("historique.csv")


def chemin_cache():
    return chemin("cache_of.json")


def assurer_dossier_sortie():
    """Crée le dossier du run au besoin. À appeler avant toute écriture."""
    os.makedirs(dossier_run(), exist_ok=True)


def charger():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception as e:
            # On repart d'une config vide plutôt que de crasher, mais on le dit :
            # un .config.json corrompu ferait sinon disparaître profils et canaux
            # en silence, et l'utilisateur croirait les avoir perdus.
            print(f"⚠️  .config.json illisible ({e}) — config ignorée ce run.",
                  file=sys.stderr)
            return {}
    return {}


def sauver(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        # Un échec d'écriture silencieux ferait croire un profil sauvé alors
        # qu'il est perdu au prochain lancement.
        print(f"⚠️  Écriture de .config.json échouée ({e}) — modifs non sauvées.",
              file=sys.stderr)


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
