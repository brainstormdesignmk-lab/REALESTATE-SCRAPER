# IMOTI247 BASE SCRAPER
# Reads config.json from category folder, uses Chrome/Selenium, saves to SQLite
# Usage: python3 _imoti247_scraper.py                         (runs ALL Imoti247 categories)
#        python3 _imoti247_scraper.py I247_STANOVI_RENTA/     (runs ONE category)

import sys
import os
import json
import re
import time
import random
import requests as http_requests
from datetime import datetime
from bs4 import BeautifulSoup

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# Add parent dir to path for shared utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
from utils import normalize_phone, init_db, ad_exists, insert_ad

class Imoti247Scraper:
    def __init__(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.base_url = self.config["url"]
        self.site = self.config.get("site", "imoti247")
        self.category = self.config.get("category", "Unknown")
        self.pages = self.config.get("pages", 50)

        # Setup DB
        category_dir = os.path.dirname(config_path)
        db_path = os.path.join(category_dir, "data", "imoti247.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn, self.cur = init_db(db_path)
        self.db_path = db_path

        self.ads = []
        self.total_new = 0
        self.seen_ids = set()

    def get_phone(self, ad_id):
        """Extract phone via AJAX endpoint"""
        try:
            phone_url = f"https://imoti247.com/description.php?get_phone=1&id={ad_id}"
            resp = http_requests.get(phone_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                cleaned = re.sub(r'[^\d+]', '', resp.text)
                mk_matches = re.findall(r'07[0-8]\d{6}', cleaned)
                if mk_matches:
                    phones = ["+389" + m[1:] for m in mk_matches[:2]]
                    return " | ".join(phones) if len(phones) > 1 else phones[0]
                intl_matches = re.findall(r'\+\d{10,15}', cleaned)
                if intl_matches:
                    return " | ".join(intl_matches[:2])
        except Exception as e:
            print(f"  AJAX phone error for {ad_id}: {e}")
        return ""

    def get_images(self, ad_url):
        """Extract images from ad page"""
        try:
            resp = http_requests.get(ad_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                img_tags = soup.select("img[src*='imoti247']")
                images = [img.get('src') for img in img_tags
                          if img.get('src') and 'logo' not in img.get('src', '').lower()]
                return " | ".join(images) if images else ""
        except Exception as e:
            print(f"  Image error: {e}")
        return ""

    def get_real_title(self, wait):
        """Get H1 title from current page"""
        try:
            h1 = wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
            return h1.text.strip() or "NO TITLE"
        except:
            return "NO TITLE"

    def sleep(self, a=0.7, b=1.8):
        time.sleep(random.uniform(a, b))

    def scrape(self):
        print(f"\n{'='*60}")
        print(f"IMOTI247 SCRAPER — {self.category}")
        print(f"URL: {self.base_url}")
        print(f"Pages: {self.pages}")
        print(f"DB: {self.db_path}")
        print(f"{'='*60}")

        # Chrome setup
        options = uc.ChromeOptions()
        options.add_argument("--start-minimized")
        options.add_argument("--window-position=0,0")
        options.add_argument("--window-size=100,100")
        options.add_argument("--no-sandbox")
        options.add_argument("--lang=mk-MK")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless=new")

        service = Service(ChromeDriverManager().install())
        driver = uc.Chrome(
            service=service,
            options=options,
            use_subprocess=True,
            version_main=151
        )

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['mk-MK','mk']});
                window.chrome = { runtime: {}, app: {}, csi: function(){}, loadTimes: function(){} };
            """
        })

        wait = WebDriverWait(driver, 20)

        try:
            page = 1
            empty_streak = 0

            while page <= self.pages:
                url = f"{self.base_url}&page={page}"
                print(f"\n[Page {page:02d}] -> {url}")
                driver.get(url)
                self.sleep(10, 15)

                # Scroll to load all ads
                for _ in range(12):
                    driver.execute_script(f"window.scrollBy(0, {random.randint(800, 1400)});")
                    self.sleep(0.6, 1.3)

                # Collect unique ad links
                links = driver.find_elements(By.XPATH, "//a[contains(@href,'.html') and contains(@href,'-')]")
                unique_links = set(
                    link.get_attribute("href") for link in links
                    if link.get_attribute("href") and "imoti247.com" in link.get_attribute("href")
                )

                new_ads = []
                for href in unique_links:
                    ad_id_match = re.search(r"-(\d+)\.html", href)
                    if ad_id_match:
                        ad_id = ad_id_match.group(1)
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
                    ad_id = ad["id"]
                    ad_url = ad["href"]
                    print(f"  -> Processing ID {ad_id}")
                    driver.get(ad_url)
                    self.sleep(8, 12)

                    title = self.get_real_title(wait)
                    phone = self.get_phone(ad_id)
                    images = self.get_images(ad_url)

                    # Save to DB
                    insert_ad(self.cur, self.conn, ad_id, title, "N/A", "N/A",
                              phone, images, ad_url, self.site, self.category)

                    self.seen_ids.add(ad_id)
                    self.total_new += 1
                    print(f"  SUCCESS -> {ad_id} | {phone[:25]} | {title[:50]}...")
                    self.sleep(6, 10)

                page += 1
                self.sleep(20, 40)

        finally:
            driver.quit()

        real_phones = self.total_new  # Would need to query DB, but approximate
        print(f"\n{'='*60}")
        print(f"DONE — {self.category}")
        print(f"New ads: {self.total_new}")
        print(f"DB: {self.db_path}")
        print(f"{'='*60}")

        self.conn.close()

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        # No argument — run ALL Imoti247 categories
        print(f"\n{'='*60}")
        print(f"IMOTI247 — RUNNING ALL CATEGORIES")
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
            scraper = Imoti247Scraper(cfg)
            scraper.scrape()
            # Count from DB
            import sqlite3
            db_path = os.path.join(os.path.dirname(cfg), "data", "imoti247.db")
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM listings")
                total_ads += cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM listings WHERE contact != ''")
                total_phones += cur.fetchone()[0]
                conn.close()

        print(f"\n{'='*60}")
        print(f"IMOTI247 ALL DONE")
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

        scraper = Imoti247Scraper(config_path)
        scraper.scrape()
