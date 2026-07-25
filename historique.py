"""Historique des annonces vues + détection des nouveautés et baisses de prix.

À chaque run, on enregistre les annonces (identifiées par leur lien) avec leur
prix et la date. En comparant au passé, on repère :
- les NOUVELLES annonces (lien jamais vu)
- les BAISSES de prix (même lien, prix plus bas qu'avant)
"""
import os
from datetime import date
import pandas as pd

import config

HISTORIQUE = config.CSV_HISTORIQUE
COLS = ["Lien", "Prix", "Secteur", "Surface", "Pieces", "Decote", "Date"]


def charger_historique():
    if os.path.exists(HISTORIQUE):
        try:
            hist = pd.read_csv(HISTORIQUE)
            # Historiques écrits avant l'introduction du Secteur : sans cette
            # migration, l'append laisserait deux colonnes à moitié vides.
            if "Commune" in hist.columns and "Secteur" not in hist.columns:
                hist = hist.rename(columns={"Commune": "Secteur"})
            return hist
        except Exception:
            pass
    return pd.DataFrame(columns=COLS)


def detecter(deals, hist):
    """Renvoie (nouveaux, baisses) : deux DataFrames extraits de `deals`.
    - nouveaux : lien absent de l'historique
    - baisses  : lien connu mais prix actuel < prix mini déjà vu
    """
    if deals is None or len(deals) == 0:
        vide = deals if deals is not None else pd.DataFrame()
        return vide, vide

    if hist is None or len(hist) == 0:
        return deals.copy(), deals.iloc[0:0].copy()

    prix_mini_vu = hist.groupby("Lien")["Prix"].min()
    liens_connus = set(hist["Lien"])

    est_nouveau = ~deals["Lien"].isin(liens_connus)
    nouveaux = deals[est_nouveau].copy()

    def _baisse(row):
        return row["Lien"] in prix_mini_vu.index and row["Prix"] < prix_mini_vu[row["Lien"]]

    connus = deals[~est_nouveau]
    baisses = connus[connus.apply(_baisse, axis=1)].copy() if len(connus) else deals.iloc[0:0].copy()
    return nouveaux, baisses


def sauver(deals, hist):
    """Ajoute les deals du jour à l'historique (append-only)."""
    if deals is None or len(deals) == 0:
        return
    aujourdhui = deals[["Lien", "Prix", "Secteur", "Surface", "Pieces", "Decote"]].copy()
    aujourdhui["Date"] = date.today().isoformat()
    maj = pd.concat([hist, aujourdhui], ignore_index=True)
    config.assurer_dossier_sortie()
    maj.to_csv(HISTORIQUE, index=False)
