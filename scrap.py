import os
import re
import json
import unicodedata
import urllib.parse
import urllib.request
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Cache des pages détail Ouest-France (Lien -> [surface, pieces]) pour éviter
# de re-scraper les mêmes annonces à chaque run.
CACHE_OF = "cache_of.json"

def _charger_cache():
    if os.path.exists(CACHE_OF):
        try:
            with open(CACHE_OF) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _sauver_cache(cache):
    try:
        with open(CACHE_OF, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────
# CONFIG
DEBUG_LOCALISATION = False
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, Gecko) Chrome/144.0.0.0 Safari/537.36')
COLONNES = ["Prix", "Surface", "Commune", "Pieces", "DPE", "Titre", "Lien", "Source"]
DPE_MAP = {'A': 7, 'B': 6, 'C': 5, 'D': 4, 'E': 3, 'F': 2, 'G': 1}

# Préfixe département, fixé au runtime par run_scraping (ex "56" pour le Morbihan).
# Sert à extraire la commune depuis le texte des annonces.
CP_PREFIXE = "56"
# ─────────────────────────────────────────────────────────────


def _num(txt):
    if not txt:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", txt.replace(" ", "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _slug(nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def commune_pv(texte, dept):
    """Commune depuis un titre paruvendu, ex 'Appartement 37 m2 Languidic (56)'."""
    if not texte:
        return None
    m = re.search(r"m[²2]\s+(.+?)\s*\(\s*" + dept, texte)
    return m.group(1).strip() if m else None


def commune_of(href, dept):
    """Commune depuis une URL Ouest-France, ex '.../appartement/vannes-56-56260/...'."""
    if not href:
        return None
    m = re.search(r"/([a-zà-ÿ\-]+)-" + dept + r"-\d{5}/", href)
    return m.group(1).replace("-", " ").title() if m else None


# Villes à arrondissements : plage de codes postaux -> nom de la ville.
# Toute leur surface est une seule commune INSEE, donc le nom de commune ne
# discrimine rien : c'est le CP qui porte l'arrondissement. Voir docs/adr/0002.
PLAGES_ARRONDISSEMENT = {
    "Paris": (75001, 75020),
    "Lyon": (69001, 69009),
    "Marseille": (13001, 13016),
}

# Le 16e arrondissement de Paris porte deux CP (75016 et 75116). Sans cet
# alias, 75116 tomberait hors plage et couperait le 16e en deux secteurs.
ALIAS_CP = {75116: 75016}


def _libelle_arrondissement(ville, rang):
    """Libellé unique d'un arrondissement, partagé par les deux extracteurs de
    Secteur : un même arrondissement doit rendre la même chaîne, sinon le
    One-Hot du modèle le coupe en deux catégories."""
    return f"{ville} {rang}{'er' if rang == 1 else 'e'}"


def cp_vers_secteur(cp, commune):
    """Secteur d'une annonce : l'arrondissement dans les villes qui en ont,
    la commune partout ailleurs. Voir docs/adr/0002."""
    try:
        # via float() : pandas rend un CP relu du CSV en float (75011.0)
        # dès qu'une ligne de la colonne est vide.
        code = int(float(cp))
    except (TypeError, ValueError):
        return commune          # source sans CP exploitable
    code = ALIAS_CP.get(code, code)
    for ville, (debut, fin) in PLAGES_ARRONDISSEMENT.items():
        if debut <= code <= fin:
            return _libelle_arrondissement(ville, code - debut + 1)
    return commune


def titre_vers_secteur(titre):
    """Secteur depuis un titre paruvendu, seule source géo de ce site.
    Ex "Appartement 52 m2 Paris 15" -> "Paris 15e". Voir docs/adr/0002."""
    if not titre:
        return None
    m = re.search(r"Paris\s+(\d{1,2})\b", titre)
    if m:
        return _libelle_arrondissement("Paris", int(m.group(1)))
    # "<type> <surface> m2 <Commune> (<dept>)" — le dept varie d'une annonce
    # a l'autre, on ne le contraint pas.
    m = re.search(r"m[²2]\s+(.+?)\s*\(\s*\d{2,3}\s*\)", titre)
    return m.group(1).strip() if m else None


def resoudre_ville(nom):
    """Résout un nom de ville en (nom officiel, code INSEE, code postal, département)
    via l'API gratuite geo.api.gouv.fr."""
    url = ("https://geo.api.gouv.fr/communes?nom=" + urllib.parse.quote(nom) +
           "&fields=nom,code,codesPostaux&boost=population&limit=1")
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if not data:
        raise ValueError(f"Ville introuvable via l'API : {nom!r}")
    c = data[0]
    return c["nom"], c["code"], c["codesPostaux"][0], c["code"][:2]


def build_urls(nom, km, prix_max):
    """Construit les URLs de recherche paruvendu + Ouest-France pour une ville."""
    nom_off, insee, cp, dept = resoudre_ville(nom)
    slug = _slug(nom_off)
    # paruvendu : pas de plafond prix → le modèle voit tout le marché (contexte)
    paruvendu = (
        f"https://www.paruvendu.fr/immobilier/recherche/location/{slug}-{cp}/"
        f"?rechpv=1&tt=5&tbApp=1&tbDup=1&tbChb=1&tbLof=1&tbAtl=1&tbPla=1"
        f"&tbMai=1&tbVil=1&tbCha=1&tbPro=1&tbHot=1&tbMou=1&tbFer=1"
        f"&pa=FR&lol=15&ray={km}&codeINSEE={insee}"
    )
    # Ouest-France : plafonné au budget (borne le nb de pages détail à visiter)
    ouestfrance = (
        f"https://www.ouestfrance-immo.com/louer/{slug}-{dept}-{cp}/"
        f"?prix=0_{prix_max}&rayon={km}&types=appartement,maison"
    )
    return nom_off, dept, paruvendu, ouestfrance


# ═════════════════════════════════════════════════════════════
# SOURCE 1 — PARUVENDU
# ═════════════════════════════════════════════════════════════
def _pv_DPE(card, liste_DPE):
    try:
        dpe_element = card.locator('span[class*="NoteEnerg_"]').first
        liste_DPE.append(dpe_element.inner_text().strip() if dpe_element.count() > 0 else None)
    except Exception:
        liste_DPE.append(None)

def _pv_pieces(card, liste_pieces):
    try:
        piece = card.locator("li.text-xs.text-grey-600.py-1.px-2.border-1.border-grey-50.rounded-xl.bg-grey-50.font-normal").first.inner_text(timeout=500)
        piece_text = re.findall(r"[-+]?\d+(?:[.,]\d+)?(?=\s*(?:pièce|piece|pièces|pieces))", piece)
        liste_pieces.append(int(piece_text[0]) if piece_text else None)
    except Exception:
        liste_pieces.append(None)

def _pv_prix(card, liste_prix):
    try:
        prix = re.sub(r"\s+", "", card.locator('div.encoded-lnk').inner_text().strip(" "))
        prix_texte = re.findall(r"[-+]?\d+(?:\.\d+)?", prix)
        liste_prix.append(float(prix_texte[0]) if prix_texte else None)
    except Exception:
        liste_prix.append(None)

def _pv_surface(card, liste_surface):
    try:
        surface = card.locator('a.hover\\:no-underline').first.inner_text()
        surface_texte = re.findall(r"[-+]?\d+(?:[.,]\d+)?(?=\s*(?:m2|m²))", surface)
        liste_surface.append(int(surface_texte[0]) if surface_texte else None)
    except Exception:
        liste_surface.append(None)

def _pv_commune(card, liste_commune):
    try:
        texte = card.locator('a.hover\\:no-underline').first.inner_text()
        if DEBUG_LOCALISATION and len(liste_commune) < 3:
            print(f"[DEBUG paruvendu] {texte!r}")
        liste_commune.append(commune_pv(texte, CP_PREFIXE))
    except Exception:
        liste_commune.append(None)

def _pv_lien(card, liste_lien, liste_titre):
    try:
        lien_el = card.locator('a.hover\\:no-underline').first
        href = lien_el.get_attribute('href') or ""
        titre = lien_el.inner_text().strip().replace("\n", " ")
        if href and href.startswith("/"):
            href = "https://www.paruvendu.fr" + href
        liste_lien.append(href if href else None)
        liste_titre.append(titre if titre else None)
    except Exception:
        liste_lien.append(None)
        liste_titre.append(None)

def scrape_paruvendu(context, url):
    if not url:
        return pd.DataFrame(columns=COLONNES)
    page = context.new_page()
    prix, surface, pieces, commune, dpe, lien, titre = ([] for _ in range(7))
    try:
        page.goto(url, wait_until='networkidle')
        bloc = page.locator("p.text-sm").all()
        page_text = re.findall(r"(?<=(?:sur ))\s*[-+]?\d+(?:[.,]\d+)?", bloc[-1].first.inner_text())
        nombre_pages = int(float(page_text[0]) // 29) + 1

        for i in range(1, nombre_pages + 1):
            print(f'[paruvendu] page {i}/{nombre_pages}')
            sep = "&" if "?" in url else "?"
            page.goto(f"{url}{sep}p={i}", wait_until='networkidle')
            for card in page.locator("div.blocAnnonce").all():
                _pv_prix(card, prix)
                _pv_surface(card, surface)
                _pv_commune(card, commune)
                _pv_pieces(card, pieces)
                _pv_DPE(card, dpe)
                _pv_lien(card, lien, titre)

        df = pd.DataFrame({
            "Prix": prix, "Surface": surface, "Commune": commune,
            "Pieces": pieces, "DPE": dpe, "Titre": titre, "Lien": lien,
        })
        df["DPE"] = df["DPE"].map(DPE_MAP)
        df["Source"] = "paruvendu"
        return df[COLONNES]
    except Exception as e:
        print(f"[paruvendu] Exception {e}")
        return pd.DataFrame(columns=COLONNES)
    finally:
        page.close()


# ═════════════════════════════════════════════════════════════
# SOURCE 2 — OUEST-FRANCE IMMO (surface uniquement sur page détail)
# ═════════════════════════════════════════════════════════════
def _of_detail(page, url):
    surface = pieces = None
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        soup = BeautifulSoup(page.content(), "html.parser")
        for line in soup.select(".detail-caracteristiques__line"):
            txt = line.get_text(" ", strip=True)
            if "Surface habitable" in txt:
                surface = _num(txt.split(":")[-1])
            elif txt.startswith("Pièces"):
                pieces = _num(txt.split(":")[-1])
    except Exception:
        pass
    return surface, pieces

def scrape_ouestfrance(context, url):
    if not url:
        return pd.DataFrame(columns=COLONNES)
    page = context.new_page()
    detail = context.new_page()
    cache = _charger_cache()
    rows = []
    hits = 0
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        arts = BeautifulSoup(page.content(), "html.parser").select("article.card-annonce")
        print(f"[ouestfrance] {len(arts)} annonces listées, récup surface sur page détail...")
        for art in arts:
            a = art.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.ouestfrance-immo.com" + href
            t_el = art.select_one(".card-annonce__content__title")
            titre = t_el.get_text(" ", strip=True) if t_el else ""
            p_el = art.select_one(".card-annonce__content__price__main")
            prix = _num(p_el.get_text() if p_el else None)
            commune = commune_of(href, CP_PREFIXE)
            if href in cache:  # déjà scrapé auparavant → pas de re-visite
                surface, pieces = cache[href]
                hits += 1
            else:
                surface, pieces = _of_detail(detail, href)
                cache[href] = [surface, pieces]
                detail.wait_for_timeout(800)  # délai anti-ban entre pages détail
            rows.append([prix, surface, commune, pieces, None, titre, href, "ouestfrance"])
        _sauver_cache(cache)
        print(f"[ouestfrance] {len(rows)} annonce(s) récupérées ({hits} depuis le cache)")
        return pd.DataFrame(rows, columns=COLONNES)
    except Exception as e:
        print(f"[ouestfrance] Exception {e}")
        return pd.DataFrame(columns=COLONNES)
    finally:
        page.close()
        detail.close()


# ═════════════════════════════════════════════════════════════
# ORCHESTRATEUR
# ═════════════════════════════════════════════════════════════
def run_scraping(ville="Vannes", km=10, prix_max=700):
    global CP_PREFIXE
    nom_off, dept, pv_url, of_url = build_urls(ville, km, prix_max)
    CP_PREFIXE = dept
    print(f"Ville : {nom_off} (dept {dept}) | rayon {km} km | budget OF ≤ {prix_max}€")
    print("ℹ️  Une fenêtre navigateur va s'ouvrir automatiquement (Chromium de "
          "Playwright, PAS ton Chrome perso). Ne la ferme pas, elle bosse seule "
          "et se fermera à la fin.\n")

    with sync_playwright() as p:
        # headless=False : Ouest-France utilise DataDome (anti-bot) qui bloque le
        # mode headless. Une fenêtre Chrome s'ouvre pendant le scrape.
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR",
                                      viewport={"width": 1366, "height": 900})
        context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            frames = [
                scrape_paruvendu(context, pv_url),
                scrape_ouestfrance(context, of_url),
            ]
            df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
            df["Prix m2"] = df["Prix"] / df["Surface"]
            df = df.sort_values(by="Prix m2", ascending=True, na_position="last")
            df = df.drop(columns=["Prix m2"])
            df.to_csv('Data_Loyer.csv', index=False)
            print(f"Total : {len(df)} annonces ({df['Source'].value_counts().to_dict()})")
        finally:
            print('Fin du scraping')
            browser.close()
        return 'Data_Loyer.csv'


if __name__ == '__main__':
    run_scraping()
