"""Le Secteur est la clé One-Hot du modèle (cf CONTEXT.md, docs/adr/0002).

Quatre extracteurs l'alimentent, un par forme de source. Ils doivent converger :
un même Secteur écrit de deux façons devient deux catégories One-Hot, et la
comparaison entre Secteurs — la raison d'être du modèle — se perd en silence.
"""
import secteur


def test_la_cle_ignore_accents_casse_et_separateur():
    assert secteur.cle("Saint-Avé") == secteur.cle("Saint Ave") == "saint-ave"
    assert secteur.cle("VANNES") == "vannes"
    assert secteur.cle("Séné") == "sene"


def test_les_quatre_extracteurs_donnent_la_meme_cle_pour_un_meme_arrondissement():
    cles = {secteur.cle(s) for s in (
        secteur.depuis_cp("75015", "Paris"),
        secteur.depuis_titre("Appartement 52 m2 Paris 15"),
        secteur.depuis_url_of("/immobilier/location/appartement/paris-75-75015/x.htm"),
        secteur.depuis_adresse("Beaugrenelle, Paris (75015)"),
    )}
    assert len(cles) == 1


def test_les_quatre_extracteurs_donnent_la_meme_cle_pour_une_meme_commune():
    # Ouest-France reconstruit la commune depuis le slug de son URL et rend
    # "Saint Ave" ; les deux autres sources lisent "Saint-Avé". Sans une clé qui
    # les fusionne, le modèle apprend deux fois un demi-marché sur la même
    # commune, et chaque moitié passe sous le seuil de fiabilité.
    cles = {secteur.cle(s) for s in (
        secteur.depuis_url_of("/immobilier/location/maison/saint-ave-56-56890/t3.htm"),
        secteur.depuis_titre("Maison 79 m2 Saint-Avé (56)"),
        secteur.depuis_adresse("Centre, Saint-Avé (56890)"),
    )}
    assert len(cles) == 1
