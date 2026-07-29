# Rent Estimator

Outil de détection de locations sous-cotées : scrape des annonces, estime un loyer de marché, signale les affaires.

## Language

**Recherche**:
Ce qu'un run couvre : une ville, un rayon, des filtres. Elle porte le nom du **Profil** qui la rejoue, ou celui de sa ville si elle n'a pas été sauvée. Chaque Recherche garde son propre **Historique** — sinon la détection des nouveautés comparerait un marché à un autre.
_Avoid_: run, requête, compartiment

**Profil**:
Une **Recherche** nommée et sauvegardée, plus son **Canal**, qu'on rejoue sans tout ressaisir.
_Avoid_: config, preset, réglage

**Bon plan** (Deal):
Une annonce dont le prix affiché est nettement sous son loyer estimé.
_Avoid_: opportunité, affaire (dans le code)

**Décote**:
L'écart en % entre le prix affiché et le loyer estimé (négatif = sous le marché).
_Avoid_: réduction, rabais

**Canal**:
Le moyen de recevoir ce qu'un run a à dire — ses **Bons plans**, ou son **Alerte** s'il n'a rien pu produire (terminal, macOS, Telegram, Email, Discord).
_Avoid_: notif, sortie

**Alerte**:
Le message qu'un run émet quand il n'a **pas pu** produire de bons plans : crash inattendu, ou trop peu d'annonces pour estimer. Elle part sur le même **Canal** que les bons plans, mais n'en est pas un — c'est un signal technique, pas une affaire. Un run réussi mais sans bon plan ne l'émet PAS : l'absence d'affaire est un résultat normal, pas un incident.
_Avoid_: erreur, log, notif

**Historique**:
Le journal des annonces déjà vues, servant à détecter les nouveautés et les baisses de prix.
_Avoid_: log, cache

**Secteur**:
La maille géographique sur laquelle le modèle apprend le prix. Vaut la **commune** dans le cas général, mais l'**arrondissement** pour les villes à arrondissements (Paris, Lyon, Marseille), où toute la ville est une seule commune. C'est la clé One-Hot du modèle — et chaque **Source** l'écrivant à sa façon, c'est la clé, pas le libellé, qui doit concorder.
_Avoid_: quartier, zone, ville

**Source**:
Un site d'où viennent les annonces (paruvendu, Ouest-France, SeLoger). Une Source dit quelles URLs couvrent une **Recherche**, sait lire une page de résultats, et connaît sa propre façon de paginer — les trois paginent différemment et rien ne peut les unifier là-dessus.
_Avoid_: scraper, site, provider

**Estimation peu fiable**:
Marqueur porté par un **Bon plan** dont le **Secteur** a trop peu d'annonces pour une estimation solide. Le bon plan est montré quand même, avec l'aveu d'incertitude — jamais masqué.
_Avoid_: invalide, rejeté

**Hors marché**:
Annonce dont le prix au m² sort du marché observé sur le run, sans pour autant être invraisemblable. Elle est évaluée et peut devenir un **Bon plan**, mais elle n'entre pas dans l'apprentissage du modèle : trop douteuse pour enseigner, trop intéressante pour être jetée.
_Avoid_: aberration, outlier, atypique

## Relationships

- Un **Profil** fixe une **Recherche** + un **Canal**
- Un run moissonne toutes les **Sources** ; l'une en panne ne coûte qu'elle-même
- Un run qui ne peut rien produire (crash, trop peu d'annonces) émet une **Alerte** sur son **Canal** ; un run sans bon plan reste muet
- Un run couvre plusieurs **Secteurs** ; le modèle compare les prix entre eux (One-Hot)
- Un run produit des **Bons plans**, chacun avec sa **Décote**
- L'**Historique** distingue les **Bons plans** nouveaux des déjà-vus
- Une annonce **Hors marché** est évaluée mais n'entraîne pas le modèle ; les autres font les deux

## Flagged ambiguities

- Les **identifiants** d'un **Canal** (webhook, token) sont globaux, PAS stockés par **Profil** — un même webhook Discord sert tous les profils.
