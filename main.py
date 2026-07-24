import argparse
from scrap import run_scraping
from model import nettoyage_donnees, model_entrainement, bon_plan


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


def recolte_parametres():
    """Args CLI si fournis, sinon questions interactives."""
    p = argparse.ArgumentParser(description="Détecteur de locations sous-cotées (France).")
    p.add_argument("--ville")
    p.add_argument("--km", type=int)
    p.add_argument("--max", type=int, dest="prix_max")
    p.add_argument("--surface-min", type=int, dest="surface_min")
    a = p.parse_args()

    # Mode interactif : on ne demande que ce qui n'a pas été passé en argument
    print("=== Rent Estimator — Détecteur de bons plans location ===\n")
    ville = a.ville if a.ville is not None else demander("Ville", "Vannes")
    km = a.km if a.km is not None else demander("Rayon (km)", 10, int)
    prix_max = a.prix_max if a.prix_max is not None else demander("Budget max (€/mois)", 700, int)
    surface_min = a.surface_min if a.surface_min is not None else demander("Surface mini (m²)", 33, int)
    print()
    return ville, km, prix_max, surface_min


if __name__ == "__main__":
    ville, km, prix_max, surface_min = recolte_parametres()

    print(f"1. Web scraping — {ville}, {km}km, ≤{prix_max}€...")
    fichier = run_scraping(ville=ville, km=km, prix_max=prix_max)

    if fichier:
        print("\n2. Nettoyage des données...")
        df = nettoyage_donnees(fichier)

        print("\n3. Entraînement du modèle...")
        model, x, y = model_entrainement(df)

        print("\n4. Export des opportunités sous-évaluées...")
        bon_plan(model, x, y, df, budget_max=prix_max, surface_min=surface_min)

        print("\nPipeline exécuté avec succès !")
        print("→ Résultats dans Appartement_interessant.csv")
