# Rent Estimator & Deal Finder (France)

[![tests](https://github.com/paule624/rent-estimator/actions/workflows/tests.yml/badge.svg)](https://github.com/paule624/rent-estimator/actions/workflows/tests.yml)

A Data Science pipeline that scrapes real-time rental listings for **any French city**, estimates a fair market rent with Machine Learning, and flags listings priced below their estimated value.

Started from [BL1ZZ4RD-PY/Paris-Housing-Price-Estimator-Deal-Finder](https://github.com/BL1ZZ4RD-PY/Paris-Housing-Price-Estimator-Deal-Finder),
a Paris-only pipeline, and generalized to any French city: three sources instead
of one, automatic geo-resolution, a CLI with saved profiles, notifications, run
history, and a test suite.

## What it does

```
CLI args (city, radius, budget)
   → resolve INSEE/postal via geo.api.gouv.fr
   → scrape paruvendu + Ouest-France Immo + SeLoger (Playwright)
   → clean, dedupe, drop colocations
   → estimate fair rent (RandomForest, out-of-fold)
   → export under-valued listings with clickable links
```

## Pipeline

1. **Geo resolution** — city name → INSEE code + postal code via the free `geo.api.gouv.fr` API, used to build each site's search URL. Cities with arrondissements get one search per arrondissement (see below).
2. **Scraping** — `paruvendu.fr` (full market), `ouestfrance-immo.com` (surface fetched from each detail page) and `seloger.com` (everything on the result card, one search per city including Paris). Runs non-headless to bypass DataDome anti-bot.
3. **Cleaning** — merges sources, deduplicates the same listing across sites, removes colocations/room rentals (they distort price-per-m²), imputes missing DPE. A price/m² below an absolute floor is dropped as a parsing error — a misread low price would fabricate a spectacular fake deal. There is no matching ceiling: an overpriced misread produces nothing (its discount is positive), and the percentiles keep it out of training anyway. A price/m² merely outside the run's own percentile range is kept and flagged **hors marché** — an underpriced listing is, by definition, abnormally cheap per m², so dropping it would delete what the tool is looking for (see `docs/adr/0004`). Bounds derive from the run's own data, so Brittany and Paris both work with no per-city table.
4. **Modeling** — `RandomForestRegressor` on `log1p(rent)`, One-Hot encoded **area** — the arrondissement where the city has them, the commune everywhere else — plus surface, rooms, DPE, and avg room size. **Hors marché** listings are excluded from training: too doubtful to teach the model, still worth scoring.
5. **Deal detection** — `cross_val_predict` for unbiased estimates on the observed market, plain `predict` for hors marché listings (they never trained, so this is genuinely out-of-sample). Listings ≥15% below estimate, within budget and above a surface floor, are exported. A deal whose area has fewer than 5 **trained** listings is flagged **estimation peu fiable** rather than hidden: too thin an area drops out of the training folds, so its estimate stops accounting for location. Hors marché deals are listed last and counted separately — their discount is the largest but the least credible, and notifications are capped.

## Usage

```bash
pip install -e .            # installs deps + the `rent-estimator` command
playwright install chromium

rent-estimator                       # interactive: arrow-key menu of saved profiles
rent-estimator --profil vannes       # replay a saved profile, no prompts (for cron)
rent-estimator --ville Auray --km 15 --max 800   # explicit flags, no prompts
rent-estimator --ville Paris         # all 20 arrondissements, no price cap
```

**Profiles.** A run's settings (city, radius, budget, min surface, notification
channel) can be saved as a named **profile**. On launch, an arrow-key menu lists
your profiles with the last-used one pre-selected — press Enter to replay it, or
pick another / create a new search / delete one. Profiles live in `.config.json`.

Run `python main.py` if you prefer not to install the package.

**Nothing is applied unless you ask for it.** The values shown greyed out in the
prompts are examples, not defaults — leave a field empty and you get no
constraint at all. Omitting a flag does the same, so `--ville Paris` searches
Paris itself with no price or surface cap rather than inheriting someone else's
budget.

| Flag | Omitted | Meaning |
|------|---------|---------|
| `--ville` | *required* | City to search |
| `--km` | the commune only | Radius around the city (km) |
| `--max` | no cap | Max monthly rent for exported deals (€) |
| `--surface-min` | no minimum | Minimum surface for exported deals (m²) |

### Cities with arrondissements

Paris, Lyon and Marseille are each a *single* commune, so the commune name
carries no price signal — the arrondissement does. These cities are searched one
arrondissement at a time (20 searches for Paris), which is both the only INSEE
code the sources accept and the only way to get clean per-arrondissement data.
The model then compares arrondissements against each other, so a flat in the
16th is judged against the 16th, not against the 19th.

SeLoger is the exception: each of its result cards carries its own postal code,
so one search covers every arrondissement at once. Its search area is a circle
we compute from `--km` and encode into the URL — see `docs/adr/0003`.

`--km 0` (or an empty radius) keeps the search inside the city. A radius above 0
pulls in the surrounding communes, which join the comparison as their own areas
alongside the arrondissements.

**Output:** deals are printed in the terminal (with links) and written to
`output/<search>/Appartement_interessant.csv`.

Everything a run produces lands in `output/`, which is git-ignored: the scraped
corpus, the exported deals, the history and the detail cache. Each search gets
its own subdirectory — named after the profile, or after the city when the run
comes from flags:

```
output/
├── vannes-2/       # profile
│   ├── Data_Loyer.csv              scraped market, rewritten every run
│   ├── Appartement_interessant.csv exported deals
│   ├── historique.csv              append-only, drives new/price-drop detection
│   └── cache_of.json
└── paris/          # rent-estimator --ville Paris
```

Two searches must not share a directory: a Paris run would overwrite the Vannes
corpus, and — worse — a shared history would compare one market against another
and report every listing as new.

`Data_Loyer.csv` is a snapshot of the market at one moment, not a ledger: it is
rewritten, never appended to. Accumulating it would train the model on listings
that are months dead and count returning ones twice. The accumulation you want
is `historique.csv`, which is append-only by design.

The directory is anchored to the repo, not to the working directory, so a
scheduled run reads and writes the same history as a manual one. Set
`RENT_ESTIMATOR_OUTPUT` to put it somewhere else.

## Extras

- **Notifications** — at startup you pick a channel (terminal, macOS,
  Telegram, Email, or Discord); new deals or price drops are then pushed
  there. Remote channels read credentials from the environment:
  - Telegram: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
  - Email: `EMAIL_FROM`, `EMAIL_PASSWORD`, `EMAIL_TO` (opt.), `SMTP_HOST`/`SMTP_PORT` (opt.)
  - Discord: `DISCORD_WEBHOOK` (simplest — just paste a webhook URL)
- **History** — each run appends to `output/historique.csv`; the next run diffs
  against it to detect new listings and price drops.
- **Detail cache** — Ouest-France detail pages are cached in
  `output/cache_of.json` so re-runs skip already-seen listings (much faster,
  fewer requests).

## Running it on a schedule

Two constraints shape every option below. The scraper drives a **visible**
Chromium — DataDome blocks headless — so the run needs a display. And a
notification nobody reads is a run wasted: pick a remote channel (Discord is the
least setup) rather than `terminal` or `macos`, so the deals reach you whether
or not you are at the machine.

### Recommended: a container on an always-on box

The scheduled run lives in a Docker container on a small always-on machine — a
Raspberry Pi here, managed by [Dokploy](https://dokploy.com). It is the default
because it decouples the detection from a personal laptop: a Mac asleep in a bag
at 08:00 crashed the run with `BrowserType.launch: Timeout` — no display to
attach the window to. See [ADR 0005](docs/adr/0005-scrape-planifie-headful-sous-xvfb-en-conteneur.md).

The visible-Chromium constraint is met with a **virtual display**: the run is
launched under `xvfb-run`, so Chromium runs headful on an in-memory framebuffer
and DataDome sees a real browser. A home residential IP helps here where a
datacenter one would be flagged. Validated: a first run returned 163 listings
including 25 from Ouest-France, the DataDome-guarded source.

The image ([`Dockerfile`](Dockerfile)) builds on Playwright's official
multi-arch image (Chromium + `xvfb` preinstalled, arm64 covered). The service
([`docker-compose.yml`](docker-compose.yml)) just stays alive (`sleep infinity`);
a **Dokploy Schedule Job** `docker exec`s the scrape once a day:

```
xvfb-run -a rent-estimator --ville Vannes --km 10 --max 700 --surface-min 34 --notif discord
```

Explicit flags, not `--profil`: a saved profile lives in `.config.json`, anchored
on `/app` and rebuilt away on every deploy. Only the **Historique** persists, on
a named volume via `RENT_ESTIMATOR_OUTPUT=/data`. Set these in Dokploy:

| Key | Value | Why |
|-----|-------|-----|
| `DISCORD_WEBHOOK` | *(the webhook)* | secret — Dokploy env, never in git or the image |
| `RENT_ESTIMATOR_OUTPUT` | `/data` | run artefacts on the persistent volume |
| `RENT_ESTIMATOR_NO_SANDBOX` | `1` | Chromium refuses to start as root without `--no-sandbox`; the container runs as root |
| `TZ` | `Europe/Paris` | the container is UTC by default — 08:00 UTC is 10:00 Paris in summer |

### Adding another search

One more search is **one more Schedule Job** — no code, no redeploy, same
container and volume. Point it at a different city:

```
xvfb-run -a rent-estimator --ville Rennes --km 15 --max 800 --surface-min 30 --notif discord
```

Each Recherche keeps its own Historique: `config.definir_recherche` files run
artefacts under `/data/<city>/` (`/data/vannes/`, `/data/rennes/`), so newness
detection never compares one market to another. Stagger the cron minutes across
jobs (`0 8`, `20 8`, `40 8`) so the sites are not all hit on the dot.

**Caveat — two searches on the *same* city.** Under flags the subfolder is the
city slug, not the filters, so two `--ville Vannes` jobs would share
`/data/vannes/historique.csv` and merge their histories. Different cities are
fine. For several searches on one city you need a distinct name per search —
that is what `--profil` gave (subfolder = profile name); reintroduce
`.config.json` on the volume if that case comes up.

### Alternatives: self-hosted on your own machine

Without a server, run it on the machine you already have. Ready-made units live
in [`deploy/`](deploy/); each carries its install commands in its header.

| OS | Use | Missed runs |
|----|-----|-------------|
| Linux | `deploy/rent-estimator.{service,timer}` (systemd user timer) | run at next boot (`Persistent=true`) |
| Windows | Task Scheduler, see below | *Run task as soon as possible after a scheduled start is missed* |
| macOS | LaunchAgent, `git rm`'d in favour of the container — recover from history if needed | ran on wake |

On a headless Linux box these units also call `xvfb-run` (`apt install xvfb`);
on a desktop session with a real display, drop the prefix.

**Why not cron on macOS.** `cron` runs detached from the logged-in graphical
session, so a windowed Chromium starts badly or not at all, and it needs Full
Disk Access granted to `/usr/sbin/cron` to boot. If the Mac is asleep at the
scheduled time, cron skips the slot and never catches up — `launchd` runs the
missed job on wake. And keep the repo out of TCC-protected `~/Documents`,
`~/Desktop`, `~/Downloads`: a launchd-started process cannot read them and dies
with `PermissionError: Operation not permitted` on `.venv/pyvenv.cfg` before
Python finishes booting. Somewhere like `~/dev/` carries no such restriction.

**Windows**, once a day at 08:00:

```powershell
schtasks /create /tn "rent-estimator" /sc daily /st 08:00 ^
  /tr "C:\path\to\repo\.venv\Scripts\rent-estimator.exe --profil Vannes-2"
```

**Why not CI.** GitHub Actions cannot run this: beyond the headless problem, a
datacenter IP is blocked by DataDome within seconds. CI is for the test suite,
not for scraping.

Nothing watches the terminal on a scheduled run, so a site changing its markup
would fail in silence. In the container the Schedule Job output is the log; the
systemd unit keeps it in `journalctl --user -u rent-estimator`.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

Covers parsing helpers, sector extraction and its One-Hot key, card parsing for
SeLoger (against real captured HTML in `tests/fixtures/`) and paruvendu
(against a reconstructed fixture — see its header), cleaning (colocation
removal, dedup, DPE imputation, outlier filtering), the history diff logic,
notification splitting, and a full run replayed from a hand-held DataFrame
instead of a browser (`tests/test_recherche.py`).

CI runs the same suite on every push and pull request. The scrapers are not
exercised there — DataDome blocks headless browsers and datacenter IPs — so
after a change to `sources.py` or `scrap.py`, run it once against the real
sites before trusting a green build.

## Files

- `main.py` — CLI: prompts, flags, and terminal rendering.
- `recherche.py` — a Recherche and its run; `executer()` takes the harvest step as a parameter, so a run replays from a CSV without a browser.
- `scrap.py` — geo resolver (geo.api.gouv.fr) and browser launch.
- `sources.py` — one contiguous block per source: its URLs, `lire(html)`, and how it paginates.
- `secteur.py` — the Secteur: four extractors and the One-Hot key they must agree on.
- `model.py` — cleaning, preprocessing, ML training, deal extraction.
- `bons_plans.py` — the market / off-market split shared by terminal and notification.
- `historique.py` — run history + new-deal / price-drop detection.
- `notif.py` — what the message says; `canaux.py` — where it goes (terminal, macOS, Telegram, email, Discord).
- `config.py` — saved profiles, channel credentials, output paths.
- `tests/` — pytest suite.
- `output/` — everything a run produces (git-ignored).

## Notes & limits

- **Small markets** → fewer listings → lower R² (real constraint, not a bug).
- **Non-headless** → a Chrome window opens during scraping (needed for anti-bot).
- **Selectors** may break if the target sites change their HTML.
- Discounts are **estimates**: a flagged "deal" can hide a defect the scraper can't see (no elevator, ground floor, works needed). Treat as leads to verify in person.

## License

[MIT](LICENSE). The upstream project it grew out of carries no license of its
own; the derived portions are credited in `LICENSE` and above.
