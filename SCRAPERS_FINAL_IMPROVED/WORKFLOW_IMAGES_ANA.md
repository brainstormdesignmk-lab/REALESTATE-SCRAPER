# Scraper → Ana → Images → Lovable workflow (V1 IMPROVED)

This describes the hardened pipeline added on top of the original scrapers.
Nothing here changes V2 (`SCRAPERS_FINAL_SCRAPLING_SPIDER`); V2 remains the
working reference variant.

## 1. Phone engine — `_shared/phones.py`

The old extractors dropped whole classes of numbers. The shared engine fixes:

| Case | Example | Result |
|---|---|---|
| `074` mobile prefix (was missing from the whitelist) | `074205522` | `+389 074 205 522` |
| dashed / spaced formats | `071-751-588`, `072 240 604` | `+389 071 751 588`, `+389 072 240 604` |
| foreign numbers (incl. Viber) | `+49 176 205 49 606`, `+355697558898` | `+4917620549606`, `+355697558898` |
| `00` country-code form | `00381-62 758 588` | `+38162758588` |
| `<bdi>` dropdowns, `tel:` links, `main-contact`, body text | — | captured |

Macedonian mobiles use the canonical `+389 0XX XXX XXX` form (so cross-site
dedup keeps working); foreign numbers are preserved as compact E.164.
The Pazar3 platform number and known agency numbers are excluded.

Tests: `.venv/bin/python tests/test_phones.py` (18 cases from the bug report).

## 2. Per-site runs (no waiting for the whole batch)

`batch_scraper.py --site PAZAR3|REKLAMA5|IMOTI247` already ran one site.
The MONITOR launchers now expose it per site, each in its own tmux session:

```bash
SITE=REKLAMA5 ./MONITOR/launch_scraper_local.sh     # local machine
SITE=PAZAR3   ./MONITOR/start_scraper_remote.sh     # T60
```

Sessions: `scraper_improved_pazar3`, `scraper_improved_reklama5`,
`scraper_improved_imoti247`. Start/stop them independently.

Smoke-tested on the T60 after deploy: all three sites completed a 1-category
run (`RC=0`), and the fixed Reklama5 crop produced `cropped_top=36`
(`crop_mode=reklama5-fixed`) there as well.

## 3. Clean output

Scrapling's `INFO: Fetched (200) <GET ...>` lines are silenced by default
(`_shared/scrapling_fetch.quiet_scrapling`). Re-enable for debugging with
`SCRAPERS_LOG_LEVEL=INFO`.

Each scraped ad prints exactly one line:

```
  [+] <ad link> | <naslov> | <phone(s)> | <image urls>
```

## 4. Images — `_shared/media.py` + `scrape_images.py`

Scrape time stores only image URLs (space saving). The actual photos are
fetched when a deal closes:

```bash
# one ad
.venv/bin/python scrape_images.py --site reklama5 --ad-id 5774034 --property-number 1043

# deal-close trigger: every listing Ana marked ACCEPTED
.venv/bin/python scrape_images.py --accepted
```

Output: `$METROPOLIS_IMAGES_DIR/<key>/01.jpg`, `01.webp`, `manifest.json`
(defaults to `./output/images`). Reklama5 images are cropped to remove the
watermark, resized to max 1600 px, and written as JPEG (q82) + WebP.
`process_image()` strips EXIF orientation issues and keeps progressive JPEGs.

### Reklama5 watermark — fixed crop

Reklama5 stamps the **same** logo into the top-left corner of every uploaded
photo (it sits at y≈12..31 px and is a fixed pixel size, independent of the
image width). Because it never moves, the crop is now a **constant** —
`REKLAMA5_LOGO_CROP_TOP_PX = 36` in `_shared/media.py` — instead of the old
unreliable auto-detect (the heterogeneous uploads gave inconsistent estimates).
Every cropped tile records `"crop_mode": "reklama5-fixed"` and
`"cropped_top": 36` in `manifest.json`.

Verify visually (red line = the fixed crop):

```bash
.venv/bin/python scrape_images.py --preview
# -> output/images/_preview/reklama_crop_preview.jpg
```

Override the constant for one run with `--crop-top-px 40`; disable cropping
entirely with `--no-crop`.

## 5. Hosting (images on the T60, everything else on Supabase)

```
Lovable app (React/Vite)  -> Cloudflare Pages           [free]
Property JSON             -> Supabase Postgres          [free]
                             + nightly local copy on T60 (offline/backup)
Images                    -> T60 disk, served by a static server
                             exposed via Cloudflare Tunnel (cloudflared) [free]
                             -> https://img.<yourdomain>/<key>/01.jpg
```

The app reads image URLs from the T60 tunnel; JSON comes from Supabase. Because
the T60 tunnel is a stable hostname (no port forwarding, no DDNS), Cloudflare
caches the image responses at the edge, so a short T60 outage does not break
pages that were already served. Optional durability net: mirror the image
folder to Cloudflare R2 (10 GB free, zero egress) — a backup, not the source.

## 6. Deploying to the T60 and serving images

Deploy the variant code (never the local `.venv`/`browsers`/`output`/`data`):

```bash
cd SCRAPERS_FINAL_IMPROVED
rsync -az --exclude='.venv/' --exclude='browsers/' --exclude='__pycache__/' \
  --exclude='*.pyc' --exclude='output/' --exclude='*/data/' \
  ./ t60hermes:Documents/PROJECTS/SCRAPERS_FINAL_IMPROVED/
```

On the T60 (already installed: `cloudflared` in `~/.local/bin`, Pillow in the venv):

```bash
# 1. static image server (127.0.0.1:8088, session metropolis_images)
./MONITOR/serve_images_local.sh

# 2. expose it — zero-account URL for testing...
./MONITOR/expose_images_tunnel.sh --quick
# ...or a stable named tunnel (needs `cloudflared tunnel login` + a domain)
./MONITOR/expose_images_tunnel.sh --name metropolis-images
```

Images live under `$METROPOLIS_IMAGES_DIR` (default `~/metropolis-images` on the T60);
point `scrape_images.py` at the same root. Verified end-to-end: the public
`*.trycloudflare.com` URL served `/<key>/01.jpg` as `image/jpeg` with
`Cache-Control: public, max-age=31536000, immutable` so Cloudflare caches it.

## 7. Ana seam — `serve_ana.py` + `update_status.py`

`serve_ana.py` now writes two files in `output/`:

- `ana_batch_<date>.csv` — full review CSV, now with an `id` column.
- `ana_leads_<date>.csv` — exactly `id,title,phone,url`, the shape Ana's
  `outbound_final/lead-processor.js` `parseLeadLine()` expects.

`update_status.py` matches on `id` and uses the `source` column to scope the
update to the right site, so an id that exists on two sites is never updated in
the wrong one:

```bash
.venv/bin/python serve_ana.py
.venv/bin/python update_status.py output/<status_export>.csv   # columns: id,source,status
```

## Verification

```bash
.venv/bin/python tests/test_phones.py
.venv/bin/python tests/test_media.py
.venv/bin/python -m py_compile PAZAR3/_pazar3_scraper.py REKLAMA5/_reklama5_scraper.py \
    IMOTI247/_imoti247_scraper.py serve_ana.py update_status.py scrape_images.py
```
