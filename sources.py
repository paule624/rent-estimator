"""Les Sources : les sites d'où viennent les annonces.

Une Source dit **quelles URLs la couvrent** pour une Recherche donnée, sait
**lire une page de résultats**, et connaît **sa façon de naviguer** — les trois
sites paginent différemment et rien ne peut les unifier là-dessus. Ce qui est
unifié, c'est le reste : `lire(html) -> DataFrame[COLONNES]` est du HTML en
entrée, des lignes en sortie, sans navigateur — donc testable sur fixture.

Chaque source occupe un bloc contigu de ce fichier : URLs, lecture, navigation.
Avant, paruvendu était éclaté sur quatre zones de scrap.py, entrelacé avec les
deux autres, et l'orchestrateur les nommait une par une.
"""
import base64
import json
import math
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

import pandas as pd
from bs4 import BeautifulSoup

import config
import secteur

COLONNES = ["Prix", "Surface", "Secteur", "Pieces", "DPE", "Titre", "Lien", "Source"]
DPE_MAP = {'A': 7, 'B': 6, 'C': 5, 'D': 4, 'E': 3, 'F': 2, 'G': 1}
# Plafond de pages de résultats par source. Une recherche à Vannes tient en 2
# pages ; à Paris paruvendu en annonce plus de 800, dont ~17 % seulement sont
# intra-muros (cf docs/adr/0002) : sans plafond le run durerait des heures.
PAGES_MAX = 40

VIDE = pd.DataFrame(columns=COLONNES)


@dataclass(frozen=True)
class Source:
    nom: str
    urls: Callable          # (recherche, ville) -> list[str]
    lire: Callable          # (html) -> DataFrame[COLONNES]
    moissonner: Callable    # (context, url, lire) -> DataFrame[COLONNES]


def _num(txt):
    """Premier nombre d'un texte, séparateurs de milliers compris.

    Les sites mélangent les espaces : U+202F entre les milliers, U+00A0 avant
    l'euro. On les retire tous — sinon "4 600 €" se lit 4."""
    if not txt:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", re.sub(r"\s", "", txt))
    return float(m.group(0).replace(",", ".")) if m else None


# ═════════════════════════════════════════════════════════════
# SOURCE 1 — PARUVENDU
# ═════════════════════════════════════════════════════════════
def urls_paruvendu(recherche, ville):
    """URLs de recherche paruvendu : une seule en général.

    Dans une ville à arrondissements, une recherche par arrondissement : c'est
    la seule façon d'obtenir une donnée propre par Secteur, et le seul INSEE
    que paruvendu accepte.

    `km` passe par `lol`, le paramètre de rayon réellement pris en compte par
    paruvendu (`ray` est inerte : ray=10 et ray=50 rendent le même résultat).
    """
    return _urls_paruvendu(ville.nom, ville.slug, ville.cp, ville.insee, recherche.km)


def _urls_paruvendu(nom_off, slug, cp, insee, km):
    def _url(cp_recherche, insee_recherche):
        # pas de plafond prix → le modèle voit tout le marché (contexte)
        return (
            f"https://www.paruvendu.fr/immobilier/recherche/location/{slug}-{cp_recherche}/"
            f"?rechpv=1&tt=5&tbApp=1&tbDup=1&tbChb=1&tbLof=1&tbAtl=1&tbPla=1"
            f"&tbMai=1&tbVil=1&tbCha=1&tbPro=1&tbHot=1&tbMou=1&tbFer=1"
            f"&pa=FR&lol={km}&codeINSEE={insee_recherche}"
        )

    plages = secteur.VILLES_A_ARRONDISSEMENTS.get(nom_off)
    if not plages:
        return [_url(cp, insee)]
    debut, fin = plages["cp"]
    return [_url(cp_arr, plages["insee"] + rang)
            for rang, cp_arr in enumerate(range(debut, fin + 1))]


def nombre_pages_paruvendu(texte, par_page=29):
    """Nombre de pages de résultats, lu dans le pied de liste ("... sur 934").
    Une recherche qui tient en une seule page n'affiche pas ce compteur."""
    trouves = re.findall(r"(?<=sur )\s*[-+]?\d+(?:[.,]\d+)?", texte or "")
    if not trouves:
        return 1
    return int(float(trouves[0]) // par_page) + 1


def _pv_texte(carte, selecteur):
    element = carte.select_one(selecteur)
    return element.get_text(" ", strip=True) if element else ""


def _pv_pieces(carte):
    """Nombre de pièces, cherché dans TOUTES les caractéristiques de la carte.

    Elles se suivent dans un ordre que le site ne garantit pas, et « 1 chambre »
    voisine « 3 pièces » dans la même liste : ne lire que la première en ferait
    dépendre le résultat de leur ordre d'affichage."""
    for li in carte.select("li.text-xs.text-grey-600"):
        m = re.search(r"(\d+)\s*pi[eè]ces?\b", li.get_text(" ", strip=True), re.I)
        if m:
            return int(m.group(1))
    return None


def annonces_paruvendu(html):
    """Annonces d'une page de résultats paruvendu, aux colonnes COLONNES.

    Le titre du lien porte à lui seul la surface ET le Secteur : paruvendu
    n'expose aucun code postal (cf docs/adr/0002)."""
    lignes = []
    for carte in BeautifulSoup(html, "html.parser").select("div.blocAnnonce"):
        lien = carte.select_one('a[class~="hover:no-underline"]')
        titre = lien.get_text(" ", strip=True) if lien else ""
        href = (lien.get("href") or "") if lien else ""
        if href.startswith("/"):
            href = "https://www.paruvendu.fr" + href
        surface = re.search(r"([\d,.]+)\s*(?:m2|m²)", titre)
        lignes.append([
            _num(_pv_texte(carte, "div.encoded-lnk")),
            float(surface.group(1).replace(",", ".")) if surface else None,
            secteur.depuis_titre(titre),
            _pv_pieces(carte),
            DPE_MAP.get(_pv_texte(carte, 'span[class*="NoteEnerg_"]')),
            titre or None,
            href or None,
            "paruvendu",
        ])
    return pd.DataFrame(lignes, columns=COLONNES)


def moissonner_paruvendu(context, url, lire):
    """paruvendu pagine par l'URL : `?p=2` rend bien la deuxième page."""
    page = context.new_page()
    frames = []
    try:
        page.goto(url, wait_until='networkidle')
        bloc = page.locator("p.text-sm").all()
        nombre_pages = nombre_pages_paruvendu(bloc[-1].first.inner_text() if bloc else "")
        if nombre_pages > PAGES_MAX:
            print(f"[paruvendu] {nombre_pages} pages disponibles, plafonné à "
                  f"{PAGES_MAX} (voir PAGES_MAX)")
            nombre_pages = PAGES_MAX
        sep = "&" if "?" in url else "?"
        for i in range(1, nombre_pages + 1):
            print(f'[paruvendu] page {i}/{nombre_pages}')
            page.goto(f"{url}{sep}p={i}", wait_until='networkidle')
            frames.append(lire(page.content()))
    except Exception as e:
        # Les pages déjà lues restent bonnes : une panne à la page 4 ne doit
        # pas coûter les trois premières, ni la source entière.
        print(f"[paruvendu] interrompu après {len(frames)} page(s) : {e}")
    finally:
        page.close()
    return pd.concat(frames, ignore_index=True) if frames else VIDE


PARUVENDU = Source("paruvendu", urls_paruvendu, annonces_paruvendu, moissonner_paruvendu)


# ═════════════════════════════════════════════════════════════
# SOURCE 2 — OUEST-FRANCE IMMO (surface uniquement sur page détail)
# ═════════════════════════════════════════════════════════════
def urls_ouestfrance(recherche, ville):
    """URL de recherche Ouest-France. Le budget y sert de plafond, ce qui borne
    le nombre de pages détail à visiter ; sans budget, pas de filtre prix."""
    params = []
    if recherche.prix_max is not None:
        params.append(f"prix=0_{recherche.prix_max}")
    params += [f"rayon={recherche.km}", "types=appartement,maison"]
    return [f"https://www.ouestfrance-immo.com/louer/{ville.slug}-{ville.dept}-"
            f"{ville.cp}/?{'&'.join(params)}"]


def annonces_ouestfrance(html):
    """Annonces d'une page de résultats Ouest-France, aux colonnes COLONNES.

    Surface et nombre de pièces restent vides : ce site ne les met que sur la
    page détail de chaque annonce, que `moissonner_ouestfrance` va chercher."""
    lignes = []
    for art in BeautifulSoup(html, "html.parser").select("article.card-annonce"):
        a = art.select_one("a[href]")
        if not a:
            continue
        href = a["href"]
        if href.startswith("/"):
            href = "https://www.ouestfrance-immo.com" + href
        t_el = art.select_one(".card-annonce__content__title")
        p_el = art.select_one(".card-annonce__content__price__main")
        lignes.append([
            _num(p_el.get_text() if p_el else None),
            None, secteur.depuis_url_of(href), None, None,
            t_el.get_text(" ", strip=True) if t_el else "",
            href, "ouestfrance",
        ])
    return pd.DataFrame(lignes, columns=COLONNES)


def caracteristiques_ouestfrance(html):
    """Surface et nombre de pièces lus dans le tableau de caractéristiques
    d'une page détail.

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


def _detail_ouestfrance(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        return caracteristiques_ouestfrance(page.content())
    except Exception:
        return None, None


def moissonner_ouestfrance(context, url, lire):
    """Ouest-France ne pagine pas : une liste, puis une visite par annonce pour
    la surface. Le cache (Lien -> [surface, pièces]) évite de revisiter ce qui
    a déjà été lu lors d'un run précédent."""
    page = context.new_page()
    detail = context.new_page()
    cache = _charger_cache()
    hits = 0
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        df = lire(page.content())
        print(f"[ouestfrance] {len(df)} annonces listées, récup surface sur page détail...")
        for i, href in enumerate(df["Lien"]):
            if href in cache:  # déjà scrapé auparavant → pas de re-visite
                surface, pieces = cache[href]
                hits += 1
            else:
                surface, pieces = _detail_ouestfrance(detail, href)
                cache[href] = [surface, pieces]
                detail.wait_for_timeout(800)  # délai anti-ban entre pages détail
            df.iat[i, df.columns.get_loc("Surface")] = surface
            df.iat[i, df.columns.get_loc("Pieces")] = pieces
        _sauver_cache(cache)
        print(f"[ouestfrance] {len(df)} annonce(s) récupérées ({hits} depuis le cache)")
        return df
    except Exception as e:
        print(f"[ouestfrance] Exception {e}")
        return VIDE
    finally:
        page.close()
        detail.close()


OUESTFRANCE = Source("ouestfrance", urls_ouestfrance, annonces_ouestfrance,
                     moissonner_ouestfrance)


# ═════════════════════════════════════════════════════════════
# SOURCE 3 — SELOGER (tout est sur la carte, pas de page détail)
# ═════════════════════════════════════════════════════════════
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


def urls_seloger(recherche, ville):
    return [url_seloger(ville.slug, ville.dept, ville.lat, ville.lng,
                        recherche.km, insee=ville.insee)]


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
            secteur.depuis_adresse(_sl_texte(carte, "cardmfe-description-box-address")),
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
        page.evaluate("document.querySelector('#usercentrics-root')?.remove()")
    except Exception:
        pass


def moissonner_seloger(context, url, lire):
    """SeLoger pagine par un clic : le paramètre `pg=` de l'URL est inerte (il
    rend toujours la même page), comme `ray` chez paruvendu."""
    page = context.new_page()
    frames = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        _sl_ecarter_banniere(page)
        for i in range(1, PAGES_MAX + 1):
            frames.append(lire(page.content()))
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
        return VIDE
    df = pd.concat(frames, ignore_index=True)
    print(f"[seloger] {len(df)} annonce(s) récupérées sur {len(frames)} page(s)")
    return df


SELOGER = Source("seloger", urls_seloger, annonces_seloger, moissonner_seloger)


# ═════════════════════════════════════════════════════════════
# REGISTRE
# ═════════════════════════════════════════════════════════════
SOURCES = [PARUVENDU, OUESTFRANCE, SELOGER]


def moissonner_toutes(context, recherche, ville, sources=SOURCES):
    """Moissonne toutes les sources du registre et rend leurs annonces réunies,
    ou None si aucune n'a rien rendu.

    Une source qui échoue ne coûte qu'elle-même : un run à deux sources sur
    trois vaut mieux qu'un run perdu, et c'est déjà ce que chaque scraper
    faisait pour son propre compte."""
    frames = []
    for source in sources:
        try:
            urls = source.urls(recherche, ville)
        except Exception as e:
            print(f"[{source.nom}] URLs introuvables : {e}")
            continue
        if len(urls) > 1:
            print(f"{len(urls)} recherches à parcourir sur {source.nom}.")
        for url in urls:
            try:
                frames.append(source.moissonner(context, url, source.lire))
            except Exception as e:
                print(f"[{source.nom}] Exception {e}")

    remplies = [f for f in frames if not f.empty]
    return pd.concat(remplies, ignore_index=True) if remplies else None
