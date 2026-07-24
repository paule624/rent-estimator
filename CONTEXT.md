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

## Relationships

- Un **Profil** fixe une recherche + un **Canal**
- Un run produit des **Bons plans**, chacun avec sa **Décote**
- L'**Historique** distingue les **Bons plans** nouveaux des déjà-vus

## Flagged ambiguities

- Les **identifiants** d'un **Canal** (webhook, token) sont globaux, PAS stockés par **Profil** — un même webhook Discord sert tous les profils.
