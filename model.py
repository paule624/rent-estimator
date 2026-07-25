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

# ─────────────────────────────────────────────────────────────
# CONFIG
# Le rayon géo est déjà géré par l'URL (ray=10 autour de Vannes),
# donc pas de whitelist ici. Passe FILTRE_SECTEURS à une liste de secteurs
# normalisés (ex ["paris 11e", "paris 12e"]) pour re-restreindre malgré tout.
# Utile à Paris, où le rayon de recherche ne cadre rien (cf docs/adr/0002).
FILTRE_SECTEURS = None
BUDGET_MAX = 700    # loyer max affiché dans les bons plans (€/mois). None pour tout voir.
SURFACE_MIN = 33    # surface mini affichée dans les bons plans (m²). None pour tout voir.

# Filtrage des aberrations. Les bornes se calent sur la donnée du run : un
# plafond fixe cale sur un marché en jette un autre (à 30 €/m², Vannes passe
# et Paris est intégralement rejeté). Le clamp absolu ne sert qu'à écarter les
# erreurs de parsing, il est volontairement très large.
PRIX_M2_PLANCHER = 3
PRIX_M2_PLAFOND = 60
PERCENTILE_BAS, PERCENTILE_HAUT = 0.025, 0.975
# En dessous, les percentiles sur si peu de lignes couperaient de la donnée
# saine : seul le clamp absolu s'applique.
MIN_POUR_PERCENTILES = 20
# ─────────────────────────────────────────────────────────────

def _normalise(nom):
    # minuscules + sans accents
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode()
    return s.lower().strip()

def _bornes_prix_m2(prix_m2):
    """Bornes basse et haute du €/m² plausible, calées sur la donnée du run.

    Le clamp absolu écarte d'abord les erreurs de parsing, puis les percentiles
    resserrent sur le marché réellement observé — ce qui marche aussi bien à
    Vannes (~12 €/m²) qu'à Paris (~35), sans table par ville.
    """
    plausibles = prix_m2[(prix_m2 >= PRIX_M2_PLANCHER) & (prix_m2 <= PRIX_M2_PLAFOND)]
    if len(plausibles) < MIN_POUR_PERCENTILES:
        return PRIX_M2_PLANCHER, PRIX_M2_PLAFOND
    return plausibles.quantile(PERCENTILE_BAS), plausibles.quantile(PERCENTILE_HAUT)


def nettoyage_donnees(file="Data_Loyer.csv"):
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
    bas, haut = _bornes_prix_m2(df["Prix m2"])
    df = df[(df["Prix m2"] >= bas) & (df["Prix m2"] <= haut)]
    df["Surface par pieces"] = df["Surface"]/df["Pieces"]
    # Clé secteur normalisée (sans accents/casse) pour fusionner les sources
    # ex "Saint-Avé" (paruvendu) == "Saint Ave" (OF) == "saint-ave"
    df["SecteurKey"] = df["Secteur"].map(_normalise)
    # Dédoublonne les annonces présentes sur plusieurs sites (même bien)
    df = df.drop_duplicates(subset=["Prix", "Surface", "Pieces", "SecteurKey"])
    print(f"{len(df)} annonces retenues. Secteurs : {sorted(df['Secteur'].unique())}")
    return df

def model_entrainement(df):
    if len(df) < 5:
        raise ValueError(f"Seulement {len(df)} annonces Vannes-10km : trop peu pour entraîner. Élargis la zone/rayon.")

    encoder = OneHotEncoder(handle_unknown="ignore")
    y = np.log1p(df["Prix"])
    x = df[["Surface", "SecteurKey", "Pieces", "DPE", "Surface par pieces"]]

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
    cv = min(5, len(df))  # évite de crasher si peu d'annonces
    y_pred_log = cross_val_predict(model, x, y, cv=cv)
    df['Estimation'] = np.expm1(y_pred_log)
    print(f"MAE : {mean_absolute_error(df['Prix'], df['Estimation']):.0f} €")
    print(f"R²  : {r2_score(df['Prix'], df['Estimation']):.3f}")
    df["Decote"] = ((df["Prix"] - df["Estimation"]) / df["Estimation"])*100
    df = df[df["Decote"] <= -15]                  # sous-coté d'au moins 15 %
    if budget_max is not None:
        df = df[df["Prix"] <= budget_max]         # payable pour ton budget
    if surface_min is not None:
        df = df[df["Surface"] >= surface_min]     # assez grand (vire les micro-studios)
    df = df.sort_values(by=["Decote"], ascending=True)
    df.to_csv("Appartement_interessant.csv", index=False)
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
