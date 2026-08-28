# REKLAMA5 BASE SCRAPER
# Reads config.json from category folder, scrapes that URL, saves to SQLite
# Usage: python3 _reklama5_scraper.py                        (runs ALL Reklama5 categories)
#        python3 _reklama5_scraper.py R5_STANOVI_RENTA/      (runs ONE category)

import sys
import os
import json
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from datetime import datetime

# Add parent dir to path for shared utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
from utils import normalize_phone, is_agency, init_db, ad_exists, insert_ad

class Reklama5Scraper:
    def __init__(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.base_url = self.config["url"]
        self.site = self.config.get("site", "reklama5")
        self.category = self.config.get("category", "Unknown")
        self.pages = self.config.get("pages", 10)

        # Setup DB
        category_dir = os.path.dirname(config_path)
        db_path = os.path.join(category_dir, "data", "reklama5.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn, self.cur = init_db(db_path)
        self.db_path = db_path

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux i686; rv:109.0) Gecko/20100101 Firefox/115.0"
        })

    def get_phone(self, soup):
        """Extract phone from ad page soup"""
        try:
            page_text = soup.get_text(separator=" ")

            phones = re.findall(r'07[0-9\s\-]{8,14}07[0-9]{7}', page_text)
            phones += re.findall(r'07\d{7}', page_text)
            phones += re.findall(r'\+389\s?7\d\s?\d{3}\s?\d{3}', page_text)
            phones += re.findall(r'07\d\s?\d{3}\s?\d{3}', page_text)

            found_phones = set()
            for p in phones:
                normalized = normalize_phone(p)
                if normalized:
                    found_phones.add(normalized)

            # If no phone, try the "show phone" direct link
            if not found_phones:
                show_link = soup.find("a", href=re.compile(r"/ShowPhone"))
                if show_link:
                    show_url = "https://reklama5.mk" + show_link["href"]
                    time.sleep(2)
                    show_resp = self.session.get(show_url, timeout=30)
                    if show_resp.status_code == 200:
                        match = re.search(r'07\d{7}', show_resp.text)
                        if match:
                            normalized = normalize_phone(match.group(0))
                            if normalized:
                                found_phones.add(normalized)

            return " | ".join(sorted(found_phones)) if found_phones else ""
        except Exception as e:
            print(f"  Phone error: {e}")
            return ""

    def get_images(self, soup):
        """Extract images from ad page using xbig pattern"""
        img_urls = re.findall(r'photos/xbig/[a-f0-9-]+\.jpg', str(soup))
        img_urls = list(dict.fromkeys(img_urls))
        full_urls = [f"https://reklama5.mk/{img}" for img in img_urls]
        return " | ".join(full_urls) if full_urls else ""

    def scrape(self):
        print(f"\n{'='*60}")
        print(f"REKLAMA5 SCRAPER — {self.category}")
        print(f"URL: {self.base_url}")
        print(f"Pages: {self.pages}")
        print(f"DB: {self.db_path}")
        print(f"{'='*60}")

        all_ads = []

        # Phase 1: Collect ad links from listing pages
        for page_num in range(1, self.pages + 1):
            # Replace page number in URL
            list_url = re.sub(r'page=\d+', f'page={page_num}', self.base_url)
            if 'page=' not in list_url:
                list_url = f"{list_url}&page={page_num}"

            print(f"\n[Page {page_num}/{self.pages}] -> {list_url}")

            try:
                resp = self.session.get(list_url, timeout=30)
                resp.raise_for_status()
            except Exception as e:
                print(f"  -> Request failed: {e}")
                time.sleep(random.uniform(3, 6))
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            time.sleep(random.uniform(3, 6))

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

                # Skip if already in DB
                if ad_exists(self.cur, ad_id):
                    continue

                # Agency filter
                if is_agency(title):
                    continue

                all_ads.append({
                    "ad_id": ad_id,
                    "title": title,
                    "url": href,
                })
                page_count += 1

            print(f"  -> {page_count} new ads")

        print(f"\nTotal new ads to process: {len(all_ads)}")

        # Phase 2: Extract phones and images from each ad
        total_phones = 0
        for i, ad in enumerate(all_ads):
            print(f"  [{i+1}/{len(all_ads)}] {ad['ad_id']} | {ad['title'][:50]}")

            try:
                resp = self.session.get(ad["url"], timeout=30)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception as e:
                print(f"    -> Failed: {e}")
                time.sleep(random.uniform(2, 4))
                continue

            phone = self.get_phone(soup)
            images = self.get_images(soup)

            # Filter agency phones
            if phone and is_agency(ad["title"], phone):
                phone = ""

            # Save to DB
            insert_ad(self.cur, self.conn, ad["ad_id"], ad["title"], "N/A", "N/A",
                      phone, images, ad["url"], self.site, self.category)

            if phone:
                total_phones += 1
                print(f"    -> {phone}")
            else:
                print(f"    -> no phone")

            time.sleep(random.uniform(4, 7))

        print(f"\n{'='*60}")
        print(f"DONE — {self.category}")
        print(f"New ads: {len(all_ads)}")
        print(f"With phone: {total_phones}")
        print(f"DB: {self.db_path}")
        print(f"{'='*60}")

        self.conn.close()

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        # No argument — run ALL Reklama5 categories
        print(f"\n{'='*60}")
        print(f"REKLAMA5 — RUNNING ALL CATEGORIES")
        print(f"{'='*60}")

        categories = []
        for d in sorted(os.listdir(script_dir)):
            cfg = os.path.join(script_dir, d, "config.json")
            if os.path.exists(cfg):
                categories.append((d, cfg))

        print(f"Found {len(categories)} categories:\n")
        for name, _ in categories:
            print(f"  {name}")

        total_ads = 0
        total_phones = 0
        for i, (name, cfg) in enumerate(categories):
            print(f"\n[{i+1}/{len(categories)}] === {name} ===")
            scraper = Reklama5Scraper(cfg)
            scraper.scrape()
            # Count from DB
            import sqlite3
            db_path = os.path.join(os.path.dirname(cfg), "data", "reklama5.db")
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM listings")
                total_ads += cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM listings WHERE contact != ''")
                total_phones += cur.fetchone()[0]
                conn.close()

        print(f"\n{'='*60}")
        print(f"REKLAMA5 ALL DONE")
        print(f"Total ads in DBs: {total_ads}")
        print(f"Total with phone: {total_phones}")
        print(f"Categories: {len(categories)}")
        print(f"{'='*60}")
    else:
        # Argument given — run ONE category
        config_path = sys.argv[1]
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, "config.json")

        if not os.path.exists(config_path):
            print(f"Config not found: {config_path}")
            sys.exit(1)

        scraper = Reklama5Scraper(config_path)
        scraper.scrape()
