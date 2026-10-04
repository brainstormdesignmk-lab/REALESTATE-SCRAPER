# SCRAPERS_FINAL_IMPROVED

A drop-in **hardening** of the original `SCRAPERS_FINAL` project. The original
folder is untouched — this is a copy you can run side by side.

The architecture is unchanged (one base scraper per site, one `config.json` +
one SQLite DB per category, sequential batch runner, `serve_ana.py` /
`update_status.py`). **Only the fetch layer was replaced with Scrapling.**

## Why this exists

Evidence gathered from the live sites and your own databases:

| Site | Problem found | Root cause |
|---|---|---|
| REKLAMA5 | HTTP **403** on listing pages; half the category DBs froze on 28.08 | TLS/JA3 **fingerprint** blocking. Plain `requests`/curl with full browser headers -> 403. `curl_cffi impersonate="chrome"` -> 200. |
| IMOTI247 | All 8 category DBs stopped advancing after 29.08 (silently) | Selenium + `undetected-chromedriver`, pinned to Chrome **151** via `version_main` + `webdriver_manager`. Version drift / CDP deadlocks / browser death, with no loud failure. |
| PAZAR3 | Working, but same fingerprint-exposed stack as Reklama5 | Preventively hardened before it gets blocked too. |

## What changed

| File | Change |
|---|---|
| `_shared/scrapling_fetch.py` | **New.** Shared Scrapling fetch layer: `http_session()`, `http_get()`, `stealth_session()`. |
| `PAZAR3/_pazar3_scraper.py` | `requests` -> Scrapling `FetcherSession` (Chrome TLS impersonation, auto-retries). Extraction logic unchanged. |
| `REKLAMA5/_reklama5_scraper.py` | `requests.Session` -> Scrapling `FetcherSession`. **This is the fix for the 403.** |
| `IMOTI247/_imoti247_scraper.py` | Selenium/undetected-chromedriver -> one reusable Scrapling `StealthySession`. No chromedriver pinning, no process-tree killing, lazy-load scrolling handled with a `page_action`. |
| `batch_scraper.py` | Adds `--site`, `--limit`, `--dry-run`; runs children with the same interpreter (venv). |
| `healthcheck.py` | **New.** Pre-flight check that runs even before Scrapling is installed. |

Every scraper now also **counts blocked responses** and prints them in the
summary, so a silent block can never again look like "no new ads".

## Requirements

- **Python >= 3.10** (Scrapling requirement). The original project runs on 3.9.
- For IMOTI247: the browser binaries (`scrapling install`), ~a few hundred MB.

## Setup

```bash
cd SCRAPERS_FINAL_IMPROVED
./setup.sh                  # venv + Python deps  (PAZAR3 + REKLAMA5 ready)
./setup.sh --with-browser   # also download the browser for IMOTI247
```

`setup.sh` auto-detects `python3.13/3.12/3.11/3.10`. On Debian without one:
`sudo apt install python3.11 python3.11-venv`.

## Usage

```bash
# Pre-flight (works even before the venv exists)
python3 healthcheck.py
python3 healthcheck.py --network      # also test reachability (needs Scrapling)

# Everything
.venv/bin/python batch_scraper.py
.venv/bin/python batch_scraper.py --dry-run
.venv/bin/python batch_scraper.py --site REKLAMA5
.venv/bin/python batch_scraper.py --limit 1     # smoke test

# One category directly
.venv/bin/python PAZAR3/_pazar3_scraper.py PAZAR3/P3_STANOVI_RENTA/
.venv/bin/python REKLAMA5/_reklama5_scraper.py REKLAMA5/R5_STANOVI_RENTA/
.venv/bin/python IMOTI247/_imoti247_scraper.py IMOTI247/I247_STANOVI_RENTA/

# Ana's pipeline is unchanged
.venv/bin/python serve_ana.py
.venv/bin/python update_status.py output/ana_batch_YYYY-MM-DD.csv
```

## IBM T40 / Core 2 Duo / 3 GB RAM notes

- PAZAR3 and REKLAMA5 use **no browser** (HTTP only) — very light, fine on 3 GB.
- IMOTI247 runs **one** Chromium instance at a time, reused for the whole
  category (not restarted per ad). Expect the machine to be busy during that
  phase; close other applications.
- Run one category at a time (the batch runner already does this).
- If IMOTI247 is too heavy for the T40, you can run the other two sites and
  scrape IMOTI247 from a stronger machine, since each category has its own DB.

## Rollback

The original `SCRAPERS_FINAL` tree was not modified. Delete this folder to roll
back; your data lives in the per-category `data/*.db` files (copied here, so
dedup and history continue).
