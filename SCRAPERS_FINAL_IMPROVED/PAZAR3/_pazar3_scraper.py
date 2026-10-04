# PAZAR3 BASE SCRAPER  (Scrapling edition)
# Reads config.json from a category folder, scrapes that URL, saves to SQLite.
#
# Usage:
#   python _pazar3_scraper.py                      # run ALL Pazar3 categories
#   python _pazar3_scraper.py P3_STANOVI_RENTA/    # run ONE category
#
# What changed vs the original (requests + random User-Agent):
#   - Fetching now goes through Scrapling's `Fetcher`/`FetcherSession`, which
#     impersonates a real Chrome TLS fingerprint and auto-retries. This both
#     hardens Pazar3 against the same 403 blocking that killed Reklama5 and
#     removes the User-Agent lottery.
#   - Blocked / non-200 responses are counted and reported loudly at the end,
#     so a silent site block can never look like "no new ads" again.
#   - Extraction logic (phone, agency filter, price/size, images) is unchanged
#     and still uses BeautifulSoup on the returned HTML.

from __future__ import annotations

import os
import re
import sys
import json
import time
from datetime import datetime

from bs4 import BeautifulSoup

# Add parent dir to path for shared utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_shared"))
from utils import (  # noqa: E402
    normalize_phone,
    is_agency,
    PAZAR3_PLATFORM_PHONE,
    init_db,
    ad_exists,
    insert_ad,
)
from scrapling_fetch import (  # noqa: E402
    http_session,
    robust_get,
    html_of,
    polite_sleep,
    ScraplingUnavailable,
)


def extract_price_size(text: str):
    """Extract price and size from ad text."""
    price = "N/A"
    price_m = re.search(r"(\d[\d\s\.\,]*)\s*€.*?/.*?месец", text, re.IGNORECASE)
    if not price_m:
        price_m = re.search(r"(\d[\d\s\.\,]*)\s*€", text)
    if price_m:
        num = price_m.group(1).replace(" ", "").replace(".", "").replace(",", "")
        price = f"{num} €"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = f"{size_m.group(1)} m²" if size_m else "N/A"
    return price, size


def get_phone_pazar3(html: str) -> str:
    """Extract phone from Pazar3 ad HTML."""
    phones = set()
    patterns = [
        r"(?:\+?389|00389)?[\s\-/]*7\d{7,8}",
        r"0?7\d{7,8}",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html):
            normalized = normalize_phone(match)
            if normalized and normalized != PAZAR3_PLATFORM_PHONE:
                phones.add(normalized)
    # Also check between > < tags
    for bare in re.findall(r">\s*(\d{7,9})\s*<", html):
        normalized = normalize_phone(bare)
        if normalized and normalized != PAZAR3_PLATFORM_PHONE:
            phones.add(normalized)
    if not phones:
        return ""
    return " | ".join(sorted(phones))


def get_images_pazar3(soup: BeautifulSoup) -> str:
    """Extract images from Pazar3 ad page."""
    img_tags = soup.select("img[data-src*='pazar3']")
    images = [img.get("data-src") for img in img_tags if img.get("data-src")]
    return " | ".join(images) if images else ""


def _status_of(resp) -> int:
    """Scrapling Response status (tolerates either attribute name)."""
    return getattr(resp, "status", None) or getattr(resp, "status_code", 0)


def scrape_category(config_path, session=None):
    """Read config, scrape, save to DB. Returns (new_ads, with_phone, blocked)."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    base_url = config["url"]
    site = config.get("site", "pazar3")
    category = config.get("category", "Unknown")
    pages = config.get("pages", 10)

    category_dir = os.path.dirname(config_path)
    db_path = os.path.join(category_dir, "data", "pazar3.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn, cur = init_db(db_path)

    print(f"\n{'=' * 60}")
    print(f"PAZAR3 SCRAPER (Scrapling) — {category}")
    print(f"URL: {base_url}")
    print(f"Pages: {pages}")
    print(f"DB: {db_path}")
    print(f"{'=' * 60}")

    total_new = 0
    total_phones = 0
    blocked = 0

    def _run(sess):
        nonlocal total_new, total_phones, blocked
        for page in range(1, pages + 1):
            url = f"{base_url}&page={page}"
            print(f"\n[Page {page}/{pages}] loading: {url}")

            try:
                r = robust_get(sess, url)
            except Exception as e:
                print(f"  -> Request failed: {e}")
                time.sleep(random_delay(3, 6))
                continue

            status = _status_of(r)
            if status != 200:
                if status in (403, 429, 503):
                    blocked += 1
                    print(f"  -> BLOCKED (HTTP {status}) — site is refusing us")
                else:
                    print(f"  -> Status {status}, skipping...")
                time.sleep(random_delay(3, 6))
                continue

            soup = BeautifulSoup(html_of(r), "html.parser")
            anchors = soup.select("a[href^='/oglas/']")
            print(f"  -> found {len(anchors)} candidate ads")

            seen = set()
            page_new = 0

            for a in anchors:
                href = a.get("href")
                if not href or "/oglas/" not in href:
                    continue
                ad_id = href.split("/")[-1].split("?")[0]
                if ad_id in seen or not ad_id.isdigit():
                    continue
                seen.add(ad_id)

                if ad_exists(cur, ad_id):
                    continue

                full_link = "https://www.pazar3.mk" + href

                try:
                    ad_r = robust_get(sess, full_link)
                    polite_sleep(0.8, 1.8)
                except Exception as e:
                    print(f"  -> Failed to load ad {ad_id}: {e}")
                    continue

                ad_status = _status_of(ad_r)
                if ad_status != 200:
                    if ad_status in (403, 429, 503):
                        blocked += 1
                    print(f"  -> ad {ad_id}: HTTP {ad_status}, skipped")
                    continue

                ad_html = html_of(ad_r)
                ad_soup = BeautifulSoup(ad_html, "html.parser")

                title_tag = ad_soup.find("h1")
                title = title_tag.get_text(strip=True) if title_tag else a.get_text(strip=True)
                title = re.sub(r"\s+", " ", title).strip()
                if not title or len(title) < 5:
                    continue

                phone_raw = get_phone_pazar3(ad_html)
                if is_agency(title, phone_raw if phone_raw else None):
                    continue

                price, size = extract_price_size(title)
                images = get_images_pazar3(ad_soup)

                insert_ad(cur, conn, ad_id, title, price, size, phone_raw,
                          images, full_link, site, category)
                page_new += 1
                total_new += 1
                if phone_raw:
                    total_phones += 1

                print(f"  [+] {title[:55]:55} | {phone_raw[:20]}")
                polite_sleep(1.5, 3.0)

            print(f"  -> {page_new} new ads on page {page}")
            time.sleep(random_delay(3.0, 6.0))

    if session is not None:
        _run(session)
    else:
        try:
            with http_session() as sess:
                _run(sess)
        except ScraplingUnavailable as e:
            print(f"\n[FATAL] {e}")
            conn.close()
            raise

    print(f"\n{'=' * 60}")
    print(f"DONE — {category}")
    print(f"New ads: {total_new}")
    print(f"With phone: {total_phones}")
    if blocked:
        print(f"BLOCKED responses: {blocked}  <-- investigate if this is non-zero")
    print(f"DB: {db_path}")
    print(f"{'=' * 60}")

    conn.close()
    return total_new, total_phones, blocked


def random_delay(low: float, high: float) -> float:
    import random
    return random.uniform(low, high)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        print(f"\n{'=' * 60}")
        print("PAZAR3 — RUNNING ALL CATEGORIES (Scrapling)")
        print(f"{'=' * 60}")

        categories = []
        for d in sorted(os.listdir(script_dir)):
            cfg = os.path.join(script_dir, d, "config.json")
            if os.path.exists(cfg):
                categories.append((d, cfg))

        print(f"Found {len(categories)} categories:\n")
        for name, _ in categories:
            print(f"  {name}")

        total_ads = total_phones = total_blocked = 0
        for i, (name, cfg) in enumerate(categories):
            print(f"\n[{i + 1}/{len(categories)}] === {name} ===")
            ads, phones, blocked = scrape_category(cfg)
            total_ads += ads
            total_phones += phones
            total_blocked += blocked

        print(f"\n{'=' * 60}")
        print("PAZAR3 ALL DONE")
        print(f"Total new ads: {total_ads}")
        print(f"Total with phone: {total_phones}")
        if total_blocked:
            print(f"Total BLOCKED responses: {total_blocked}  <-- investigate")
        print(f"Categories: {len(categories)}")
        print(f"{'=' * 60}")
    else:
        config_path = sys.argv[1]
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, "config.json")
        if not os.path.exists(config_path):
            print(f"Config not found: {config_path}")
            sys.exit(1)
        scrape_category(config_path)
