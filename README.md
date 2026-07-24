# Rent Estimator & Deal Finder (France)

A Data Science pipeline that scrapes real-time rental listings for **any French city**, estimates a fair market rent with Machine Learning, and flags listings priced below their estimated value.

Forked from a Paris-only project and generalized: multi-source scraping, automatic geo-resolution, and a CLI.

## What it does

```
CLI args (city, radius, budget)
   → resolve INSEE/postal via geo.api.gouv.fr
   → scrape paruvendu + Ouest-France Immo (Playwright)
   → clean, dedupe, drop colocations
   → estimate fair rent (RandomForest, out-of-fold)
   → export under-valued listings with clickable links
```

## Pipeline

1. **Geo resolution** — city name → INSEE code + postal code via the free `geo.api.gouv.fr` API, used to build each site's search URL.
2. **Scraping** — `paruvendu.fr` (full market) and `ouestfrance-immo.com` (surface fetched from each detail page). Runs non-headless to bypass DataDome anti-bot.
3. **Cleaning** — merges sources, deduplicates the same listing across sites, removes colocations/room rentals (they distort price-per-m²), imputes missing DPE, filters price/m² outliers.
4. **Modeling** — `RandomForestRegressor` on `log1p(rent)`, One-Hot encoded commune (normalized across sources), plus surface, rooms, DPE, and avg room size.
5. **Deal detection** — `cross_val_predict` for unbiased estimates; listings ≥15% below estimate, within budget and above a surface floor, are exported.

## Usage

```bash
pip install -r requirements.txt
playwright install chromium

python main.py --ville Vannes --km 10 --max 700 --surface-min 33
python main.py --ville Auray --km 15 --max 800
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--ville` | Vannes | City to search |
| `--km` | 10 | Radius around the city (km) |
| `--max` | 700 | Max monthly rent for exported deals (€) |
| `--surface-min` | 33 | Minimum surface for exported deals (m²) |

**Output:** `Appartement_interessant.csv` — under-valued listings, sorted by discount, with a direct `Lien` (link) to each ad.

## Files

- `main.py` — CLI orchestrator.
- `scrap.py` — geo resolver, URL builder, paruvendu + Ouest-France scrapers.
- `model.py` — cleaning, preprocessing, ML training, deal extraction.
- `Data_Loyer.csv` — all scraped listings (sorted best-value first).
- `Appartement_interessant.csv` — exported deals.

## Notes & limits

- **Small markets** → fewer listings → lower R² (real constraint, not a bug).
- **Non-headless** → a Chrome window opens during scraping (needed for anti-bot).
- **Selectors** may break if the target sites change their HTML.
- Discounts are **estimates**: a flagged "deal" can hide a defect the scraper can't see (no elevator, ground floor, works needed). Treat as leads to verify in person.
