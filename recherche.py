"""La Recherche : ce qu'un run couvre, et ce qu'il produit.

Une ville, un rayon, des filtres — plus le Canal qui recevra les bons plans et
le nom du compartiment où tout atterrit (cf CONTEXT.md).

`executer` enchaîne le run entier : moissonner, nettoyer, entraîner, classer,
comparer à l'Historique. **Le moissonnage est un paramètre**, pas un import :
c'est la seule étape qui exige un navigateur, et la remplacer par un CSV tenu à
la main rend le reste rejouable à volonté. Ce que l'on fait du résultat —
l'afficher, l'envoyer sur un Canal — n'appartient pas ici.
"""
import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import config
import historique
import model
import scrap


@dataclass(frozen=True)
class Recherche:
    ville: str
    km: int = 0
    prix_max: Optional[int] = None
    surface_min: Optional[int] = None
    canal: str = "terminal"
    # Le compartiment de sortie : le nom du Profil qui rejoue la Recherche, ou
    # la ville si elle n'a pas été sauvée.
    nom: Optional[str] = None

    @property
    def compartiment(self):
        return self.nom or self.ville

    def resume(self):
        return " · ".join([
            self.ville,
            f"{self.km}km" if self.km else "commune seule",
            f"≤{self.prix_max}€" if self.prix_max else "sans plafond",
            f"≥{self.surface_min}m²" if self.surface_min else "sans surface mini",
        ])


@dataclass(frozen=True)
class Resultat:
    deals: pd.DataFrame
    nouveaux: pd.DataFrame
    baisses: pd.DataFrame
    chemin: str          # le CSV des bons plans, en absolu


def executer(recherche, moissonner=scrap.run_scraping):
    """Joue un run entier et rend son Resultat, ou None si rien n'a été moissonné.

    `moissonner(recherche) -> DataFrame | None` : le scraping en vrai, un CSV
    de fixture en test."""
    # Cloisonner AVANT toute écriture : sans ça un run sur Paris écrase les
    # données de Vannes, et les deux historiques se mélangent.
    config.definir_recherche(recherche.compartiment)

    print(f"\n1. Web scraping — {recherche.resume()}...")
    annonces = moissonner(recherche)
    if annonces is None or len(annonces) == 0:
        return None

    print("\n2. Nettoyage des données...")
    df = model.nettoyage_donnees(annonces)

    print("\n3. Entraînement du modèle...")
    estimateur, x, y = model.model_entrainement(df)

    print("\n4. Export des bons plans sous-évalués...")
    deals = model.bon_plan(estimateur, x, y, df, budget_max=recherche.prix_max,
                           surface_min=recherche.surface_min)

    hist = historique.charger_historique()
    nouveaux, baisses = historique.detecter(deals, hist)
    historique.sauver(deals, hist)

    return Resultat(deals=deals, nouveaux=nouveaux, baisses=baisses,
                    chemin=os.path.abspath(config.chemin_deals()))
