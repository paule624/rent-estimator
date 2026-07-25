import base64
import math
import os
import re
import json
import unicodedata
import urllib.parse
import urllib.request
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

import config

# Cache des pages détail Ouest-France (Lien -> [surface, pieces]) pour éviter
# de re-scraper les mêmes annonces à chaque run. Le chemin se lit à l'usage :
# le sous-dossier de la recherche n'est connu qu'au lancement.

def _charger_cache():
    if os.path.exists(config.chemin_cache()):
        try:
            with open(config.chemin_cache()) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _sauver_cache(cache):
    try:
        config.assurer_dossier_sortie()
        with open(config.chemin_cache(), "w") as f:
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
    """Premier nombre d'un texte, séparateurs de milliers compris.

    Les sites mélangent les espaces : U+202F entre les milliers, U+00A0 avant
    l'euro. On les retire tous — sinon "4 600 €" se lit 4."""
    if not txt:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", re.sub(r"\s", "", txt))
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
    Ex "Appartement 52 m2 Paris 15" -> "Paris 15e". Voir docs/adr/0002.

    Le format est identique dans les trois villes à arrondissements (relevé sur
    le site) : on les balaie toutes plutôt que de coder Paris en dur. Un rang
    hors plage ne désigne pas un arrondissement, on le laisse au cas commune.
    """
    if not titre:
        return None
    for ville, plages in VILLES_A_ARRONDISSEMENTS.items():
        m = re.search(rf"\b{ville}\s+(\d{{1,2}})\b", titre)
        if not m:
            continue
        rang = int(m.group(1))
        debut, fin = plages["cp"]
        if 1 <= rang <= fin - debut + 1:
            return _libelle_arrondissement(ville, rang)
    # "<type> <surface> m2 <Commune> (<dept>)" — le dept varie d'une annonce
    # a l'autre, on ne le contraint pas.
    m = re.search(r"m[²2]\s+(.+?)\s*\(\s*\d{2,3}\s*\)", titre)
    return m.group(1).strip() if m else None


def adresse_vers_secteur(adresse):
    """Secteur depuis une adresse de carte SeLoger, qui porte le code postal :
    'Zone Rurale Nord Ouest, Vannes (56000)' -> 'Vannes'. Voir docs/adr/0002.

    Le quartier qui précède la commune est ignoré : la maille du modèle est
    l'arrondissement, pas le quartier (cf CONTEXT.md)."""
    if not adresse:
        return None
    m = re.search(r"([^,]+?)\s*\((\d{5})\)\s*$", adresse)
    if not m:
        return None
    return cp_vers_secteur(m.group(2), m.group(1).strip())


def _centre(commune):
    """(lat, lng) du centre d'une commune rendue par geo.api.gouv.fr.

    L'API rend du GeoJSON, où `coordinates` vaut [lng, lat] — l'inverse de
    l'ordre usuel. SeLoger cherche autour de ce point : les inverser
    déplacerait la recherche de plusieurs milliers de kilomètres en silence."""
    lng, lat = commune["centre"]["coordinates"]
    return lat, lng


def resoudre_ville(nom):
    """Résout un nom de ville en (nom officiel, code INSEE, code postal,
    département, (lat, lng)) via l'API gratuite geo.api.gouv.fr."""
    url = ("https://geo.api.gouv.fr/communes?nom=" + urllib.parse.quote(nom) +
           "&fields=nom,code,codesPostaux,centre&boost=population&limit=1")
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if not data:
        raise ValueError(f"Ville introuvable via l'API : {nom!r}")
    c = data[0]
    return c["nom"], c["code"], c["codesPostaux"][0], c["code"][:2], _centre(c)


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


def _cercle(lat, lng, km, cotes=32):
    """Contour fermé d'un disque de `km` autour d'un point, en (lat, lng).

    C'est le périmètre que SeLoger applique à la recherche : il porte `--km`.
    32 côtés suffisent à en approcher le bord à quelques dizaines de mètres."""
    points = []
    for i in range(cotes + 1):          # +1 : on referme sur le point de départ
        angle = 2 * math.pi * i / cotes
        d_lat = (km / 111.32) * math.cos(angle)
        d_lng = (km / (111.32 * math.cos(math.radians(lat)))) * math.sin(angle)
        points.append((lat + d_lat, lng + d_lng))
    return points


def _polyline(points):
    """Encode une suite de (lat, lng) au format Google Encoded Polyline.

    Format imposé par SeLoger, qui ne résout un lieu que si l'URL porte le
    contour de la zone cherchée. Voir docs/adr/0003."""
    def morceau(valeur):
        valeur = ~(valeur << 1) if valeur < 0 else valeur << 1
        sortie = ""
        while valeur >= 0x20:
            sortie += chr((0x20 | (valeur & 0x1F)) + 63)
            valeur >>= 5
        return sortie + chr(valeur + 63)

    sortie, lat_prec, lng_prec = "", 0, 0
    for lat, lng in points:
        lat_e5, lng_e5 = round(lat * 1e5), round(lng * 1e5)
        sortie += morceau(lat_e5 - lat_prec) + morceau(lng_e5 - lng_prec)
        lat_prec, lng_prec = lat_e5, lng_e5
    return sortie


# Le contour brut d'une commune compte plus de mille points (1210 pour Vannes),
# bien trop pour tenir dans une URL. On l'échantillonne : à cette maille le bord
# reste fidèle à quelques dizaines de mètres, comme le cercle de _cercle().
CONTOUR_MAX_POINTS = 60


def _geojson_commune(insee):
    """Contour GeoJSON d'une commune, ou None si l'API ne répond pas."""
    url = f"https://geo.api.gouv.fr/communes/{insee}?fields=contour&format=json"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.load(r).get("contour")
    except Exception:
        return None


def _contour_commune(insee, max_points=CONTOUR_MAX_POINTS):
    """Contour de la commune en (lat, lng), échantillonné et refermé.

    Sert à chercher la commune seule sur SeLoger sans quitter
    `classified-search` — la seule forme d'URL qui porte un filtre de type de
    bien. Voir docs/adr/0003."""
    contour = _geojson_commune(insee)
    if not contour:
        return None
    coords = contour.get("coordinates") or []
    # Une commune peut avoir des îles : on garde son anneau principal, celui
    # qui porte le plus de points.
    anneaux = [p[0] for p in coords] if contour.get("type") == "MultiPolygon" else coords
    anneaux = [a for a in anneaux if a]
    if not anneaux:
        return None
    anneau = max(anneaux, key=len)
    # Division par excès : un pas arrondi vers le bas laisserait passer
    # quelques points de plus que le plafond.
    pas = max(1, math.ceil(len(anneau) / max_points))
    # geo.api.gouv.fr rend du GeoJSON : coordinates = [lng, lat], l'inverse de
    # l'ordre usuel.
    points = [(lat, lng) for lng, lat in anneau[::pas]]
    if points[0] != points[-1]:
        points.append(points[0])
    return points


def url_ouestfrance(slug, dept, cp, km, prix_max):
    """URL de recherche Ouest-France. Le budget y sert de plafond, ce qui borne
    le nombre de pages détail à visiter ; sans budget, pas de filtre prix."""
    params = []
    if prix_max is not None:
        params.append(f"prix=0_{prix_max}")
    params += [f"rayon={km}", "types=appartement,maison"]
    return (f"https://www.ouestfrance-immo.com/louer/{slug}-{dept}-{cp}/"
            f"?{'&'.join(params)}")


def _url_seloger_zone(points, radius):
    """URL classified-search couvrant la zone décrite par `points`."""
    zone = {"radius": radius, "polyline": _polyline(points)}
    brut = json.dumps(zone, separators=(",", ":")).encode()
    locations = base64.urlsafe_b64encode(brut).decode().rstrip("=")
    return ("https://www.seloger.com/classified-search"
            "?distributionTypes=Rent&estateTypes=Apartment,House"
            f"&locations={locations}")


def url_seloger(slug, dept, lat, lng, km, insee=None):
    """URL de recherche SeLoger.

    SeLoger ne résout un lieu que si `locations` porte le contour de la zone :
    le placeId seul ne suffit pas, le polyline si (vérifié en réel, cf
    docs/adr/0003). On fabrique donc le cercle de `km` autour de la ville.

    `--km 0` demande la commune seule. Un cercle de rayon nul ne décrit aucune
    zone, mais le contour réel de la commune, si — et il permet de rester sur
    `classified-search`, la seule forme d'URL qui restreigne le type de bien.
    La forme par commune `immo-{slug}-{dept}/` ne le fait pas : un run sur
    Paris en a rapporté 405 bureaux, 94 locaux et 18 parkings sur 1200
    annonces. Elle ne sert plus que de repli si l'API géo est muette, où des
    non-logements à trier valent mieux que zéro annonce.

    Pas de plafond prix, comme sur les autres sources : le modèle doit voir
    tout le marché pour situer une annonce."""
    if not km:
        contour = _contour_commune(insee) if insee else None
        if not contour:
            return f"https://www.seloger.com/immobilier/locations/immo-{slug}-{dept}/"
        return _url_seloger_zone(contour, radius=0)
    return _url_seloger_zone(_cercle(lat, lng, km), radius=km)


def build_urls(nom, km, prix_max):
    """Construit les URLs de recherche des trois sources pour une ville."""
    nom_off, insee, cp, dept, (lat, lng) = resoudre_ville(nom)
    slug = _slug(nom_off)
    paruvendu = urls_paruvendu(nom_off, slug, cp, insee, km)
    ouestfrance = url_ouestfrance(slug, dept, cp, km, prix_max)
    seloger = url_seloger(slug, dept, lat, lng, km, insee=insee)
    return nom_off, dept, paruvendu, ouestfrance, seloger


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
def _of_caracteristiques(html):
    """Surface et nombre de pièces lus dans le tableau de caractéristiques.

    « Pièce » au singulier sur un T1, « Pièces » au-delà : lire le seul pluriel
    perdait tous les studios, silencieusement — l'annonce partait ensuite au
    `dropna` du nettoyage."""
    surface = pieces = None
    soup = BeautifulSoup(html, "html.parser")
    for line in soup.select(".detail-caracteristiques__line"):
        txt = line.get_text(" ", strip=True)
        if "Surface habitable" in txt:
            surface = _num(txt.split(":")[-1])
        elif txt.startswith("Pièce"):
            pieces = _num(txt.split(":")[-1])
    return surface, pieces


def _of_detail(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        return _of_caracteristiques(page.content())
    except Exception:
        return None, None

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
# SOURCE 3 — SELOGER (tout est sur la carte, pas de page détail)
# ═════════════════════════════════════════════════════════════
def _sl_texte(carte, testid):
    """Texte d'un champ de carte SeLoger. Les `data-testid` du site sont
    sémantiques et stables, contrairement à ses classes CSS générées."""
    element = carte.select_one(f'[data-testid="{testid}"]')
    return element.get_text(" ", strip=True) if element else ""


def _sl_titre(carte):
    """Titre commercial d'une carte SeLoger ("Appartement à louer").

    Le titre n'a pas de `data-testid` à lui ; il est le frère qui précède les
    caractéristiques. On passe par cette fratrie plutôt que par les classes
    CSS du site, qui sont générées et changent à chaque déploiement.

    Le titre doit rester exempt des caractéristiques : elles annoncent
    « 1 chambre » sur presque toutes les cartes, et le filtre anti-colocation
    de `nettoyage_donnees` jetterait alors la source entière."""
    faits = carte.select_one('[data-testid="cardmfe-keyfacts-testid"]')
    titre = faits.find_previous_sibling() if faits else None
    return titre.get_text(" ", strip=True) if titre else None


def _sl_lien(carte):
    """Lien vers l'annonce, débarrassé du contexte de recherche.

    SeLoger réinjecte la recherche entière derrière le lien de chaque carte —
    polyline compris — puis un fragment de suivi : ~700 caractères là où le
    chemin de l'annonce suffit. Les bons plans partent par Telegram ou
    Discord, où quelques liens pareils font déborder le message."""
    lien = carte.select_one("a[href]")
    if not lien or not lien.get("href"):
        return None
    return lien["href"].split("?")[0].split("#")[0]


def annonces_seloger(html):
    """Annonces d'une page de résultats SeLoger, aux colonnes COLONNES."""
    lignes = []
    soupe = BeautifulSoup(html, "html.parser")
    for carte in soupe.select('[data-testid="serp-core-classified-card-testid"]'):
        faits = _sl_texte(carte, "cardmfe-keyfacts-testid")
        # "2 pièces · 1 chambre · 83,2 m² · Étage 2/2" — viser "pièce(s)" et
        # non "chambre", les deux sont des nombres voisins dans la même ligne.
        pieces = re.search(r"(\d+)\s*pièces?\b", faits)
        surface = re.search(r"([\d,.]+)\s*m²", faits)
        lignes.append([
            _num(_sl_texte(carte, "cardmfe-price-testid")),
            float(surface.group(1).replace(",", ".")) if surface else None,
            adresse_vers_secteur(_sl_texte(carte, "cardmfe-description-box-address")),
            int(pieces.group(1)) if pieces else None,
            DPE_MAP.get(_sl_texte(carte, "card-mfe-energy-performance-class")),
            _sl_titre(carte),
            _sl_lien(carte),
            "seloger",
        ])
    return pd.DataFrame(lignes, columns=COLONNES)


def _sl_ecarter_banniere(page):
    """Retire la bannière de consentement, qui recouvre la pagination et
    intercepte les clics.

    On la retire au lieu de cliquer « OK » : le site ne propose pas de refus
    en un clic, et accepter le pistage à la place de l'utilisateur ne nous
    appartient pas. Le contexte navigateur est jetable, rien n'est conservé
    d'un run à l'autre."""
    try:
        page.evaluate(
            "document.querySelector('#usercentrics-root')?.remove()")
    except Exception:
        pass


def scrape_seloger(context, url):
    """Parcourt les pages de résultats SeLoger et rend leurs annonces.

    La page suivante s'obtient par un clic : le paramètre `pg=` de l'URL est
    inerte (il rend toujours la même page), comme `ray` chez paruvendu."""
    if not url:
        return pd.DataFrame(columns=COLONNES)
    page = context.new_page()
    frames = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        _sl_ecarter_banniere(page)
        for i in range(1, PAGES_MAX + 1):
            frames.append(annonces_seloger(page.content()))
            if i == PAGES_MAX:
                print(f"[seloger] plafonné à {PAGES_MAX} pages (voir PAGES_MAX)")
                break
            suivante = page.locator('button[aria-label="page suivante"]')
            if suivante.count() == 0 or not suivante.first.is_enabled():
                break
            # dispatch_event plutôt que click() : la page empile des habillages
            # (consentement, promos) qui interceptent un clic par coordonnées.
            # L'événement DOM va au bouton quoi qu'il y ait par-dessus.
            suivante.first.dispatch_event("click")
            page.wait_for_timeout(4000)   # le rendu des cartes est asynchrone
    except Exception as e:
        # Les pages déjà lues restent bonnes : une panne à la page 4 ne doit
        # pas coûter les trois premières, ni la source entière.
        print(f"[seloger] interrompu après {len(frames)} page(s) : {e}")
    finally:
        page.close()
    if not frames:
        return pd.DataFrame(columns=COLONNES)
    df = pd.concat(frames, ignore_index=True)
    print(f"[seloger] {len(df)} annonce(s) récupérées sur {len(frames)} page(s)")
    return df


# ═════════════════════════════════════════════════════════════
# ORCHESTRATEUR
# ═════════════════════════════════════════════════════════════
def run_scraping(ville="Vannes", km=10, prix_max=700):
    nom_off, dept, pv_urls, of_url, sl_url = build_urls(ville, km, prix_max)
    budget = f"budget OF ≤ {prix_max}€" if prix_max is not None else "budget OF illimité"
    rayon = f"rayon {km} km" if km else "commune seule"
    print(f"Ville : {nom_off} (dept {dept}) | {rayon} | {budget}")
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
            frames.append(scrape_seloger(context, sl_url))
            remplies = [f for f in frames if not f.empty]
            if not remplies:
                print("Aucune annonce trouvée. Les sélecteurs des sites ont "
                      "peut-être changé, ou la recherche est trop étroite.")
                return None
            df = pd.concat(remplies, ignore_index=True)
            df["Prix m2"] = df["Prix"] / df["Surface"]
            df = df.sort_values(by="Prix m2", ascending=True, na_position="last")
            df = df.drop(columns=["Prix m2"])
            config.assurer_dossier_sortie()
            df.to_csv(config.chemin_donnees(), index=False)
            print(f"Total : {len(df)} annonces ({df['Source'].value_counts().to_dict()})")
        finally:
            print('Fin du scraping')
            browser.close()
        return config.chemin_donnees()


if __name__ == '__main__':
    run_scraping()
