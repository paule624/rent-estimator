# Rent Estimator

Outil de détection de locations sous-cotées : scrape des annonces, estime un loyer de marché, signale les affaires.

## Language

**Profil**:
Un jeu de paramètres nommé et sauvegardé (recherche + canal de notif) qu'on rejoue sans tout ressaisir.
_Avoid_: config, preset, réglage

**Bon plan** (Deal):
Une annonce dont le prix affiché est nettement sous son loyer estimé.
_Avoid_: opportunité, affaire (dans le code)

**Décote**:
L'écart en % entre le prix affiché et le loyer estimé (négatif = sous le marché).
_Avoid_: réduction, rabais

**Canal**:
Le moyen de recevoir les bons plans à la fin d'un run (terminal, macOS, Telegram, Email, Discord).
_Avoid_: notif, sortie

**Historique**:
Le journal des annonces déjà vues, servant à détecter les nouveautés et les baisses de prix.
_Avoid_: log, cache

**Secteur**:
La maille géographique sur laquelle le modèle apprend le prix. Vaut la **commune** dans le cas général, mais l'**arrondissement** pour les villes à arrondissements (Paris, Lyon, Marseille), où toute la ville est une seule commune. C'est la clé One-Hot du modèle.
_Avoid_: quartier, zone, ville

**Estimation peu fiable**:
Marqueur porté par un **Bon plan** dont le **Secteur** a trop peu d'annonces pour une estimation solide. Le bon plan est montré quand même, avec l'aveu d'incertitude — jamais masqué.
_Avoid_: invalide, rejeté

**Hors marché**:
Annonce dont le prix au m² sort du marché observé sur le run, sans pour autant être invraisemblable. Elle est évaluée et peut devenir un **Bon plan**, mais elle n'entre pas dans l'apprentissage du modèle : trop douteuse pour enseigner, trop intéressante pour être jetée.
_Avoid_: aberration, outlier, atypique

## Relationships

- Un **Profil** fixe une recherche + un **Canal**
- Un run couvre plusieurs **Secteurs** ; le modèle compare les prix entre eux (One-Hot)
- Un run produit des **Bons plans**, chacun avec sa **Décote**
- L'**Historique** distingue les **Bons plans** nouveaux des déjà-vus
- Une annonce **Hors marché** est évaluée mais n'entraîne pas le modèle ; les autres font les deux

## Flagged ambiguities

- Les **identifiants** d'un **Canal** (webhook, token) sont globaux, PAS stockés par **Profil** — un même webhook Discord sert tous les profils.
