# IMOTI247 BASE SCRAPER  (Scrapling edition)
# Reads config.json from a category folder, uses a Scrapling stealth browser
# session, saves to SQLite.
#
# Usage:
#   python _imoti247_scraper.py                        # run ALL Imoti247 categories
#   python _imoti247_scraper.py I247_STANOVI_RENTA/    # run ONE category
#
# What changed vs the original (Selenium + undetected-chromedriver):
#   - ONE reusable `StealthySession` (patchright/Chromium) is opened per
#     category and reused for every page/ad, instead of launching Chrome per
#     request and restarting it every N ads. On a 3 GB machine this is the
#     difference between running and swapping to death.
#   - No chromedriver version pinning, no `webdriver_manager`, no manual
#     process-tree killing: the browser lifecycle is owned by Scrapling.
#   - The phone AJAX endpoint and the image scrape go through the same
#     TLS-impersonating HTTP client (`http_get`), not a second requests stack.
#   - Consecutive fetch failures are counted; if the browser dies the run
#     aborts loudly instead of silently producing zero new ads.
#
# Requires the browser binaries once per machine:  `scrapling install`

from __future__ import annotations

import os
import re
import sys
import json
import time
import random
from datetime import datetime

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_shared"))
from utils import normalize_phone, init_db, ad_exists, insert_ad  # noqa: E402
from scrapling_fetch import (  # noqa: E402
    stealth_session,
    http_get,
    robust_fetch,
    html_of,
    polite_sleep,
    ScraplingUnavailable,
)

MAX_CONSECUTIVE_FAILURES = 8   # abort the category if the browser keeps failing
AD_ID_RE = re.compile(r"-(\d+)\.html")


def _scroll_listing(page):
    """Scrapling `page_action`: lazy-load the listing page by scrolling.

    Runs after every navigation. Ad pages (URLs ending in `.html`) need no
    scrolling, so we skip them to avoid wasting time/RAM. The whole body is
    wrapped because a failed scroll must never break the fetch.
    """
    try:
        if page.url and ".html" in page.url:
            return
        for _ in range(12):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(300)
    except Exception:
        pass


class Imoti247Scraper:
    def __init__(self, config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.base_url = self.config["url"]
        self.site = self.config.get("site", "imoti247")
        self.category = self.config.get("category", "Unknown")
        self.pages = self.config.get("pages", 50)

        category_dir = os.path.dirname(config_path)
        db_path = os.path.join(category_dir, "data", "imoti247.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn, self.cur = init_db(db_path)
        self.db_path = db_path

        self.seen_ids = set()
        self.total_new = 0
        self.total_skipped = 0
        self.total_errors = 0
        self.consecutive_failures = 0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _status_of(resp):
        return getattr(resp, "status", None) or getattr(resp, "status_code", 0)

    def _fetch(self, session, url):
        """Fetch a URL, returning the Scrapling Response or None on failure."""
        try:
            resp = robust_fetch(session, url)
            if self._status_of(resp) in (403, 429, 503):
                print(f"  [BLOCKED] HTTP {self._status_of(resp)} for {url}")
                self.consecutive_failures += 1
                return None
            self.consecutive_failures = 0
            return resp
        except Exception as e:
            self.consecutive_failures += 1
            print(f"  [FETCH ERROR] {type(e).__name__}: {e}")
            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise RuntimeError(
                    f"{MAX_CONSECUTIVE_FAILURES} consecutive browser failures — "
                    "browser is likely dead. Aborting this category."
                )
            return None

    def get_phone(self, ad_id):
        """Extract phone via the site's AJAX endpoint (TLS-impersonated GET)."""
        try:
            phone_url = f"https://imoti247.com/description.php?get_phone=1&id={ad_id}"
            resp = http_get(phone_url)
            if self._status_of(resp) == 200:
                cleaned = re.sub(r"[^\d+]", "", html_of(resp))
                mk_matches = re.findall(r"07[0-8]\d{6}", cleaned)
                if mk_matches:
                    # Normalise to the SAME format as Pazar3/Reklama5 so that
                    # serve_ana.py's cross-site phone dedup works.
                    phones = []
                    for m in mk_matches[:2]:
                        n = normalize_phone(m)
                        if n and n not in phones:
                            phones.append(n)
                    if phones:
                        return " | ".join(phones) if len(phones) > 1 else phones[0]
                intl_matches = re.findall(r"\+\d{10,15}", cleaned)
                if intl_matches:
                    return " | ".join(intl_matches[:2])
        except Exception as e:
            print(f"  AJAX phone error for {ad_id}: {e}")
        return ""

    def get_images(self, ad_url):
        """Extract image URLs from the ad page HTML."""
        try:
            resp = http_get(ad_url)
            if self._status_of(resp) == 200:
                soup = BeautifulSoup(html_of(resp), "lxml")
                img_tags = soup.select("img[src*='imoti247']")
                images = [img.get("src") for img in img_tags
                          if img.get("src") and "logo" not in img.get("src", "").lower()]
                return " | ".join(images) if images else ""
        except Exception as e:
            print(f"  Image error: {e}")
        return ""

    def process_ad(self, session, ad_id, ad_url):
        """Load one ad page and save it. Returns True if saved."""
        resp = self._fetch(session, ad_url)
        if resp is None:
            self.total_skipped += 1
            return False

        title_tag = BeautifulSoup(html_of(resp), "lxml").find("h1")
        title = title_tag.get_text(strip=True) if title_tag else "NO TITLE"

        phone = self.get_phone(ad_id)
        images = self.get_images(ad_url)

        insert_ad(self.cur, self.conn, ad_id, title, "N/A", "N/A",
                  phone, images, ad_url, self.site, self.category)

        self.seen_ids.add(ad_id)
        self.total_new += 1
        print(f"  SUCCESS -> {ad_id} | {phone[:30]} | {title[:50]}...")
        polite_sleep(1, 3)
        return True

    # -------------------------------------------------------------------- main
    def scrape(self):
        print(f"\n{'=' * 60}")
        print(f"IMOTI247 SCRAPER (Scrapling stealth) — {self.category}")
        print(f"URL: {self.base_url}")
        print(f"Pages: {self.pages}")
        print(f"DB: {self.db_path}")
        print(f"{'=' * 60}")

        try:
            # disable_resources=False keeps XHR/images available; one session
            # for the whole category keeps RAM bounded on a small machine.
            with stealth_session(
                headless=True,
                network_idle=True,
                timeout=60000,
                disable_resources=False,
                page_action=_scroll_listing,
            ) as session:
                self._crawl(session)
        except ScraplingUnavailable as e:
            print(f"\n[FATAL] {e}")
        except RuntimeError as e:
            print(f"\n[FATAL] {e}")

        print(f"\n{'=' * 60}")
        print(f"DONE — {self.category}")
        print(f"New ads: {self.total_new}")
        print(f"Skipped: {self.total_skipped}")
        print(f"DB: {self.db_path}")
        print(f"{'=' * 60}")
        self.conn.close()
        return self.total_new

    def _crawl(self, session):
        page = 1
        empty_streak = 0

        while page <= self.pages:
            url = f"{self.base_url}&page={page}"
            print(f"\n[Page {page:02d}] -> {url}")

            resp = self._fetch(session, url)
            if resp is None:
                print(f"  SKIP page {page} — could not load")
                page += 1
                time.sleep(5)
                continue

            soup = BeautifulSoup(html_of(resp), "lxml")
            links = soup.select("a[href*='.html']")

            # Ad links are RELATIVE on the listing page (e.g. "/se-izdava-77048.html"),
            # so we must NOT require "imoti247.com" in the href. Normalise to an
            # absolute URL and accept anything matching "-<digits>.html".
            hrefs = set()
            for a in links:
                href = a.get("href")
                if not href or ".html" not in href:
                    continue
                full = href if href.startswith("http") else (
                    "https://imoti247.com" + (href if href.startswith("/") else "/" + href))
                if AD_ID_RE.search(full):
                    hrefs.add(full)

            new_ads = []
            for href in hrefs:
                m = AD_ID_RE.search(href)
                if not m:
                    continue
                ad_id = m.group(1)
                if ad_id not in self.seen_ids and not ad_exists(self.cur, ad_id):
                    new_ads.append({"id": ad_id, "href": href})

            print(f"  -> {len(new_ads)} new ads on page {page}")

            if not new_ads:
                empty_streak += 1
                if empty_streak >= 5:
                    print("  5 empty pages in a row -> stopping")
                    break
            else:
                empty_streak = 0

            for ad in new_ads:
                try:
                    self.process_ad(session, ad["id"], ad["href"])
                except Exception as e:
                    self.total_errors += 1
                    print(f"  [AD ERROR] {ad['id']}: {type(e).__name__}: {e}")

            page += 1
            polite_sleep(3, 6)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        print(f"\n{'=' * 60}")
        print("IMOTI247 — RUNNING ALL CATEGORIES (Scrapling)")
        print(f"{'=' * 60}")

        categories = []
        for d in sorted(os.listdir(script_dir)):
            cfg = os.path.join(script_dir, d, "config.json")
            if os.path.exists(cfg):
                categories.append((d, cfg))

        print(f"Found {len(categories)} categories:\n")
        for name, _ in categories:
            print(f"  {name}")

        total_ads = 0
        for i, (name, cfg) in enumerate(categories):
            print(f"\n[{i + 1}/{len(categories)}] === {name} ===")
            total_ads += Imoti247Scraper(cfg).scrape()

        print(f"\n{'=' * 60}")
        print("IMOTI247 ALL DONE")
        print(f"Total new ads: {total_ads}")
        print(f"Categories: {len(categories)}")
        print(f"{'=' * 60}")
    else:
        config_path = sys.argv[1]
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, "config.json")
        if not os.path.exists(config_path):
            print(f"Config not found: {config_path}")
            sys.exit(1)
        Imoti247Scraper(config_path).scrape()
