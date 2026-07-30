"""Le moissonnage : résoudre la ville cherchée, ouvrir un navigateur, et laisser
le registre des Sources faire le tour des sites.

Ce fichier ne connaît plus aucun site par son nom. Ce que chaque source sait
faire — ses URLs, la lecture de ses pages, sa façon de paginer — vit dans
sources.py, un bloc par source.
"""
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

import config
import sources

USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, Gecko) Chrome/144.0.0.0 Safari/537.36')


@dataclass(frozen=True)
class Ville:
    """La ville cherchée, telle que geo.api.gouv.fr la résout. Les Sources y
    puisent ce dont elles ont besoin : slug et CP pour les URLs, INSEE pour
    paruvendu et le contour de commune, coordonnées pour le cercle SeLoger."""
    nom: str
    insee: str
    cp: str
    dept: str
    lat: float
    lng: float
    slug: str


# Slug d'URL d'une ville pour les sites (paruvendu/OF/SeLoger). À NE PAS confondre
# avec secteur.cle : celui-ci est la clé One-Hot du modèle, dont l'invariant est
# de rester stable entre Sources. Les deux rendent le même octet aujourd'hui par
# coïncidence — les garder séparés évite qu'un ajustement d'URL déplace la clé.
def slug_ville(nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _centre(commune):
    """(lat, lng) du centre d'une commune rendue par geo.api.gouv.fr.

    L'API rend du GeoJSON, où `coordinates` vaut [lng, lat] — l'inverse de
    l'ordre usuel. SeLoger cherche autour de ce point : les inverser
    déplacerait la recherche de plusieurs milliers de kilomètres en silence."""
    lng, lat = commune["centre"]["coordinates"]
    return lat, lng


def resoudre_ville(nom):
    """Résout un nom de ville en `Ville` via l'API gratuite geo.api.gouv.fr."""
    url = ("https://geo.api.gouv.fr/communes?nom=" + urllib.parse.quote(nom) +
           "&fields=nom,code,codesPostaux,centre&boost=population&limit=1")
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if not data:
        raise ValueError(f"Ville introuvable via l'API : {nom!r}")
    c = data[0]
    lat, lng = _centre(c)
    return Ville(nom=c["nom"], insee=c["code"], cp=c["codesPostaux"][0],
                 dept=c["code"][:2], lat=lat, lng=lng, slug=slug_ville(c["nom"]))


def run_scraping(recherche):
    """Moissonne toutes les sources pour une Recherche et rend leurs annonces.

    Écrit aussi `Data_Loyer.csv` — photographie du marché à l'instant T, utile
    pour rejouer un run sans navigateur — mais rend le DataFrame directement :
    l'écrire pour le relire aussitôt n'apportait que le risque de les voir
    diverger."""
    ville = resoudre_ville(recherche.ville)
    budget = (f"budget OF ≤ {recherche.prix_max}€" if recherche.prix_max is not None
              else "budget OF illimité")
    rayon = f"rayon {recherche.km} km" if recherche.km else "commune seule"
    print(f"Ville : {ville.nom} (dept {ville.dept}) | {rayon} | {budget}")
    print("ℹ️  Une fenêtre navigateur va s'ouvrir automatiquement (Chromium de "
          "Playwright, PAS ton Chrome perso). Ne la ferme pas, elle bosse seule "
          "et se fermera à la fin.\n")

    with sync_playwright() as p:
        # headless=False : Ouest-France utilise DataDome (anti-bot) qui bloque le
        # mode headless. Une fenêtre Chrome s'ouvre pendant le scrape.
        #
        # chromium_sandbox : désactivé en conteneur seulement. Chromium refuse de
        # démarrer en root sans --no-sandbox ; or l'image Docker tourne en root.
        # Piloté par l'env RENT_ESTIMATOR_NO_SANDBOX pour ne rien changer en local
        # (sandbox actif sur macOS). Sous Docker le scrape tourne headful sur un
        # écran virtuel Xvfb — pas de display réel sur le serveur.
        browser = p.chromium.launch(
            headless=False,
            chromium_sandbox=not os.environ.get("RENT_ESTIMATOR_NO_SANDBOX"))
        context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR",
                                      viewport={"width": 1366, "height": 900})
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            df = sources.moissonner_toutes(context, recherche, ville)
        finally:
            print('Fin du scraping')
            browser.close()

    if df is None:
        print("Aucune annonce trouvée. Les sélecteurs des sites ont "
              "peut-être changé, ou la recherche est trop étroite.")
        return None
    df = _trier_par_prix_m2(df)
    config.assurer_dossier_sortie()
    df.to_csv(config.chemin_donnees(), index=False)
    print(f"Total : {len(df)} annonces ({df['Source'].value_counts().to_dict()})")
    return df


def _trier_par_prix_m2(df):
    """Les moins chères au m² en tête : c'est par là qu'on lit le CSV brut."""
    df = df.assign(_prix_m2=df["Prix"] / df["Surface"])
    return df.sort_values(by="_prix_m2", na_position="last").drop(columns=["_prix_m2"])
