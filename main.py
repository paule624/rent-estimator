import argparse
from scrap import run_scraping
from model import nettoyage_donnees, model_entrainement, bon_plan


def parse_args():
    p = argparse.ArgumentParser(
        description="Détecteur de locations sous-cotées dans une ville française.")
    p.add_argument("--ville", default="Vannes", help="Ville de recherche (ex: Vannes, Auray, Rennes)")
    p.add_argument("--km", type=int, default=10, help="Rayon autour de la ville, en km (défaut 10)")
    p.add_argument("--max", type=int, default=700, dest="prix_max",
                   help="Budget max des annonces retenues, en €/mois (défaut 700)")
    p.add_argument("--surface-min", type=int, default=33, dest="surface_min",
                   help="Surface minimale des bons plans, en m² (défaut 33)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    print(f"1. Web scraping — {args.ville}, {args.km}km, ≤{args.prix_max}€...")
    fichier = run_scraping(ville=args.ville, km=args.km, prix_max=args.prix_max)

    if fichier:
        print("\n2. Nettoyage des données...")
        df = nettoyage_donnees(fichier)

        print("\n3. Entraînement du modèle...")
        model, x, y = model_entrainement(df)

        print("\n4. Export des opportunités sous-évaluées...")
        bon_plan(model, x, y, df, budget_max=args.prix_max, surface_min=args.surface_min)

        print("\nPipeline exécuté avec succès !")
