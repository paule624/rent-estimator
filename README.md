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
3. **Cleaning** — merges sources, deduplicates the same listing across sites, removes colocations/room rentals (they distort price-per-m²), imputes missing DPE, drops price/m² outliers using bounds derived from the run's own data (so Brittany and Paris both work, with no per-city table).
4. **Modeling** — `RandomForestRegressor` on `log1p(rent)`, One-Hot encoded **area** — the arrondissement where the city has them, the commune everywhere else — plus surface, rooms, DPE, and avg room size.
5. **Deal detection** — `cross_val_predict` for unbiased estimates; listings ≥15% below estimate, within budget and above a surface floor, are exported. A deal whose area has fewer than 5 listings is flagged **estimation peu fiable** rather than hidden: too thin an area drops out of the training folds, so its estimate stops accounting for location.

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

`--profil <name>` replays a saved search with no prompts, which is the form to
schedule. Ready-made units live in [`deploy/`](deploy/); each one carries its
install commands in its header.

Two constraints shape every option below. The scraper drives a **visible**
Chromium — DataDome blocks headless — so the run needs a display. And a
notification nobody reads is a run wasted: pick a remote channel (Discord is the
least setup) rather than `terminal` or `macos`, so the deals reach you whether
or not you are at the machine.

| OS | Use | Missed runs |
|----|-----|-------------|
| macOS | `deploy/com.rent-estimator.daily.plist` (LaunchAgent) | run on wake |
| Linux | `deploy/rent-estimator.{service,timer}` (systemd user timer) | run at next boot (`Persistent=true`) |
| Windows | Task Scheduler, see below | *Run task as soon as possible after a scheduled start is missed* |

**Why not cron on macOS.** `cron` runs detached from the logged-in graphical
session, so a windowed Chromium starts badly or not at all, and it needs Full
Disk Access granted to `/usr/sbin/cron` to boot. Above all: if the Mac is asleep
at the scheduled time, cron skips the slot and never catches up. On a laptop
closed overnight, that is the difference between a tool that runs and one that
never does. `launchd` runs the missed job on wake.

**macOS: keep the repo out of `~/Documents`.** That folder — like `~/Desktop`
and `~/Downloads` — is protected by TCC, and a process started by launchd has no
access to it. The run dies before Python finishes booting:

```
PermissionError: [Errno 1] Operation not permitted: '.../.venv/pyvenv.cfg'
```

Manual runs work regardless, since the terminal already holds that permission,
so this only ever surfaces on the scheduled run — in the log. Somewhere like
`~/dev/` carries no such restriction. Granting Full Disk Access to the Python
interpreter also works, but that interpreter is shared: every script you run
with it would inherit the same access.

**Headless Linux servers** need a virtual display — the unit calls `xvfb-run`
for that (`apt install xvfb`). On a desktop session with a real display, drop
the prefix.

**Windows**, once a day at 08:00:

```powershell
schtasks /create /tn "rent-estimator" /sc daily /st 08:00 ^
  /tr "C:\path\to\repo\.venv\Scripts\rent-estimator.exe --profil Vannes-2"
```

**Why not CI.** GitHub Actions cannot run this: beyond the headless problem, a
datacenter IP is blocked by DataDome within seconds. CI is for the test suite,
not for scraping.

Nothing watches the terminal on a scheduled run, so a site changing its markup
would fail in silence. The macOS unit writes to `output/run.log`; systemd keeps
it in `journalctl --user -u rent-estimator`.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

Covers parsing helpers, area extraction, SeLoger card parsing (against real
captured HTML in `tests/fixtures/`), cleaning (colocation removal, dedup, DPE
imputation, outlier filtering), the history diff logic, and notification
splitting.

CI runs the same suite on every push and pull request. The scrapers are not
exercised there — DataDome blocks headless browsers and datacenter IPs — so
after a change to `scrap.py`, run it once against the real sites before
trusting a green build.

## Files

- `main.py` — CLI orchestrator (interactive prompts + flags).
- `scrap.py` — geo resolver, URL builder, paruvendu + Ouest-France + SeLoger scrapers, cache.
- `model.py` — cleaning, preprocessing, ML training, deal extraction.
- `historique.py` — run history + new-deal / price-drop detection.
- `notif.py` — notification channels (terminal, macOS, Telegram, email, Discord).
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
