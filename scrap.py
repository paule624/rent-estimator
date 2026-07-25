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
COLONNES = ["Prix", "Surface", "Secteur", "Pieces", "DPE", "Titre", "Lien", "Source"]
# Plafond de pages de résultats par source. Une recherche à Vannes tient en 2
# pages ; à Paris paruvendu en annonce plus de 800, dont ~17 % seulement sont
# intra-muros (cf docs/adr/0002) : sans plafond le run durerait des heures.
PAGES_MAX = 40
DPE_MAP = {'A': 7, 'B': 6, 'C': 5, 'D': 4, 'E': 3, 'F': 2, 'G': 1}
# ─────────────────────────────────────────────────────────────


def _num(txt):
    if not txt:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", txt.replace(" ", "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _slug(nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# Villes à arrondissements. Toute leur surface est une seule commune INSEE,
# donc le nom de commune ne discrimine rien : c'est l'arrondissement qui porte
# le prix. Voir docs/adr/0002.
#   cp     : plage des codes postaux d'arrondissement (identifie un Secteur)
#   insee  : INSEE du 1er arrondissement, les suivants s'incrémentent de 1.
#            paruvendu ne connaît QUE ces INSEE, pas celui de la commune
#            (75056 pour Paris) que rend geo.api.gouv.fr.
VILLES_A_ARRONDISSEMENTS = {
    "Paris": {"cp": (75001, 75020), "insee": 75101},
    "Lyon": {"cp": (69001, 69009), "insee": 69381},
    "Marseille": {"cp": (13001, 13016), "insee": 13201},
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
    for ville, plages in VILLES_A_ARRONDISSEMENTS.items():
        debut, fin = plages["cp"]
        if debut <= code <= fin:
            return _libelle_arrondissement(ville, code - debut + 1)
    return commune


def url_of_vers_secteur(href):
    """Secteur depuis une URL Ouest-France, qui porte commune ET code postal :
    '.../appartement/vannes-56-56260/...' -> 'Vannes'. Voir docs/adr/0002."""
    if not href:
        return None
    m = re.search(r"/([a-zà-ÿ\-]+)-\d{2}-(\d{5})/", href)
    if not m:
        return None
    return cp_vers_secteur(m.group(2), m.group(1).replace("-", " ").title())


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


def urls_paruvendu(nom_off, slug, cp, insee, km):
    """URLs de recherche paruvendu pour une ville : une seule en général.

    Dans une ville à arrondissements, une recherche par arrondissement : c'est
    la seule façon d'obtenir une donnée propre par Secteur, et le seul INSEE
    que paruvendu accepte.

    `km` passe par `lol`, le paramètre de rayon réellement pris en compte par
    paruvendu (`ray` est inerte : ray=10 et ray=50 rendent le même résultat).
    """
    def _url(cp_recherche, insee_recherche):
        # pas de plafond prix → le modèle voit tout le marché (contexte)
        return (
            f"https://www.paruvendu.fr/immobilier/recherche/location/{slug}-{cp_recherche}/"
            f"?rechpv=1&tt=5&tbApp=1&tbDup=1&tbChb=1&tbLof=1&tbAtl=1&tbPla=1"
            f"&tbMai=1&tbVil=1&tbCha=1&tbPro=1&tbHot=1&tbMou=1&tbFer=1"
            f"&pa=FR&lol={km}&codeINSEE={insee_recherche}"
        )

    plages = VILLES_A_ARRONDISSEMENTS.get(nom_off)
    if not plages:
        return [_url(cp, insee)]
    debut, fin = plages["cp"]
    return [_url(cp_arr, plages["insee"] + rang)
            for rang, cp_arr in enumerate(range(debut, fin + 1))]


def build_urls(nom, km, prix_max):
    """Construit les URLs de recherche paruvendu + Ouest-France pour une ville."""
    nom_off, insee, cp, dept = resoudre_ville(nom)
    slug = _slug(nom_off)
    paruvendu = urls_paruvendu(nom_off, slug, cp, insee, km)
    # Ouest-France : plafonné au budget (borne le nb de pages détail à visiter)
    ouestfrance = (
        f"https://www.ouestfrance-immo.com/louer/{slug}-{dept}-{cp}/"
        f"?prix=0_{prix_max}&rayon={km}&types=appartement,maison"
    )
    return nom_off, dept, paruvendu, ouestfrance


# ═════════════════════════════════════════════════════════════
# SOURCE 1 — PARUVENDU
# ═════════════════════════════════════════════════════════════
def _nombre_pages(texte, par_page=29):
    """Nombre de pages de résultats, lu dans le pied de liste ("... sur 934").
    Une recherche qui tient en une seule page n'affiche pas ce compteur."""
    trouves = re.findall(r"(?<=sur )\s*[-+]?\d+(?:[.,]\d+)?", texte or "")
    if not trouves:
        return 1
    return int(float(trouves[0]) // par_page) + 1


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

def _pv_secteur(card, liste_secteur):
    try:
        texte = card.locator('a.hover\\:no-underline').first.inner_text()
        if DEBUG_LOCALISATION and len(liste_secteur) < 3:
            print(f"[DEBUG paruvendu] {texte!r}")
        liste_secteur.append(titre_vers_secteur(texte))
    except Exception:
        liste_secteur.append(None)

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
    prix, surface, pieces, secteur, dpe, lien, titre = ([] for _ in range(7))
    try:
        page.goto(url, wait_until='networkidle')
        bloc = page.locator("p.text-sm").all()
        nombre_pages = _nombre_pages(bloc[-1].first.inner_text() if bloc else "")
        if nombre_pages > PAGES_MAX:
            print(f"[paruvendu] {nombre_pages} pages disponibles, plafonné à "
                  f"{PAGES_MAX} (voir PAGES_MAX)")
            nombre_pages = PAGES_MAX

        for i in range(1, nombre_pages + 1):
            print(f'[paruvendu] page {i}/{nombre_pages}')
            sep = "&" if "?" in url else "?"
            page.goto(f"{url}{sep}p={i}", wait_until='networkidle')
            for card in page.locator("div.blocAnnonce").all():
                _pv_prix(card, prix)
                _pv_surface(card, surface)
                _pv_secteur(card, secteur)
                _pv_pieces(card, pieces)
                _pv_DPE(card, dpe)
                _pv_lien(card, lien, titre)

        df = pd.DataFrame({
            "Prix": prix, "Surface": surface, "Secteur": secteur,
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
            secteur = url_of_vers_secteur(href)
            if href in cache:  # déjà scrapé auparavant → pas de re-visite
                surface, pieces = cache[href]
                hits += 1
            else:
                surface, pieces = _of_detail(detail, href)
                cache[href] = [surface, pieces]
                detail.wait_for_timeout(800)  # délai anti-ban entre pages détail
            rows.append([prix, surface, secteur, pieces, None, titre, href, "ouestfrance"])
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
    nom_off, dept, pv_urls, of_url = build_urls(ville, km, prix_max)
    print(f"Ville : {nom_off} (dept {dept}) | rayon {km} km | budget OF ≤ {prix_max}€")
    if len(pv_urls) > 1:
        print(f"{len(pv_urls)} arrondissements à parcourir sur paruvendu.")
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
            frames = [scrape_paruvendu(context, u) for u in pv_urls]
            frames.append(scrape_ouestfrance(context, of_url))
            remplies = [f for f in frames if not f.empty]
            if not remplies:
                print("Aucune annonce trouvée. Les sélecteurs des sites ont "
                      "peut-être changé, ou la recherche est trop étroite.")
                return None
            df = pd.concat(remplies, ignore_index=True)
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
