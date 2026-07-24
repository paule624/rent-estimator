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
pip install -e .            # installs deps + the `rent-estimator` command
playwright install chromium

rent-estimator             # interactive: asks city, radius, budget, min surface
rent-estimator --ville Auray --km 15 --max 800   # or pass flags to skip prompts
```

Run `python main.py` if you prefer not to install the package.

| Flag | Default | Meaning |
|------|---------|---------|
| `--ville` | Vannes | City to search |
| `--km` | 10 | Radius around the city (km) |
| `--max` | 700 | Max monthly rent for exported deals (€) |
| `--surface-min` | 33 | Minimum surface for exported deals (m²) |

**Output:** deals are printed in the terminal (with links) and written to
`Appartement_interessant.csv` (opened automatically on macOS).

## Extras

- **Notifications** — at startup you pick a channel (terminal, macOS,
  Telegram, Email, or Discord); new deals or price drops are then pushed
  there. Remote channels read credentials from the environment:
  - Telegram: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
  - Email: `EMAIL_FROM`, `EMAIL_PASSWORD`, `EMAIL_TO` (opt.), `SMTP_HOST`/`SMTP_PORT` (opt.)
  - Discord: `DISCORD_WEBHOOK` (simplest — just paste a webhook URL)
- **History** — each run appends to `historique.csv`; the next run diffs
  against it to detect new listings and price drops.
- **Detail cache** — Ouest-France detail pages are cached in `cache_of.json`
  so re-runs skip already-seen listings (much faster, fewer requests).

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

Covers parsing helpers, commune extraction, cleaning (colocation removal,
dedup, DPE imputation, outlier filtering), and the history diff logic.

## Files

- `main.py` — CLI orchestrator (interactive prompts + flags).
- `scrap.py` — geo resolver, URL builder, paruvendu + Ouest-France scrapers, cache.
- `model.py` — cleaning, preprocessing, ML training, deal extraction.
- `historique.py` — run history + new-deal / price-drop detection.
- `notif.py` — macOS + Telegram notifications.
- `tests/` — pytest suite.
- `Appartement_interessant.csv` — exported deals.

## Notes & limits

- **Small markets** → fewer listings → lower R² (real constraint, not a bug).
- **Non-headless** → a Chrome window opens during scraping (needed for anti-bot).
- **Selectors** may break if the target sites change their HTML.
- Discounts are **estimates**: a flagged "deal" can hide a defect the scraper can't see (no elevator, ground floor, works needed). Treat as leads to verify in person.
