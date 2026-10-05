# scrape_images.py  (deal-close image trigger)
# Downloads the actual photos for one or more already-scraped ads and writes
# them, web-optimised, into a per-property folder on this machine.
#
# The scraper only stores image URLs (space saving). This is the second step,
# run when Ana closes a deal:
#
#   .venv/bin/python scrape_images.py --site reklama5 --ad-id 5774034 --property-number 1043
#   .venv/bin/python scrape_images.py --site pazar3 --ad-id 6184457
#   .venv/bin/python scrape_images.py --preview            # verify the fixed logo crop
#
# Output:  $METROPOLIS_IMAGES_DIR/<key>/01.jpg, 01.webp, manifest.json
#          (defaults to ./output/images when the env var is not set)

from __future__ import annotations

import os
import re
import sys
import glob
import json
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "_shared"))

from media import (  # noqa: E402
    process_property,
    write_preview,
    images_root,
    DEFAULT_MAX_WIDTH,
    DEFAULT_QUALITY,
    REKLAMA5_LOGO_CROP_TOP_PX,
)
from scrapling_fetch import http_session, html_of, status_of  # noqa: E402

SITES = ["pazar3", "reklama5", "imoti247"]
SITE_DIR = {"pazar3": "PAZAR3", "reklama5": "REKLAMA5", "imoti247": "IMOTI247"}


def find_db(site: str, ad_id: str):
    """Return (db_path, images, url) for an ad id across the site's DBs."""
    site_path = os.path.join(BASE_DIR, SITE_DIR[site])
    for db_file in sorted(glob.glob(os.path.join(site_path, "*", "data", "*.db"))):
        try:
            import sqlite3
            conn = sqlite3.connect(db_file)
            row = conn.execute(
                "SELECT images, url FROM listings WHERE id=?", (ad_id,)
            ).fetchone()
            conn.close()
        except Exception:
            continue
        if row:
            images = [u for u in (row[0] or "").split(" | ") if u.strip()]
            return db_file, images, row[1]
    return None, [], None


def refresh_images(site: str, ad_url: str, session) -> list:
    """Re-fetch the ad page and read its current image URLs.

    Used when the stored URLs may be stale (the ad page is the source of
    truth and is keyed by the stable numeric ad id, not the URL).
    """
    if not ad_url:
        return []
    resp = session.get(ad_url)
    if status_of(resp) != 200:
        return []
    html = html_of(resp)
    if site == "pazar3":
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        return [(i.get("data-src") or "").strip() for i in soup.select("img[data-src]")
                if "pazar3.mk" in (i.get("data-src") or "") and ".svg" not in (i.get("data-src") or "")]
    if site == "imoti247":
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        return [(i.get("src") or "").strip() for i in soup.select("img")
                if "imoti247.com/img/" in (i.get("src") or "") and "logo" not in (i.get("src") or "").lower()]
    # reklama5
    return [f"https://reklama5.mk/{m}" for m in
            dict.fromkeys(re.findall(r"photos/xbig/[a-f0-9-]+\.jpg", html))]


def find_accepted(site: str = None) -> list:
    """All listings marked ACCEPTED whose images have not been fetched yet.

    This is the deal-close trigger: run it from cron/watch after Ana flips a
    listing to ACCEPTED. A per-ad marker file records that it was processed.
    """
    import sqlite3
    found = []
    sites = [site] if site else SITES
    for s in sites:
        site_path = os.path.join(BASE_DIR, SITE_DIR[s])
        for db_file in sorted(glob.glob(os.path.join(site_path, "*", "data", "*.db"))):
            try:
                conn = sqlite3.connect(db_file)
                rows = conn.execute(
                    "SELECT id, images, url FROM listings "
                    "WHERE status='ACCEPTED' AND images IS NOT NULL AND images != ''"
                ).fetchall()
                conn.close()
            except Exception:
                continue
            for ad_id, images, url in rows:
                urls = [u for u in (images or "").split(" | ") if u.strip()]
                if urls:
                    found.append({"site": s, "id": ad_id, "images": urls, "url": url})
    return found


def collect_preview_urls(limit: int = 12) -> list:
    """Grab a spread of real Reklama5 image URLs for the crop preview."""
    urls = []
    for db_file in sorted(glob.glob(os.path.join(BASE_DIR, "REKLAMA5", "*", "data", "*.db"))):
        try:
            import sqlite3
            conn = sqlite3.connect(db_file)
            for (imgs,) in conn.execute("SELECT images FROM listings WHERE images != '' LIMIT 2"):
                for u in (imgs or "").split(" | "):
                    if u.strip() and u not in urls:
                        urls.append(u)
            conn.close()
        except Exception:
            continue
        if len(urls) >= limit:
            break
    return urls[:limit]


def main():
    parser = argparse.ArgumentParser(description="Download + prepare ad images for a property.")
    parser.add_argument("--site", choices=SITES, help="Site the ad belongs to.")
    parser.add_argument("--ad-id", action="append", default=[], help="Ad id (repeatable).")
    parser.add_argument("--property-number", default=None,
                        help="Folder key = property number once Ana closes the deal.")
    parser.add_argument("--out", default=None, help="Override the images root.")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch the ad page for current image URLs.")
    parser.add_argument("--crop-top-px", type=int, default=None,
                        help="Fixed top crop (px). Defaults to the Reklama5 watermark crop.")
    parser.add_argument("--no-crop", action="store_true", help="Never crop the top band.")
    parser.add_argument("--no-webp", action="store_true", help="JPEG only.")
    parser.add_argument("--max-width", type=int, default=DEFAULT_MAX_WIDTH)
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY)
    parser.add_argument("--preview", action="store_true",
                        help="Write a crop preview contact sheet for Reklama5 and exit.")
    parser.add_argument("--accepted", action="store_true",
                        help="Deal-close trigger: process every ACCEPTED listing.")
    args = parser.parse_args()

    if args.preview:
        crop_px = args.crop_top_px if args.crop_top_px is not None else REKLAMA5_LOGO_CROP_TOP_PX
        out = args.out or os.path.join(images_root(BASE_DIR), "_preview", "reklama_crop_preview.jpg")
        with http_session() as session:
            path = write_preview(collect_preview_urls(), out, session=session,
                                 crop_top_px=crop_px)
        print(f"Preview written: {path}")
        print(f"Red line = fixed crop at y={crop_px}px; confirm it sits below the "
              "Reklama5 watermark on every tile.")
        return

    if not args.accepted and (not args.site or not args.ad_id):
        parser.error("--site and at least one --ad-id are required (or use --preview/--accepted)")

    root = args.out or images_root(BASE_DIR)
    print(f"Images root: {root}")

    if args.accepted:
        targets = find_accepted(args.site)
        print(f"Accepted listings with images: {len(targets)}")
        if not targets:
            return
    else:
        targets = [{"site": args.site, "id": ad_id, "images": None, "url": None}
                   for ad_id in args.ad_id]

    with http_session() as session:
        for target in targets:
            ad_id = target["id"]
            site = target["site"]
            db_file, images, ad_url = find_db(site, ad_id)
            if target.get("images"):
                images = target["images"]
            if db_file is None:
                print(f"[{site}/{ad_id}] not found in any DB")
                continue
            if args.refresh:
                fresh = refresh_images(site, ad_url, session)
                if fresh:
                    images = fresh
            if not images:
                print(f"[{site}/{ad_id}] no image URLs stored"
                      + (" (try --refresh)" if not args.refresh else ""))
                continue

            crop_logo = (site == "reklama5") and not args.no_crop and args.crop_top_px is None
            manifest = process_property(
                site, ad_id, images,
                out_root=root,
                property_number=args.property_number,
                session=session,
                crop_logo=crop_logo,
                crop_top_px=(None if args.no_crop else args.crop_top_px),
                max_width=args.max_width,
                quality=args.quality,
                want_webp=not args.no_webp,
            )
            print(f"[{site}/{ad_id}] {manifest['count']} images -> {manifest['dir']}"
                  + (f"  ({len(manifest['errors'])} failed)" if manifest["errors"] else ""))
            for e in manifest["errors"]:
                print(f"    ! {e['url']}: {e['error']}")


if __name__ == "__main__":
    main()
