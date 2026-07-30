# Le scrape planifié tourne headful sous Xvfb dans un conteneur

Le run quotidien supposait une session graphique macOS ouverte : `headless=False`
plus un LaunchAgent. Un matin, portable endormi dans un sac à 8h, le run a planté
— `BrowserType.launch: Timeout 180000ms exceeded`, aucun display où attacher la
fenêtre. La détection dépendait de l'état physique d'un laptop. On déplace le run
**par défaut** vers un conteneur sur un serveur sans écran (Raspberry Pi via
Dokploy), où le navigateur tourne headful sur un **écran virtuel Xvfb**.

## Contexte

`scrap.py` lance Chromium en `headless=False` : Ouest-France sert DataDome, qui
bloque le mode headless. Il faut donc une vraie fenêtre Chrome — trivial sur un
poste avec écran, impossible sur un serveur en SSH, et fragile même sur le
portable (capot fermé, session verrouillée, veille).

L'astuce Xvfb n'est pas neuve : `deploy/rent-estimator.service` (systemd)
documentait déjà `xvfb-run -a rent-estimator …`. Ce qui change ici, c'est d'en
faire le **chemin planifié par défaut**, empaqueté et reproductible, plutôt qu'un
poste personnel qui doit être ouvert, éveillé et déverrouillé à l'heure dite.

## Décision

- **Image** : base Playwright officielle (`mcr.microsoft.com/playwright/python`),
  multi-arch donc l'ARM64 du Pi est couvert, Chromium + xvfb déjà présents.
- **Conteneur oisif** (`sleep infinity`). Il ne scrape pas seul ; un **Schedule
  Job Dokploy** fait un `docker exec` une fois par jour :
  `xvfb-run -a rent-estimator --ville … --notif discord`.
- **Flags explicites, pas `--profil`.** Un profil vit dans `.config.json`, ancré
  sur `/app` (cf `config.py`), reconstruit à chaque déploiement — il
  disparaîtrait. Les flags ne dépendent d'aucun fichier persistant.
- **Seul l'Historique persiste**, sur un volume nommé via
  `RENT_ESTIMATOR_OUTPUT=/data`. Sans lui, chaque rebuild reverrait tout le
  marché comme nouveau — rafale de fausses nouveautés, détection de baisses
  cassée.
- **Secrets par variables d'env** (`DISCORD_WEBHOOK`), jamais en git ni dans
  l'image. `config.py` lit déjà l'env en priorité.
- **`chromium_sandbox` désactivé en conteneur** (`RENT_ESTIMATOR_NO_SANDBOX`) :
  Chromium refuse de démarrer en root sans `--no-sandbox`, et l'image tourne en
  root. Les runs macOS locaux gardent le sandbox actif.

## Conséquences

- **Validation DataDome/Xvfb : OK (2026-07-30).** Le premier run dans le
  conteneur sur le Pi a rendu 163 annonces dont **25 Ouest-France** — le site
  DataDome passe sous écran virtuel. La crainte du fingerprint swiftshader/WebGL
  ne s'est pas concrétisée ; l'IP résidentielle y est probablement pour beaucoup.
  Le mode macAwake (ci-dessous) n'est donc plus le filet actif, juste un repli
  documenté si le comportement de DataDome change.
- **L'IP résidentielle française du Pi est un atout** face à DataDome, là où une
  IP datacenter de VPS est plus souvent signalée.
- **Le mode macOS est retiré du chemin par défaut**, pas effacé : il survit dans
  l'historique git et reste le repli si Xvfb échoue.

## Alternatives écartées

**Garder le Mac éveillé à 8h** (LaunchAgent + `caffeinate`, empêcher le
verrouillage). Zéro infra nouvelle. Écartée comme défaut : elle rattache la
détection à l'état d'un portable — ouvert, éveillé, déverrouillé — soit
exactement la panne d'origine. Conservée comme repli si la validation Xvfb échoue.

**Un VPS cloud** plutôt que le Pi. Toujours allumé, mais IP datacenter, la plus
exposée aux blocages DataDome — à rebours du besoin. Le Pi à la maison donne le
« toujours allumé » avec une IP résidentielle.

**systemd nu sur le Pi** (`deploy/rent-estimator.service`). Valable et déjà
écrit, mais Dokploy administre déjà cette machine : dédoubler la planification
hors de Dokploy diviserait la surveillance et les logs.
