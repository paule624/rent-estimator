import re
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DPE_MAP = {'A': 7, 'B': 6, 'C': 5, 'D': 4, 'E': 3, 'F': 2, 'G': 1}

def _num(txt):
    if not txt:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", txt.replace(" ", "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None

# ─────────────────────────────────────────────────────────────
# CONFIG — Vannes + ~10 km (Morbihan 56)
#
# Colle pour chaque site l'URL EXACTE d'une recherche faite dans
# ton navigateur (location, Vannes + rayon). Mets None pour
# désactiver une source. Ne pas inclure le paramètre de page.
# ─────────────────────────────────────────────────────────────
PARUVENDU_URL = (
    "https://www.paruvendu.fr/immobilier/recherche/location/vannes-56000/"
    "?rechpv=1&tt=5&tbApp=1&tbDup=1&tbChb=1&tbLof=1&tbAtl=1&tbPla=1"
    "&tbMai=1&tbVil=1&tbCha=1&tbPro=1&tbHot=1&tbMou=1&tbFer=1"
    "&pa=FR&lol=15&ray=10&codeINSEE=56260"
)
PAP_URL = "https://www.pap.fr/annonce/location-appartement-garage-parking-location-accession-maison-mobil-home-peniche-vannes-56000-g28674-jusqu-a-700-euros"
OUESTFRANCE_URL = "https://www.ouestfrance-immo.com/louer/vannes-56-56000/?prix=0_700&rayon=10&types=appartement,maison"

CP_PREFIXE = "56"          # codes postaux Morbihan
DEBUG_LOCALISATION = False # True = affiche le texte brut des 1res annonces
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, Gecko) Chrome/144.0.0.0 Safari/537.36')

COLONNES = ["Prix", "Surface", "Commune", "Pieces", "DPE", "Titre", "Lien", "Source"]


# ═════════════════════════════════════════════════════════════
# SOURCE 1 — PARUVENDU
# ═════════════════════════════════════════════════════════════
def _pv_DPE(card, liste_DPE):
    try:
        dpe_element = card.locator('span[class*="NoteEnerg_"]').first
        dpe_text = None
        if dpe_element.count() > 0:
            dpe_text = dpe_element.inner_text().strip()
        liste_DPE.append(dpe_text)
    except Exception:
        liste_DPE.append(None)

def _pv_pieces(card, liste_pieces):
    try:
        piece = card.locator("li.text-xs.text-grey-600.py-1.px-2.border-1.border-grey-50.rounded-xl.bg-grey-50.font-normal").first.inner_text(timeout=500)
        motif_piece = r"[-+]?\d+(?:[.,]\d+)?(?=\s*(?:pièce|piece|pièces|pieces))"
        piece_text = re.findall(motif_piece, piece)
        liste_pieces.append(int(piece_text[0]) if piece_text else None)
    except Exception:
        liste_pieces.append(None)

def _pv_prix(card, liste_prix):
    try:
        prix = card.locator('div.encoded-lnk').inner_text().strip(" ")
        prix = re.sub(r"\s+", "", prix)
        prix_texte = re.findall(r"[-+]?\d+(?:\.\d+)?", prix)
        liste_prix.append(float(prix_texte[0]) if prix_texte else None)
    except Exception:
        liste_prix.append(None)

def _pv_surface(card, liste_surface):
    try:
        motif_surface = r"[-+]?\d+(?:[.,]\d+)?(?=\s*(?:m2|m²))"
        surface = card.locator('a.hover\\:no-underline').first.inner_text()
        surface_texte = re.findall(motif_surface, surface)
        liste_surface.append(int(surface_texte[0]) if surface_texte else None)
    except Exception:
        liste_surface.append(None)

def _pv_commune(card, liste_commune):
    try:
        texte = card.locator('a.hover\\:no-underline').first.inner_text()
        if DEBUG_LOCALISATION and len(liste_commune) < 3:
            print(f"[DEBUG paruvendu] {texte!r}")
        m = re.search(r"m[²2]\s+(.+?)\s*\(\s*" + CP_PREFIXE, texte)
        liste_commune.append(m.group(1).strip() if m else None)
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

def scrape_paruvendu(context):
    if not PARUVENDU_URL:
        return pd.DataFrame(columns=COLONNES)
    page = context.new_page()
    prix, surface, pieces, commune, dpe, lien, titre = ([] for _ in range(7))
    try:
        page.goto(PARUVENDU_URL, wait_until='networkidle')
        bloc = page.locator("p.text-sm").all()
        page_text = re.findall(r"(?<=(?:sur ))\s*[-+]?\d+(?:[.,]\d+)?", bloc[-1].first.inner_text())
        nombre_pages = int(float(page_text[0]) // 29) + 1

        for i in range(1, nombre_pages + 1):
            print(f'[paruvendu] page {i}/{nombre_pages}')
            sep = "&" if "?" in PARUVENDU_URL else "?"
            page.goto(f"{PARUVENDU_URL}{sep}p={i}", wait_until='networkidle')
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
        df["DPE"] = df["DPE"].map({'A': 7, 'B': 6, 'C': 5, 'D': 4, 'E': 3, 'F': 2, 'G': 1})
        df["Source"] = "paruvendu"
        return df[COLONNES]
    except Exception as e:
        print(f"[paruvendu] Exception {e}")
        return pd.DataFrame(columns=COLONNES)
    finally:
        page.close()


# ═════════════════════════════════════════════════════════════
# SOURCE 2 — PAP (particulier à particulier). Tout est dans la liste.
# ═════════════════════════════════════════════════════════════
def scrape_pap(context):
    if not PAP_URL:
        return pd.DataFrame(columns=COLONNES)
    page = context.new_page()
    rows = []
    try:
        page.goto(PAP_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        soup = BeautifulSoup(page.content(), "html.parser")
        for it in soup.select("div.search-list-item-alt"):
            a = it.select_one("a.item-title")
            if not a or not a.get("href", "").startswith("/annonces/"):
                continue  # ignore les blocs "atelier"/pub
            titre = a.get_text(" ", strip=True)
            href = "https://www.pap.fr" + a["href"]
            prix = _num(it.select_one(".item-price").get_text() if it.select_one(".item-price") else None)
            tags = [x.get_text(" ", strip=True) for x in it.select(".item-tags li")]
            surface = pieces = None
            for t in tags:
                if "m²" in t or "m2" in t:
                    surface = _num(t)
                elif "pièce" in t or "piece" in t:
                    pieces = _num(t)
            dpe_el = it.select_one("[class*=item-thumb-dpe-]")
            dpe = None
            if dpe_el:
                mdpe = re.search(r"item-thumb-dpe-([a-g])", " ".join(dpe_el.get("class")))
                if mdpe:
                    dpe = DPE_MAP.get(mdpe.group(1).upper())
            mcom = re.search(r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\- ]*?)\s*\(" + CP_PREFIXE + r"\d{3}\)", titre)
            commune = mcom.group(1).strip() if mcom else None
            rows.append([prix, surface, commune, pieces, dpe, titre, href, "pap"])
        print(f"[pap] {len(rows)} annonce(s)")
        return pd.DataFrame(rows, columns=COLONNES)
    except Exception as e:
        print(f"[pap] Exception {e}")
        return pd.DataFrame(columns=COLONNES)
    finally:
        page.close()


# ═════════════════════════════════════════════════════════════
# SOURCE 3 — OUEST-FRANCE IMMO. Surface uniquement sur page détail.
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

def scrape_ouestfrance(context):
    if not OUESTFRANCE_URL:
        return pd.DataFrame(columns=COLONNES)
    page = context.new_page()
    detail = context.new_page()
    rows = []
    try:
        page.goto(OUESTFRANCE_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        soup = BeautifulSoup(page.content(), "html.parser")
        arts = soup.select("article.card-annonce")
        print(f"[ouestfrance] {len(arts)} annonces listées, récup surface sur page détail...")
        for art in arts:
            a = art.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.ouestfrance-immo.com" + href
            titre = (art.select_one(".card-annonce__content__title").get_text(" ", strip=True)
                     if art.select_one(".card-annonce__content__title") else "")
            prix = _num(art.select_one(".card-annonce__content__price__main").get_text()
                        if art.select_one(".card-annonce__content__price__main") else None)
            # commune depuis le slug d'URL : .../appartement/vannes-56-56260/...
            mcom = re.search(r"/([a-zà-ÿ\-]+)-" + CP_PREFIXE + r"-\d{5}/", href)
            commune = mcom.group(1).replace("-", " ").title() if mcom else None
            surface, pieces = _of_detail(detail, href)
            detail.wait_for_timeout(800)  # délai anti-ban entre pages détail
            rows.append([prix, surface, commune, pieces, None, titre, href, "ouestfrance"])
        print(f"[ouestfrance] {len(rows)} annonce(s) récupérées")
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
def run_scraping():
    with sync_playwright() as p:
        # headless=False : PAP et Ouest-France utilisent DataDome (anti-bot)
        # qui bloque le mode headless. Une fenêtre Chrome s'ouvre pendant le scrape.
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR",
                                      viewport={"width": 1366, "height": 900})
        context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            frames = [
                scrape_paruvendu(context),
                scrape_pap(context),
                scrape_ouestfrance(context),
            ]
            df = pd.concat([f for f in frames if not f.empty], ignore_index=True)

            # Tri : meilleures annonces (€/m² le plus bas) en premier
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
