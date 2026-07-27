"""Ce que le terminal et les Canaux ont en commun face à un lot de Bons plans.

Un Bon plan **Hors marché** est évalué et montré, mais sa décote est
mécaniquement la plus forte sans être la plus crédible : il ferme la marche
partout où on l'affiche, et se compte à part (cf docs/adr/0004). Cette règle
vivait en double — une fois pour le terminal, une fois pour la notification —
avec deux conventions d'absence divergentes, alors que l'ADR 0004 l'a déjà fait
bouger une fois.
"""
import pandas as pd

VIDE = pd.DataFrame()


def scinder(deals):
    """Sépare le marché observé de ce qui reste à vérifier.

    Rend toujours deux DataFrames, jamais None : « pas de colonne HorsMarche »,
    « aucune hors marché » et « aucun bon plan » sont trois absences, et un
    appelant qui doit les distinguer finit par en oublier une."""
    if deals is None or len(deals) == 0:
        vide = deals if deals is not None else VIDE
        return vide, vide.iloc[0:0]
    if "HorsMarche" not in deals.columns:
        return deals, deals.iloc[0:0]
    hors = deals["HorsMarche"].astype(bool)
    return deals[~hors], deals[hors]
