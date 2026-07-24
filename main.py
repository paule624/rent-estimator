import os
import argparse
import subprocess
from scrap import run_scraping
from model import nettoyage_donnees, model_entrainement, bon_plan
import historique
import notif

CSV_DEALS = "Appartement_interessant.csv"


def demander(question, defaut, cast=str):
    """Pose une question, renvoie la réponse castée. Entrée vide = valeur par défaut."""
    rep = input(f"{question} [{defaut}] : ").strip()
    if not rep:
        return defaut
    try:
        return cast(rep)
    except ValueError:
        print(f"  ! valeur invalide, on garde {defaut}")
        return defaut


def demander_canal(defaut="1"):
    """Menu de choix du canal de notification."""
    print("\nOù recevoir les nouveaux bons plans à la fin ?")
    for k, (_, label) in notif.CANAUX.items():
        print(f"  {k}) {label}")
    choix = input(f"Choix [{defaut}] : ").strip() or defaut
    canal = notif.CANAUX.get(choix, notif.CANAUX[defaut])[0]
    return canal


def recolte_parametres():
    """Args CLI si fournis, sinon questions interactives."""
    p = argparse.ArgumentParser(description="Détecteur de locations sous-cotées (France).")
    p.add_argument("--ville")
    p.add_argument("--km", type=int)
    p.add_argument("--max", type=int, dest="prix_max")
    p.add_argument("--surface-min", type=int, dest="surface_min")
    p.add_argument("--notif", choices=["terminal", "macos", "telegram", "email", "discord"],
                   help="Canal de notification (saute la question)")
    a = p.parse_args()

    # Mode interactif : on ne demande que ce qui n'a pas été passé en argument
    print("=== Rent Estimator — Détecteur de bons plans location ===\n")
    ville = a.ville if a.ville is not None else demander("Ville", "Vannes")
    km = a.km if a.km is not None else demander("Rayon (km)", 10, int)
    prix_max = a.prix_max if a.prix_max is not None else demander("Budget max (€/mois)", 700, int)
    surface_min = a.surface_min if a.surface_min is not None else demander("Surface mini (m²)", 33, int)
    canal = a.notif if a.notif is not None else demander_canal()
    notif.assurer_config(canal)  # demande & sauve les identifiants manquants du canal
    print()
    return ville, km, prix_max, surface_min, canal


def afficher_deals(deals):
    """Affiche les bons plans directement dans le terminal."""
    print("\n" + "=" * 60)
    if deals is None or len(deals) == 0:
        print("  Aucun bon plan trouvé avec ces critères.")
        print("  Essaie d'élargir : budget +, surface -, ou rayon +.")
        print("=" * 60)
        return
    print(f"  {len(deals)} BON(S) PLAN(S) — triés par décote")
    print("=" * 60)
    for _, r in deals.iterrows():
        print(f"\n  {r['Commune']} — {int(r['Surface'])}m², {int(r['Pieces'])} pièces — "
              f"{int(r['Prix'])}€/mois")
        print(f"    Décote : {r['Decote']:.0f}%  (estimé ~{int(r['Estimation'])}€)  "
              f"[{r['Source']}]")
        print(f"    {r['Lien']}")
    print("\n" + "=" * 60)


def main():
    ville, km, prix_max, surface_min, canal = recolte_parametres()

    print(f"1. Web scraping — {ville}, {km}km, ≤{prix_max}€...")
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

    # Historique + notif : nouveautés et baisses de prix depuis le dernier run
    hist = historique.charger_historique()
    nouveaux, baisses = historique.detecter(deals, hist)
    if len(nouveaux) or len(baisses):
        print(f"\n🔔 {len(nouveaux)} nouveau(x) · {len(baisses)} baisse(s) depuis le dernier run")
        notif.notifier_deals(nouveaux, baisses, canal=canal)
    historique.sauver(deals, hist)

    chemin = os.path.abspath(CSV_DEALS)
    print(f"\n→ Détail complet + liens : {chemin}")
    try:
        subprocess.run(["open", chemin], check=False)  # ouvre le CSV (macOS)
    except Exception:
        pass


if __name__ == "__main__":
    main()
