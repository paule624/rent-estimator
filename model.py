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
# donc pas de whitelist commune ici. Passe FILTRE_COMMUNES à une
# liste si tu veux re-restreindre malgré tout.
FILTRE_COMMUNES = None
BUDGET_MAX = 700    # loyer max affiché dans les bons plans (€/mois). None pour tout voir.
SURFACE_MIN = 33    # surface mini affichée dans les bons plans (m²). None pour tout voir.
# ─────────────────────────────────────────────────────────────

def _normalise(nom):
    # minuscules + sans accents
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode()
    return s.lower().strip()

def nettoyage_donnees(file="Data_Loyer.csv"):
    df = pd.read_csv(file)
    # Vire les colocations / locations de chambre : prix par chambre, pas
    # par logement → fausse totalement le €/m² et le modèle.
    if "Titre" in df.columns:
        masque_coloc = df["Titre"].fillna("").str.contains(r"coloc|chambre", case=False, regex=True)
        df = df[~masque_coloc]
    # DPE souvent absent des annonces → on impute au lieu de jeter la ligne
    df = df.dropna(subset=["Prix", "Surface", "Commune", "Pieces"])
    dpe_median = df["DPE"].median()
    df["DPE"] = df["DPE"].fillna(dpe_median if pd.notna(dpe_median) else 4)
    df['Commune'] = df['Commune'].astype(str).str.strip()
    df['Pieces'] = df['Pieces'].astype(int)
    df['DPE'] = df['DPE'].astype(int)
    df['Prix m2'] = df['Prix']/df['Surface']
    # Filtre géo optionnel (le rayon est déjà fait par l'URL)
    if FILTRE_COMMUNES:
        df = df[df['Commune'].map(_normalise).isin(FILTRE_COMMUNES)]
    # Filtres calés Vannes/Morbihan (loyers ~9-18 €/m², bien < Paris)
    df = df[df["Prix"] <= 2500]
    df = df[(df["Prix m2"] >= 6) & (df["Prix m2"] <= 30)]
    df["Surface par pieces"] = df["Surface"]/df["Pieces"]
    # Clé commune normalisée (sans accents/casse) pour fusionner les sources
    # ex "Saint-Avé" (paruvendu) == "Saint Ave" (OF) == "saint-ave"
    df["CommuneKey"] = df["Commune"].map(_normalise)
    # Dédoublonne les annonces présentes sur plusieurs sites (même bien)
    df = df.drop_duplicates(subset=["Prix", "Surface", "Pieces", "CommuneKey"])
    print(f"{len(df)} annonces retenues. Communes : {sorted(df['Commune'].unique())}")
    return df

def model_entrainement(df):
    if len(df) < 5:
        raise ValueError(f"Seulement {len(df)} annonces Vannes-10km : trop peu pour entraîner. Élargis la zone/rayon.")

    encoder = OneHotEncoder(handle_unknown="ignore")
    y = np.log1p(df["Prix"])
    x = df[["Surface", "CommuneKey", "Pieces", "DPE", "Surface par pieces"]]

    preprocessor = ColumnTransformer(
        transformers=[('cat', encoder, ["CommuneKey"])],
        remainder='passthrough')

    model = Pipeline(steps=[('preprocessor', preprocessor),
                            ('regressor', RandomForestRegressor(n_estimators=100, max_depth=12, random_state=0))
                     ])

    # Petit dataset : on entraîne sur tout, l'éval se fait en cross-val (bon_plan)
    model.fit(x, y)

    return model, x, y

def bon_plan(model, x, y, df):
    df = df.copy()
    cv = min(5, len(df))  # évite de crasher si peu d'annonces
    y_pred_log = cross_val_predict(model, x, y, cv=cv)
    df['Estimation'] = np.expm1(y_pred_log)
    print(f"MAE : {mean_absolute_error(df['Prix'], df['Estimation']):.0f} €")
    print(f"R²  : {r2_score(df['Prix'], df['Estimation']):.3f}")
    df["Decote"] = ((df["Prix"] - df["Estimation"]) / df["Estimation"])*100
    df = df[df["Decote"] <= -15]                  # sous-coté d'au moins 15 %
    if BUDGET_MAX is not None:
        df = df[df["Prix"] <= BUDGET_MAX]         # payable pour ton budget
    if SURFACE_MIN is not None:
        df = df[df["Surface"] >= SURFACE_MIN]     # assez grand (vire les micro-studios)
    df = df.sort_values(by=["Decote"], ascending=True)
    df.to_csv("Appartement_interessant.csv", index=False)
    print(f"{len(df)} bon(s) plan(s) ≤ {BUDGET_MAX}€ et ≥ {SURFACE_MIN}m² exporté(s).")

    return 'csv créée'

if "__main__" == __name__:
    df = nettoyage_donnees()
    model, x, y = model_entrainement(df)
    print(bon_plan(model, x, y, df))
