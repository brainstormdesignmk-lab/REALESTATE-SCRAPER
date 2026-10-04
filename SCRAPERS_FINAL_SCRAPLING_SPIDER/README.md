# SCRAPERS_FINAL_SCRAPLING_SPIDER

A full **Scrapling Spider** re-implementation of the scrapers. Same data
contract as the original (one `config.json` + one SQLite DB per category, same
`listings` schema), so `serve_ana.py` and `update_status.py` work unchanged.

Your original `SCRAPERS_FINAL` folder is untouched — this runs side by side.

## What this variant buys you

The Scrapling Spider framework replaces the hand-rolled loops in
`batch_scraper.py` + the per-site base scrapers with:

- **Multi-session routing** in a single spider — HTTP (curl_cffi) for
  PAZAR3/REKLAMA5 and their side requests, and a stealth browser for IMOTI247.
- **Blocked-request detection + retry** built in (`max_blocked_retries`).
- **AutoThrottle** — tunes per-domain delay from how the site responds and
  backs off automatically when it pushes back.
- **Checkpoint / resume** (`--crawldir`) for long runs.
- **Streaming items straight into SQLite** (`on_scraped_item`), so memory use
  stays flat even on a 3 GB machine.

## Docs & setup

```bash
cd SCRAPERS_FINAL_SCRAPLING_SPIDER
./setup.sh                  # venv + Python deps
./setup.sh --with-browser   # also download the browser (needed for IMOTI247)
```

Requires **Python >= 3.10**.

## Usage

```bash
# List what would run
.venv/bin/python run_spiders.py --dry-run

# Smoke test one fast site
.venv/bin/python run_spiders.py --site REKLAMA5 --limit 1

# Everything, sequentially, one spider per category
.venv/bin/python run_spiders.py

# One site, with checkpoint/resume enabled
.venv/bin/python run_spiders.py --site IMOTI247 --crawldir ./crawl_data

# Ana's pipeline is unchanged
.venv/bin/python serve_ana.py
.venv/bin/python update_status.py output/ana_batch_YYYY-MM-DD.csv
```

## Layout

```
spiders/
  base.py            BaseCategorySpider: config, DB sink, HTTP session, politeness
  parsers.py         site-specific phone / price / size / image extraction
  pazar3_spider.py   listing -> ad pages (HTTP)
  reklama5_spider.py listing -> ad pages + ShowPhone fallback (HTTP)
  imoti247_spider.py listing + ad pages (browser) -> phone AJAX (HTTP)
run_spiders.py       runs one spider per category, sequentially
```

## How IMOTI247 works here

IMOTI247's listing pages are **JavaScript-rendered** — a plain HTTP GET returns
zero ad links (verified). So the spider routes listing and ad pages through the
async stealth browser session, and fetches the phone from the HTML/imoti247
AJAX endpoint through the fast HTTP session:

```
listing (browser) -> ad page (browser): title + images -> phone AJAX (HTTP) -> item
```

A `page_action` scrolls listing pages to trigger lazy loading. It is skipped on
ad pages (their URLs end in `.html`), so it costs nothing on those.

## Low-RAM tuning

Defaults are already conservative (`concurrent_requests = 1`, `download_delay`,
AutoThrottle on). If the T40 struggles, the knobs live in `spiders/base.py`
and `spiders/imoti247_spider.py`:

- lower `timeout`/`network_idle` impact by keeping `disable_resources=False`
  (needed because images are scraped from the DOM),
- reduce `pages` in the relevant `config.json`,
- run sites separately with `--site`.

## Rollback

Delete this folder. The original project and its data are untouched.
