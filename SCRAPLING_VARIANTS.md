# Scrapling migration — two variants (deployed & tested on the T60/T40)

Two independent projects next to the original. **`SCRAPERS_FINAL/` is untouched.**

```
SCRAPERS_FINAL/                     <- original (not modified)
SCRAPERS_FINAL_IMPROVED/            <- Variant 1: hardened fetch layer (Scrapling HTTP + stealth browser)
SCRAPERS_FINAL_SCRAPLING_SPIDER/    <- Variant 2: full Scrapling Spider rewrite
```

Both write the **same per-category SQLite layout**, so `serve_ana.py` /
`update_status.py` and Ana's workflow are unchanged. Existing DBs were copied in,
so dedup/history continue.

---

## Target machine (192.168.1.20, ssh alias `t60hermes`)

| | |
|---|---|
| Host | T60 — Intel Core 2 Duo T7200 @ 2.00 GHz, 2 cores |
| RAM | 2.9 GB |
| OS | Debian 11 (bullseye) |
| Python | **3.9.2 only** → Scrapling needs 3.10+ |
| Chrome | Google Chrome **151.0.7922.108** already installed |
| sudo | no passwordless sudo |

Deployed to `~/Documents/PROJECTS/` on that host.

### What was installed (no root)

1. User-local **Python 3.11.17** (prebuilt standalone) at
   `~/.local/python311/python/bin/python3`.
2. Per-variant venvs:
   - `SCRAPERS_FINAL_IMPROVED/.venv`
   - `SCRAPERS_FINAL_SCRAPLING_SPIDER/.venv`
   Each has `scrapling[fetchers] 0.4.15` + `curl_cffi 0.16.3` + `patchright 1.63`.
3. **No browser download was needed** — Scrapling is pointed at the installed
   system Chrome via `real_chrome=True` (auto-detected; override with
   `SCRAPING_REAL_CHROME=0`).

`setup.sh` in each variant now also finds the user-local Python automatically.

---

## Bugs found and fixed through live testing on the T40

These were caught by actually running against the live sites (not by inspection):

1. **`.text` is not the HTML.** Scrapling's `Response` subclasses the parser
   `Selector`, so `resp.text` is the *element text* (empty at the document root);
   the page HTML is `.html_content`. Every scraper now uses `.html_content`
   (shared helper `html_of()`, and `soup_of()` in Variant 2). Without this, the
   scrapers silently parsed empty strings.
2. **IMOTI247 ad links are relative** (`/se-izdava-77048.html`). All versions
   required `"imoti247.com"` in the href and therefore collected **zero** ads —
   the likely cause of IMOTI247's silent death. Links are now normalised to
   absolute URLs and matched by the `-<digits>.html` pattern.
3. **Pazar3 platform number leaked into contacts.** The filter constant was
   `"+389 78 377 677"` but `normalize_phone()` emits `"+389 078 377 677"`, so it
   never matched (same for the agency phone list). Fixed in `_shared/utils.py`.
4. **IMOTI247 phones were left unnormalised** (`+38970274423`), so
   `serve_ana.py`'s cross-site phone dedup silently failed. Now normalised to
   the same `+389 0XX XXX XXX` format as the other sites.
5. **Pazar3 intermittently returns HTTP 503** (WAF interstitial) from the T40.
   Scrapling's own `retries` does not retry 5xx *status codes*, so added
   `robust_get()` / `robust_fetch()` with exponential backoff. Variant 2's spider
   additionally benefits from the framework's blocked-retry (observed absorbing
   a 503 mid-run).

---

## Verified on the T40 (real end-to-end runs, 1-page configs, fresh DBs)

| Site | Variant 1 (IMPROVED) | Variant 2 (SPIDER) |
|---|---|---|
| REKLAMA5 | 42 rows, 39 phones, 0 blocked | 42 rows, 39 phones, 0 blocked |
| PAZAR3 | 50 rows, 43 phones, 0 platform leaks | 51 rows, 44 phones, 0 platform leaks, 1 × 503 auto-retried |
| IMOTI247 | 12 rows, 12 phones, 12 images | 12 rows, 12 phones, 12 images |

- REKLAMA5 **403 is fixed on target hardware** (plain `requests` = 403;
  Scrapling/curl_cffi `impersonate="chrome"` = 200).
- IMOTI247 now runs on **system Chrome 151** through Scrapling's stealth session
  — no Selenium, no chromedriver pinning, no browser download.
- `healthcheck.py` passes: 29/29 categories, all configs + DBs valid, and all
  three homepages reachable.

---

## Which variant to use

| | **IMPROVED** | **SCRAPLING_SPIDER** |
|---|---|---|
| Shape | Same layout, fetch layer swapped | Spider classes + runner |
| Risk | Low | Medium |
| Throttling | Fixed polite sleeps + backoff | AutoThrottle + blocked-retry |
| Checkpoint/resume | No | Yes (`--crawldir`) |
| Recommendation | **Default for daily use on the T60** | Use once Variant 1 is trusted |

## Running them (on the T60)

```bash
# Variant 1
cd ~/Documents/PROJECTS/SCRAPERS_FINAL_IMPROVED
.venv/bin/python batch_scraper.py --dry-run
.venv/bin/python batch_scraper.py              # all 29, sequential
.venv/bin/python healthcheck.py --network

# Variant 2
cd ~/Documents/PROJECTS/SCRAPERS_FINAL_SCRAPLING_SPIDER
.venv/bin/python run_spiders.py --dry-run
.venv/bin/python run_spiders.py                # all 29, sequential

# Both: Ana's pipeline unchanged
.venv/bin/python serve_ana.py
.venv/bin/python update_status.py output/ana_batch_YYYY-MM-DD.csv
```

## Monitoring from the Lenovo

Each variant has its own `MONITOR/` folder (copied to the T60 as well). These
replace the original `SCRAPERS_FINAL/MONITOR/` scripts, which were hard-coded to
the old folder and to system `python3` (3.9) — they cannot run the Scrapling
variants. The adapted scripts are layout-independent:

- **Interpreter**: always the variant's `.venv/bin/python` (3.11 + Scrapling).
- **Entry point**: auto-detected — `run_spiders.py` if present, else `batch_scraper.py`.
- **tmux session**: `scraper_improved` (V1) and `scraper_scrapling_spider` (V2), so
  both can run side by side without clashing with the old `scraper` session.
- **Remote folder**: auto-detected on the T60 — tries
  `~/Documents/PROJECTS/<variant>` (sibling) then the local mirrored path, so it
  works whether the variants sit next to or inside `SCRAPERS_FINAL`.
- `output/` is created on demand before logging.

```bash
# on the Lenovo, from a variant's MONITOR/ folder
./start_scraper_remote.sh --dry-run     # show resolved remote path/session/entry
./start_scraper_remote.sh               # start + attach on the T60
./watch_scraper_remote.sh               # attach to the running T60 session
./kill_scraper_remote.sh                # stop the T60 session + processes

./launch_scraper_local.sh               # same, but on the Lenovo itself
./kill_scraper_local.sh

# limited smoke run
SCRAPER_ARGS="--site REKLAMA5 --limit 1" ./start_scraper_remote.sh
```

The `*_icon.sh` wrappers open the matching script in an `urxvt` window.

## Pazar3 and Cloudflare's 503

Pazar3 sometimes answers `HTTP 503` with `server: cloudflare` and
`retry-after: 30`. Measured directly (8 interleaved requests each):

| Fetch method | 503s |
|---|---|
| original `requests` + random UA | 6/8 |
| Scrapling `Fetcher` (curl_cffi, `stealthy_headers=True`) | 7/8 |
| Scrapling `Fetcher` (curl_cffi, `stealthy_headers=False`) | 8/8 |

So the 503 is **Cloudflare rate-limiting by IP, not a Scrapling regression** —
the original code hits it just as hard. The migration did not introduce it; it
only made it visible. The old scraper's handling was:

```python
if r.status_code != 200:
    print(f"  -> Status {r.status_code}, skipping...")
    continue          # page silently dropped, no retry, no counter
```

Every 503 page was silently discarded, so Pazar3 quietly returned fewer ads. The
Scrapling variants instead retry and report `BLOCKED` counts.

`robust_get`/`robust_fetch` now honour the server's `Retry-After` (falls back to
capped exponential backoff otherwise), so a throttled page waits the 30s
Cloudflare asked for instead of guessing. To reduce 503s further, lower Pazar3's
request rate — it is a rate limit, so fewer/faster requests is the only real fix.

## Pinned browser (optional)

By default the IMOTI247 stealth scrapers use the installed Chrome
(`real_chrome=True`), which a Chrome auto-update can change under you. To pin a
version, bundle a browser inside the variant folder:

```bash
./install_browser.sh --cft            # Chrome for Testing (latest stable)
./install_browser.sh --cft 151.0.7922.71   # a specific version
./install_browser.sh --copy-system    # copy the machine's installed Chrome
./install_browser.sh --status
./install_browser.sh --remove
```

Whatever it installs lands in `<variant>/browsers/` (git-ignored). `_shared/browser.py`
detects it automatically and the stealth sessions launch it via `executable_path`,
so the scraper no longer depends on the machine's Chrome. Override the search with
`SCRAPING_BROWSER_PATH=/path/to/chrome`. With nothing bundled, behaviour is exactly
as before (installed Chrome).

## Remaining limitations

- Only 1-page smoke configs were run end-to-end; a full 29-category batch has not
  been executed on the target. Recommend a `--site REKLAMA5 --limit 1` then a full
  overnight run.
- The MONITOR remote scripts attach a tmux session, so they need a real terminal;
  when run non-interactively (e.g. over a pipe) the session still starts but the
  attach step reports "not a terminal".
- IMOTI247 uses system Chrome via `real_chrome=True` unless a browser is bundled
  with `install_browser.sh`; run `./install_browser.sh --status` to see which one
  is in use.
- Pazar3's Cloudflare 503 is a per-IP rate limit and cannot be eliminated from
  the client side; `robust_get` now waits for the server's `Retry-After` and
  retries, which recovers most throttled pages.
