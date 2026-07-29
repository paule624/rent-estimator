import os

import numpy as np
import pandas as pd
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import cross_val_predict

import config
import secteur


class DonneesInsuffisantes(Exception):
    """Un run a moissonné des annonces, mais trop peu survivent au nettoyage
    pour estimer un marché. Distincte d'une moisson vide (0 annonce, cf
    `recherche.executer` qui rend None) et d'un crash inattendu : c'est un
    échec *attendu* — la zone est trop étroite, pas le code cassé. `main` la
    traduit en Alerte, sans trace ni exit non nul (cf CONTEXT.md)."""


# ─────────────────────────────────────────────────────────────
# CONFIG
# Le rayon géo est déjà géré par l'URL (ray=10 autour de Vannes),
# donc pas de whitelist ici. Passe FILTRE_SECTEURS à une liste de secteurs
# en clé (ex ["paris-11e", "paris-12e"], cf secteur.cle) pour re-restreindre.
# Utile à Paris, où le rayon de recherche ne cadre rien (cf docs/adr/0002).
FILTRE_SECTEURS = None

# Budget et surface mini n'ont PAS de valeur par défaut ici : ils appartiennent
# à la Recherche, qui les passe explicitement. Un défaut caché dans le modèle
# ferait disparaître des bons plans que personne n'a exclus, et se lirait comme
# une règle du projet alors qu'il ne servait qu'à l'exécution directe.

# Deux sorts, pas un (cf docs/adr/0004). Le plancher absolu JETTE : sous 3 €/m²
# il n'y a pas de prix, il y a une erreur de lecture — et une lecture trop basse
# fabrique un faux bon plan spectaculaire, donc elle ne doit jamais sortir.
# Il n'y a PAS de plafond symétrique : une lecture trop haute ne fabrique rien
# (sa décote est positive, le seuil -15 % l'élimine), et le percentile suffit à
# la tenir hors de l'entraînement en la marquant hors marché. Un plafond fixe
# jetait 22 % du marché parisien — des logements ordinaires, pas des anomalies.
PRIX_M2_PLANCHER = 3
PERCENTILE_BAS, PERCENTILE_HAUT = 0.025, 0.975
MIN_POUR_PERCENTILES = 20

# En dessous de ce nombre d'annonces, un Secteur manque à certains plis de la
# cross-validation (cv=5) : son One-Hot sort à zéro au moment de prédire et
# l'estimation perd la localisation. Les bons plans concernés sont marqués
# "estimation peu fiable", jamais masqués.
MIN_ANNONCES_PAR_SECTEUR = 5

COLONNES_MODELE = ["Surface", "SecteurKey", "Pieces", "DPE", "Surface par pieces"]
# ─────────────────────────────────────────────────────────────

def _bornes_prix_m2(prix_m2):
    """Bornes du marché observé, calées sur la donnée du run.

    Reçoit du €/m² déjà passé au plancher absolu. Les percentiles resserrent sur
    le marché réellement observé — ce qui marche aussi bien à Vannes (~12 €/m²)
    qu'à Paris (~35), sans table par ville. Sur trop peu de lignes ils
    couperaient de la donnée saine : rien n'est alors marqué hors marché.
    """
    if len(prix_m2) < MIN_POUR_PERCENTILES:
        return PRIX_M2_PLANCHER, float("inf")
    return prix_m2.quantile(PERCENTILE_BAS), prix_m2.quantile(PERCENTILE_HAUT)


def nettoyage_donnees(annonces=None):
    """Nettoie un marché moissonné : un DataFrame quand le run vient de le
    produire, un chemin de CSV quand on rejoue un run passé — c'est cette
    seconde forme qui permet de reprendre un `Data_Loyer.csv` sans navigateur."""
    if isinstance(annonces, pd.DataFrame):
        df = annonces.copy()
    else:
        df = pd.read_csv(annonces or config.chemin_donnees())
    # Vire les colocations / locations de chambre : prix par chambre, pas
    # par logement → fausse totalement le €/m² et le modèle.
    if "Titre" in df.columns:
        masque_coloc = df["Titre"].fillna("").str.contains(r"coloc|chambre", case=False, regex=True)
        df = df[~masque_coloc]
    # Prix/Surface arrivent parfois en texte ("Nous consulter", "1 200") : une
    # seule valeur non numérique bascule toute la colonne en dtype object et
    # fait planter np.log1p à l'entraînement. On coerce d'abord — ce qui n'est
    # pas un nombre devient NaN et tombe au dropna ci-dessous.
    df["Prix"] = pd.to_numeric(df["Prix"], errors="coerce")
    df["Surface"] = pd.to_numeric(df["Surface"], errors="coerce")
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
        df = df[df['Secteur'].map(secteur.cle).isin(FILTRE_SECTEURS)]
    # Le plancher absolu jette : à ce niveau c'est une erreur de lecture, pas un
    # prix. Les percentiles, eux, ne font que marquer : une annonce sous le
    # marché est peut-être exactement le bon plan cherché (cf ADR 0004).
    df = df[df["Prix m2"] >= PRIX_M2_PLANCHER]
    bas, haut = _bornes_prix_m2(df["Prix m2"])
    df["HorsMarche"] = (df["Prix m2"] < bas) | (df["Prix m2"] > haut)
    df["Surface par pieces"] = df["Surface"]/df["Pieces"]
    # Clé One-Hot : c'est elle qui fusionne les écritures d'une même commune
    # entre sources — "Saint-Avé" (paruvendu, SeLoger) et "Saint Ave"
    # (Ouest-France, reconstruit depuis le slug de son URL). Voir secteur.cle.
    df["SecteurKey"] = df["Secteur"].map(secteur.cle)
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
        raise DonneesInsuffisantes(
            f"seulement {len(appris)} annonce(s) exploitable(s), trop peu pour "
            f"estimer le marché. Élargis le rayon ou la zone.")

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

def _estimer(model, x, y, df):
    """Ajoute la colonne `Estimation`. Pur : aucune I/O, aucun print.

    Marché observé estimé hors-pli (chaque annonce prédite par des plis qui ne
    la contiennent pas) ; hors marché estimé par `predict` sur le modèle déjà
    ajusté — du hors-échantillon franc, de même nature que le hors-pli, pas de
    fuite (cf ADR 0004)."""
    df = df.copy()
    if "HorsMarche" not in df.columns:
        df["HorsMarche"] = False
    hors_marche = df["HorsMarche"]
    cv = min(5, len(x))  # évite de crasher si peu d'annonces
    df.loc[x.index, "Estimation"] = np.expm1(cross_val_predict(model, x, y, cv=cv))
    if hors_marche.any():
        df.loc[hors_marche, "Estimation"] = np.expm1(
            model.predict(df.loc[hors_marche, COLONNES_MODELE]))
    return df


def metriques(x, df_estime):
    """MAE et R² sur le seul marché observé — ce qui a servi de vérité. Pur."""
    appris = df_estime.loc[x.index]
    return {
        "mae": mean_absolute_error(appris["Prix"], appris["Estimation"]),
        "r2": r2_score(appris["Prix"], appris["Estimation"]),
    }


def scorer(model, x, y, df, budget_max=None, surface_min=None):
    """Estime, note (décote, fiabilité), filtre et trie les bons plans.

    **Pur** : ne lit ni n'écrit aucun fichier, n'imprime rien. Rend
    `(bons_plans, métriques)`. Toute la logique ML/scoring vit ici, testable
    sans système de fichiers ni stdout — l'export et l'affichage sont ailleurs."""
    df = _estimer(model, x, y, df)
    mesures = metriques(x, df)
    df["Decote"] = ((df["Prix"] - df["Estimation"]) / df["Estimation"]) * 100
    # Un secteur trop peu représenté sort des plis d'entraînement : son One-Hot
    # est alors tout à zéro et l'estimation ignore la localisation. On le dit
    # au lieu de masquer le bon plan — c'est une piste, pas une garantie.
    # Le comptage porte sur ce qui a appris : une hors marché seule dans son
    # secteur se compterait elle-même et passerait pour fiable.
    appris = df.loc[x.index]
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
    return df, mesures


def exporter(deals, chemin):
    """Écrit les bons plans en CSV, créant le dossier au besoin. Le seul point
    d'I/O du module côté sortie."""
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    deals.to_csv(chemin, index=False)


def _resume_contraintes(budget_max, surface_min):
    return " et ".join(
        ([f"≤ {budget_max}€"] if budget_max is not None else [])
        + ([f"≥ {surface_min}m²"] if surface_min is not None else [])
    ) or "sans contrainte de budget ni de surface"


def bon_plan(model, x, y, df, budget_max=None, surface_min=None):
    """Orchestre le scoring : calcule (via `scorer`, pur), imprime les métriques,
    exporte le CSV. La logique vit dans `scorer` ; ici on ne fait que l'I/O et
    l'affichage."""
    deals, mesures = scorer(model, x, y, df,
                            budget_max=budget_max, surface_min=surface_min)
    print(f"MAE : {mesures['mae']:.0f} €")
    print(f"R²  : {mesures['r2']:.3f}")
    exporter(deals, config.chemin_deals())
    print(f"{len(deals)} bon(s) plan(s) "
          f"{_resume_contraintes(budget_max, surface_min)} exporté(s).")
    return deals


if "__main__" == __name__:
    df = nettoyage_donnees()
    model, x, y = model_entrainement(df)
    bon_plan(model, x, y, df)
