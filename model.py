import unicodedata
import numpy as np
import pandas as pd
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import cross_val_predict

import config

# ─────────────────────────────────────────────────────────────
# CONFIG
# Le rayon géo est déjà géré par l'URL (ray=10 autour de Vannes),
# donc pas de whitelist ici. Passe FILTRE_SECTEURS à une liste de secteurs
# normalisés (ex ["paris 11e", "paris 12e"]) pour re-restreindre malgré tout.
# Utile à Paris, où le rayon de recherche ne cadre rien (cf docs/adr/0002).
FILTRE_SECTEURS = None
BUDGET_MAX = 700    # loyer max affiché dans les bons plans (€/mois). None pour tout voir.
SURFACE_MIN = 33    # surface mini affichée dans les bons plans (m²). None pour tout voir.

# Deux sorts, pas un (cf docs/adr/0004). Le clamp absolu JETTE : à 1 ou 200
# €/m² il n'y a pas de prix, il y a une erreur de lecture. Il est volontairement
# très large. Les percentiles, eux, ne font que MARQUER "hors marché" : une
# annonce sous le marché est peut-être exactement le bon plan cherché. Les
# bornes se calent sur la donnée du run — un plafond fixe cale sur un marché en
# jette un autre (à 30 €/m², Vannes passe et Paris est intégralement rejeté).
PRIX_M2_PLANCHER = 3
PRIX_M2_PLAFOND = 60
PERCENTILE_BAS, PERCENTILE_HAUT = 0.025, 0.975
MIN_POUR_PERCENTILES = 20

# En dessous de ce nombre d'annonces, un Secteur manque à certains plis de la
# cross-validation (cv=5) : son One-Hot sort à zéro au moment de prédire et
# l'estimation perd la localisation. Les bons plans concernés sont marqués
# "estimation peu fiable", jamais masqués.
MIN_ANNONCES_PAR_SECTEUR = 5

COLONNES_MODELE = ["Surface", "SecteurKey", "Pieces", "DPE", "Surface par pieces"]
# ─────────────────────────────────────────────────────────────

def _normalise(nom):
    # minuscules + sans accents
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode()
    return s.lower().strip()

def _bornes_prix_m2(prix_m2):
    """Bornes du marché observé, calées sur la donnée du run.

    Reçoit du €/m² déjà passé au clamp absolu. Les percentiles resserrent sur le
    marché réellement observé — ce qui marche aussi bien à Vannes (~12 €/m²) qu'à
    Paris (~35), sans table par ville. Sur trop peu de lignes ils couperaient de
    la donnée saine : le clamp fait alors seul office de bornes, et rien n'est
    marqué hors marché.
    """
    if len(prix_m2) < MIN_POUR_PERCENTILES:
        return PRIX_M2_PLANCHER, PRIX_M2_PLAFOND
    return prix_m2.quantile(PERCENTILE_BAS), prix_m2.quantile(PERCENTILE_HAUT)


def nettoyage_donnees(file=None):
    file = file or config.chemin_donnees()
    df = pd.read_csv(file)
    # Vire les colocations / locations de chambre : prix par chambre, pas
    # par logement → fausse totalement le €/m² et le modèle.
    if "Titre" in df.columns:
        masque_coloc = df["Titre"].fillna("").str.contains(r"coloc|chambre", case=False, regex=True)
        df = df[~masque_coloc]
    # DPE souvent absent des annonces → on impute au lieu de jeter la ligne
    df = df.dropna(subset=["Prix", "Surface", "Secteur", "Pieces"])
    dpe_median = df["DPE"].median()
    df["DPE"] = df["DPE"].fillna(dpe_median if pd.notna(dpe_median) else 4)
    df['Secteur'] = df['Secteur'].astype(str).str.strip()
    df['Pieces'] = df['Pieces'].astype(int)
    df['DPE'] = df['DPE'].astype(int)
    df['Prix m2'] = df['Prix']/df['Surface']
    # Filtre géo optionnel (le rayon est déjà fait par l'URL)
    if FILTRE_SECTEURS:
        df = df[df['Secteur'].map(_normalise).isin(FILTRE_SECTEURS)]
    # Le clamp absolu jette : à ce niveau c'est une erreur de lecture, pas un
    # prix. Les percentiles, eux, ne font que marquer : une annonce sous le
    # marché est peut-être exactement le bon plan cherché (cf ADR 0004).
    df = df[(df["Prix m2"] >= PRIX_M2_PLANCHER) & (df["Prix m2"] <= PRIX_M2_PLAFOND)]
    bas, haut = _bornes_prix_m2(df["Prix m2"])
    df["HorsMarche"] = (df["Prix m2"] < bas) | (df["Prix m2"] > haut)
    df["Surface par pieces"] = df["Surface"]/df["Pieces"]
    # Clé secteur normalisée (sans accents/casse) pour fusionner les sources
    # ex "Saint-Avé" (paruvendu) == "Saint Ave" (OF) == "saint-ave"
    df["SecteurKey"] = df["Secteur"].map(_normalise)
    # Dédoublonne les annonces présentes sur plusieurs sites (même bien).
    # La surface est arrondie pour la seule comparaison : SeLoger la donne au
    # dixième (50,4 m²) là où paruvendu l'affiche entière, et sans cet arrondi
    # le même bien compterait deux fois. Les données gardent la valeur exacte.
    doublon = df.assign(SurfaceArrondie=df["Surface"].round()).duplicated(
        subset=["Prix", "SurfaceArrondie", "Pieces", "SecteurKey"])
    df = df[~doublon]
    print(f"{len(df)} annonces retenues. Secteurs : {sorted(df['Secteur'].unique())}")
    return df

def model_entrainement(df):
    # Le modèle apprend le marché observé seul. Les hors marché restent dans
    # `df` — elles seront estimées par bon_plan(), sans avoir pesé ici.
    appris = df[~df["HorsMarche"]] if "HorsMarche" in df.columns else df
    if len(appris) < 5:
        raise ValueError(f"Seulement {len(appris)} annonces retenues : trop peu pour "
                         f"entraîner. Élargis le rayon ou la zone.")

    encoder = OneHotEncoder(handle_unknown="ignore")
    y = np.log1p(appris["Prix"])
    x = appris[COLONNES_MODELE]

    preprocessor = ColumnTransformer(
        transformers=[('cat', encoder, ["SecteurKey"])],
        remainder='passthrough')

    model = Pipeline(steps=[('preprocessor', preprocessor),
                            ('regressor', RandomForestRegressor(n_estimators=100, max_depth=12, random_state=0))
                     ])

    # Petit dataset : on entraîne sur tout, l'éval se fait en cross-val (bon_plan)
    model.fit(x, y)

    return model, x, y

def bon_plan(model, x, y, df, budget_max=BUDGET_MAX, surface_min=SURFACE_MIN):
    df = df.copy()
    if "HorsMarche" not in df.columns:
        df["HorsMarche"] = False
    hors_marche = df["HorsMarche"]

    # Le marché observé s'estime hors-pli : chaque annonce est prédite par des
    # plis qui ne la contiennent pas.
    cv = min(5, len(x))  # évite de crasher si peu d'annonces
    df.loc[x.index, "Estimation"] = np.expm1(cross_val_predict(model, x, y, cv=cv))
    # Une hors marché n'a pas entraîné : `predict` sur le modèle déjà ajusté est
    # du hors-échantillon franc, de même nature que le hors-pli. Pas de fuite.
    if hors_marche.any():
        df.loc[hors_marche, "Estimation"] = np.expm1(
            model.predict(df.loc[hors_marche, COLONNES_MODELE]))

    appris = df.loc[x.index]
    print(f"MAE : {mean_absolute_error(appris['Prix'], appris['Estimation']):.0f} €")
    print(f"R²  : {r2_score(appris['Prix'], appris['Estimation']):.3f}")
    df["Decote"] = ((df["Prix"] - df["Estimation"]) / df["Estimation"])*100
    # Un secteur trop peu représenté sort des plis d'entraînement : son One-Hot
    # est alors tout à zéro et l'estimation ignore la localisation. On le dit
    # au lieu de masquer le bon plan — c'est une piste, pas une garantie.
    # Le comptage porte sur ce qui a appris : une hors marché seule dans son
    # secteur se compterait elle-même et passerait pour fiable.
    appris_par_secteur = appris["SecteurKey"].value_counts()
    par_secteur = df["SecteurKey"].map(appris_par_secteur).fillna(0)
    df["Fiable"] = par_secteur >= MIN_ANNONCES_PAR_SECTEUR
    df = df[df["Decote"] <= -15]                  # sous-coté d'au moins 15 %
    if budget_max is not None:
        df = df[df["Prix"] <= budget_max]         # payable pour ton budget
    if surface_min is not None:
        df = df[df["Surface"] >= surface_min]     # assez grand (vire les micro-studios)
    # Les hors marché ferment la marche : leur décote est la plus forte sans
    # être la plus crédible, et la notification est plafonnée.
    df = df.sort_values(by=["HorsMarche", "Decote"], ascending=[True, True])
    config.assurer_dossier_sortie()
    df.to_csv(config.chemin_deals(), index=False)
    contraintes = " et ".join(
        ([f"≤ {budget_max}€"] if budget_max is not None else [])
        + ([f"≥ {surface_min}m²"] if surface_min is not None else [])
    ) or "sans contrainte de budget ni de surface"
    print(f"{len(df)} bon(s) plan(s) {contraintes} exporté(s).")

    return df

if "__main__" == __name__:
    df = nettoyage_donnees()
    model, x, y = model_entrainement(df)
    bon_plan(model, x, y, df)
