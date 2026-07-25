import os
import argparse

import questionary

from scrap import run_scraping
from model import (nettoyage_donnees, model_entrainement, bon_plan,
                   MIN_ANNONCES_PAR_SECTEUR)
import historique
import notif
import config

CSV_DEALS = config.CSV_DEALS


def entier_ou_none(txt):
    """Valeur saisie, ou None si le champ est laissé vide — un champ vide vaut
    "pas de contrainte", pas une valeur par défaut cachée."""
    t = str(txt).strip() if txt is not None else ""
    return int(t) if t.isdigit() else None


def valider_entier_optionnel(txt):
    """Validateur questionary : accepte un entier positif ou rien du tout.
    Sans lui, une faute de frappe passerait pour "aucune contrainte"."""
    t = str(txt).strip() if txt is not None else ""
    return True if t == "" or t.isdigit() else "Entre un nombre, ou laisse vide"


def _canal_choices():
    return [questionary.Choice(label, value=canal) for canal, label in notif.CANAUX.values()]


def _profil_label(nom, p):
    rayon = f"{p['km']}km" if p.get("km") else "commune seule"
    budget = f"≤{p['prix_max']}€" if p.get("prix_max") else "sans plafond"
    return f"{nom} · {rayon} · {budget} · {p['canal']}"


def profil_vers_params(p):
    return p["ville"], p["km"], p["prix_max"], p["surface_min"], p["canal"]


# ── flux « nouvelle recherche » ──────────────────────────────
def _demander_entier(message, exemple):
    """Prompt numérique dont l'exemple reste grisé : laisser vide = None."""
    return entier_ou_none(questionary.text(
        message, placeholder=exemple, validate=valider_entier_optionnel).ask())


def nouvelle_recherche():
    # Seule la ville est obligatoire : sans elle il n'y a rien à chercher.
    ville = None
    while not ville:
        ville = questionary.text("Ville", placeholder="ex : Vannes, Paris, Lyon").ask()
        if ville is None:      # Ctrl-C
            return None
        ville = ville.strip()

    km = _demander_entier("Rayon (km) · vide = la commune seule", "ex : 10")
    prix_max = _demander_entier("Budget max (€/mois) · vide = sans plafond", "ex : 700")
    surface_min = _demander_entier("Surface mini (m²) · vide = sans minimum", "ex : 33")
    if km is None:
        km = 0                 # la commune seule, sans élargissement
    canal = questionary.select("Où recevoir les bons plans ?", choices=_canal_choices()).ask()
    if canal is None:
        return None
    notif.assurer_config(canal)

    profil = {"ville": ville, "km": km, "prix_max": prix_max,
              "surface_min": surface_min, "canal": canal}

    if questionary.confirm("Sauver cette recherche comme profil ?", default=True).ask():
        _sauver_profil_interactif(profil)
    return profil


def _sauver_profil_interactif(profil):
    profils = config.charger_profils()
    nom = questionary.text("Nom du profil", default=profil["ville"]).ask()
    if not nom:
        return
    if nom in profils and not questionary.confirm(f"'{nom}' existe déjà. Écraser ?",
                                                  default=False).ask():
        nom = questionary.text("Nouveau nom").ask()
        if not nom:
            return
    config.sauver_profil(nom, profil)
    print(f"  ✓ Profil '{nom}' sauvé.")


def _supprimer_profil_interactif(profils):
    nom = questionary.select(
        "Supprimer quel profil ?",
        choices=list(profils) + [questionary.Choice("← annuler", value=None)],
    ).ask()
    if nom and questionary.confirm(f"Supprimer '{nom}' ?", default=False).ask():
        config.supprimer_profil(nom)
        print(f"  ✓ Profil '{nom}' supprimé.")


# ── menu principal ───────────────────────────────────────────
def menu_interactif():
    """Boucle du menu profils. Renvoie un dict profil, ou None si abandon."""
    while True:
        profils = config.charger_profils()
        if not profils:
            return nouvelle_recherche()

        dernier = config.get_dernier_profil()
        choix, defaut = [], None
        for nom, p in profils.items():
            c = questionary.Choice(_profil_label(nom, p), value=("profil", nom))
            choix.append(c)
            if nom == dernier:
                defaut = c
        choix.append(questionary.Choice("🆕 Nouvelle recherche", value=("nouveau", None)))
        choix.append(questionary.Choice("🗑 Supprimer un profil", value=("supprimer", None)))

        sel = questionary.select("Profil ?", choices=choix, default=defaut).ask()
        if sel is None:
            return None
        action, nom = sel
        if action == "profil":
            config.set_dernier_profil(nom)
            return config.get_profil(nom)
        if action == "nouveau":
            return nouvelle_recherche()
        if action == "supprimer":
            _supprimer_profil_interactif(profils)
            # retour au menu (boucle)


def recolte_parametres():
    """Renvoie (ville, km, prix_max, surface_min, canal, interactif) ou None si abandon.
    `interactif` = True si on est passé par le menu (→ demander confirmation avant Chrome)."""
    p = argparse.ArgumentParser(description="Détecteur de locations sous-cotées (France).")
    p.add_argument("--ville")
    p.add_argument("--km", type=int)
    p.add_argument("--max", type=int, dest="prix_max")
    p.add_argument("--surface-min", type=int, dest="surface_min")
    p.add_argument("--notif", choices=["terminal", "macos", "telegram", "email", "discord"])
    p.add_argument("--profil", help="Rejoue un profil sauvegardé sans menu (pour cron)")
    a = p.parse_args()

    # Non-interactif : rejouer un profil (cron)
    if a.profil:
        prof = config.get_profil(a.profil)
        if not prof:
            print(f"Profil '{a.profil}' introuvable. Existants : {list(config.charger_profils())}")
            return None
        config.set_dernier_profil(a.profil)
        return profil_vers_params(prof) + (False,)

    # Non-interactif : flags explicites. Un flag omis vaut "pas de contrainte",
    # comme un champ laissé vide dans le menu — une même règle pour les deux
    # modes. `is not None` et pas `or` : --km 0 est un choix, pas un vide.
    if a.ville is not None:
        canal = a.notif or "terminal"
        notif.assurer_config(canal)
        return (a.ville, a.km if a.km is not None else 0,
                a.prix_max, a.surface_min, canal, False)

    # Interactif : menu profils
    print("=== Rent Estimator — Détecteur de bons plans location ===\n")
    profil = menu_interactif()
    if profil is None:
        return None
    print()
    return profil_vers_params(profil) + (True,)


def afficher_deals(deals):
    print("\n" + "=" * 60)
    if deals is None or len(deals) == 0:
        print("  Aucun bon plan trouvé avec ces critères.")
        print("  Essaie d'élargir : budget +, surface -, ou rayon +.")
        print("=" * 60)
        return
    print(f"  {len(deals)} BON(S) PLAN(S) — triés par décote")
    print("=" * 60)
    for _, r in deals.iterrows():
        print(f"\n  {r['Secteur']} — {int(r['Surface'])}m², {int(r['Pieces'])} pièces — "
              f"{int(r['Prix'])}€/mois")
        print(f"    Décote : {r['Decote']:.0f}%  (estimé ~{int(r['Estimation'])}€)  "
              f"[{r['Source']}]")
        if not r.get("Fiable", True):
            print(f"    ⚠️  Estimation peu fiable : moins de "
                  f"{MIN_ANNONCES_PAR_SECTEUR} annonces dans ce secteur.")
        print(f"    {r['Lien']}")
    print("\n" + "=" * 60)


def main():
    params = recolte_parametres()
    if params is None:
        print("Abandon.")
        return
    ville, km, prix_max, surface_min, canal, interactif = params
    criteres = " · ".join([
        ville,
        f"{km}km" if km else "commune seule",
        f"≤{prix_max}€" if prix_max else "sans plafond",
        f"≥{surface_min}m²" if surface_min else "sans surface mini",
    ])

    if interactif:
        print(f"\n▶ Recherche : {criteres} · notif {canal}")
        print("  Une fenêtre Chrome va s'ouvrir automatiquement (elle se ferme seule à la fin).")
        if not questionary.confirm("Commencer ?", default=True).ask():
            print("Annulé.")
            return

    print(f"\n1. Web scraping — {criteres}...")
    fichier = run_scraping(ville=ville, km=km, prix_max=prix_max)
    if not fichier:
        return

    print("\n2. Nettoyage des données...")
    df = nettoyage_donnees(fichier)

    print("\n3. Entraînement du modèle...")
    model, x, y = model_entrainement(df)

    print("\n4. Export des opportunités sous-évaluées...")
    deals = bon_plan(model, x, y, df, budget_max=prix_max, surface_min=surface_min)

    afficher_deals(deals)

    hist = historique.charger_historique()
    nouveaux, baisses = historique.detecter(deals, hist)
    if len(nouveaux) or len(baisses):
        print(f"\n🔔 {len(nouveaux)} nouveau(x) · {len(baisses)} baisse(s) depuis le dernier run")
        notif.notifier_deals(nouveaux, baisses, canal=canal)
    historique.sauver(deals, hist)

    chemin = os.path.abspath(CSV_DEALS)
    print(f"\n→ Détail complet + liens : {chemin}")


if __name__ == "__main__":
    main()
