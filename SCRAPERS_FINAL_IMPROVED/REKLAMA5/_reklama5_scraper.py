# REKLAMA5 BASE SCRAPER  (Scrapling edition)
# Reads config.json from a category folder, scrapes that URL, saves to SQLite.
#
# Usage:
#   python _reklama5_scraper.py                      # run ALL Reklama5 categories
#   python _reklama5_scraper.py R5_STANOVI_RENTA/    # run ONE category
#
# Why Scrapling here:
#   Reklama5 returns HTTP 403 to plain `requests` (and even to curl with full
#   browser headers) because it fingerprints the TLS handshake (JA3/JA4).
#   Scrapling's `FetcherSession` uses curl_cffi and `impersonate="chrome"`,
#   which reproduces a genuine Chrome TLS fingerprint -> HTTP 200.
#
#   Verified against the live site:  plain curl  -> 403
#                                    curl_cffi impersonate=chrome -> 200
#
# Blocked responses are counted so a mid-run block is reported, not mistaken
# for "no new ads".

from __future__ import annotations

import os
import re
import sys
import json
import time
import sqlite3

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_shared"))
from utils import (  # noqa: E402
    normalize_phone,
    extract_phones,
    is_agency,
    AGENCY_PHONES,
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

BLOCKED_CODES = (403, 429, 503)


class Reklama5Scraper:
    def __init__(self, config_path, session=None):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.base_url = self.config["url"]
        self.site = self.config.get("site", "reklama5")
        self.category = self.config.get("category", "Unknown")
        self.pages = self.config.get("pages", 10)

        category_dir = os.path.dirname(config_path)
        db_path = os.path.join(category_dir, "data", "reklama5.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn, self.cur = init_db(db_path)
        self.db_path = db_path

        self.session = session
        self.blocked = 0

    @staticmethod
    def _status_of(resp):
        return getattr(resp, "status", None) or getattr(resp, "status_code", 0)

    def get_phone(self, soup, html=None):
        """Extract phone from an ad page using the shared engine.

        Falls back to the site's "Show phone" link when the number is hidden.
        """
        try:
            phones = extract_phones(
                html=html, soup=soup, site="reklama5", exclude=AGENCY_PHONES
            )
            if phones:
                return " | ".join(phones)

            # If no phone, try the "show phone" direct link
            show_link = soup.find("a", href=re.compile(r"/ShowPhone"))
            if show_link:
                show_url = "https://reklama5.mk" + show_link["href"]
                time.sleep(2)
                show_resp = robust_get(self.session, show_url)
                if self._status_of(show_resp) == 200:
                    match = re.search(r"07\d{7}", html_of(show_resp))
                    if match:
                        normalized = normalize_phone(match.group(0))
                        if normalized:
                            return normalized

            return ""
        except Exception as e:
            print(f"  Phone error: {e}")
            return ""

    def get_images(self, soup):
        """Extract images from ad page using xbig pattern."""
        img_urls = re.findall(r"photos/xbig/[a-f0-9-]+\.jpg", str(soup))
        img_urls = list(dict.fromkeys(img_urls))
        full_urls = [f"https://reklama5.mk/{img}" for img in img_urls]
        return " | ".join(full_urls) if full_urls else ""

    def _scrape(self):
        print(f"\n{'=' * 60}")
        print(f"REKLAMA5 SCRAPER (Scrapling) — {self.category}")
        print(f"URL: {self.base_url}")
        print(f"Pages: {self.pages}")
        print(f"DB: {self.db_path}")
        print(f"{'=' * 60}")

        all_ads = []

        # Phase 1: collect ad links from listing pages
        for page_num in range(1, self.pages + 1):
            list_url = re.sub(r"page=\d+", f"page={page_num}", self.base_url)
            if "page=" not in list_url:
                list_url = f"{list_url}&page={page_num}"

            print(f"\n[Page {page_num}/{self.pages}] -> {list_url}")

            try:
                resp = robust_get(self.session, list_url)
            except Exception as e:
                print(f"  -> Request failed: {e}")
                time.sleep(3)
                continue

            status = self._status_of(resp)
            if status != 200:
                if status in BLOCKED_CODES:
                    self.blocked += 1
                    print(f"  -> BLOCKED (HTTP {status}) — fingerprint rejected")
                else:
                    print(f"  -> Status {status}, skipping...")
                time.sleep(3)
                continue

            soup = BeautifulSoup(html_of(resp), "lxml")
            polite_sleep(1.5, 3.0)

            ad_links = soup.find_all("a", href=re.compile(r"/AdDetails\?ad="))
            page_count = 0

            for link in ad_links:
                title = link.get_text(strip=True)
                if len(title) < 8:
                    continue
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://reklama5.mk" + href
                ad_id_match = re.search(r"ad=(\d+)", href)
                if not ad_id_match:
                    continue
                ad_id = ad_id_match.group(1)

                if ad_exists(self.cur, ad_id):
                    continue
                if is_agency(title):
                    continue

                all_ads.append({"ad_id": ad_id, "title": title, "url": href})
                page_count += 1

            print(f"  -> {page_count} new ads")

        print(f"\nTotal new ads to process: {len(all_ads)}")

        # Phase 2: extract phones + images from each ad
        total_phones = 0
        for i, ad in enumerate(all_ads):
            print(f"  [{i + 1}/{len(all_ads)}] {ad['ad_id']} | {ad['title'][:50]}")

            try:
                resp = robust_get(self.session, ad["url"])
            except Exception as e:
                print(f"    -> Failed: {e}")
                time.sleep(2)
                continue

            status = self._status_of(resp)
            if status != 200:
                if status in BLOCKED_CODES:
                    self.blocked += 1
                print(f"    -> HTTP {status}, skipped")
                continue

            ad_html = html_of(resp)
            soup = BeautifulSoup(ad_html, "lxml")
            phone = self.get_phone(soup, html=ad_html)
            images = self.get_images(soup)

            if phone and is_agency(ad["title"], phone):
                phone = ""

            insert_ad(self.cur, self.conn, ad["ad_id"], ad["title"], "N/A", "N/A",
                      phone, images, ad["url"], self.site, self.category)

            if phone:
                total_phones += 1

            print(f"  [+] {ad['url']} | {ad['title']} | {phone or '-'} | {images or '-'}")

            polite_sleep(2.0, 4.0)

        print(f"\n{'=' * 60}")
        print(f"DONE — {self.category}")
        print(f"New ads: {len(all_ads)}")
        print(f"With phone: {total_phones}")
        if self.blocked:
            print(f"BLOCKED responses: {self.blocked}  <-- investigate if non-zero")
        print(f"DB: {self.db_path}")
        print(f"{'=' * 60}")

        self.conn.close()
        return len(all_ads), total_phones, self.blocked

    def scrape(self):
        if self.session is not None:
            return self._scrape()
        try:
            with http_session() as sess:
                self.session = sess
                return self._scrape()
        except ScraplingUnavailable as e:
            print(f"\n[FATAL] {e}")
            self.conn.close()
            raise


def _count_db(cfg):
    db_path = os.path.join(os.path.dirname(cfg), "data", "reklama5.db")
    if not os.path.exists(db_path):
        return 0, 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM listings")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM listings WHERE contact != ''")
    phones = cur.fetchone()[0]
    conn.close()
    return total, phones


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        print(f"\n{'=' * 60}")
        print("REKLAMA5 — RUNNING ALL CATEGORIES (Scrapling)")
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
            scraper = Reklama5Scraper(cfg)
            _, _, blocked = scraper.scrape()
            total_blocked += blocked
            ads, phones = _count_db(cfg)
            total_ads += ads
            total_phones += phones

        print(f"\n{'=' * 60}")
        print("REKLAMA5 ALL DONE")
        print(f"Total ads in DBs: {total_ads}")
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
        Reklama5Scraper(config_path).scrape()
