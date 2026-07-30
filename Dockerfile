# Image du scraper pour un serveur sans écran (Raspberry Pi / Dokploy).
#
# Base Playwright officielle : Chromium + toutes les dépendances système déjà
# présentes, et multi-arch (l'ARM64 du Pi est couvert). Elle embarque aussi
# xvfb, dont on a besoin : le scrape tourne headful (DataDome bloque headless)
# sur un écran virtuel, faute de display réel sur le serveur.
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Couche de dépendances d'abord : elle ne change que si requirements.txt change,
# donc le rebuild d'un simple changement de code ne réinstalle pas tout.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# -e . pour exposer la commande `rent-estimator`. `playwright install chromium`
# réaligne le navigateur sur la version de playwright tirée par pip (l'image en
# fige une, pip peut en tirer une autre — sinon "browser not found" au run).
RUN pip install --no-cache-dir -e . && playwright install chromium

# Le conteneur ne scrape pas de lui-même : il vit, et le Schedule Job Dokploy
# fait un `docker exec` dedans une fois par jour (voir docker-compose.yml).
CMD ["sleep", "infinity"]
