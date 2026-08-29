# IMOTI247 BASE SCRAPER
# Reads config.json from category folder, uses Chrome/Selenium, saves to SQLite
# Usage: python3 _imoti247_scraper.py                         (runs ALL Imoti247 categories)
#        python3 _imoti247_scraper.py I247_STANOVI_RENTA/     (runs ONE category)
#
# V2 — Added crash resilience:
#   - try/except around each ad (skip bad ads, don't crash scraper)
#   - Chrome restart if CDP connection dies
#   - Retry logic for page loads
#   - Committed to DB after each ad (no data loss on crash)

import sys
import os
import json
import re
import time
import random
import signal
import atexit
import threading
import subprocess as sp
import requests as http_requests
from datetime import datetime
from bs4 import BeautifulSoup

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, WebDriverException,
    InvalidSessionIdException
)

# Add parent dir to path for shared utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))
from utils import normalize_phone, init_db, ad_exists, insert_ad

MAX_CHROME_RESTARTS = 3
MAX_AD_RETRIES = 2
PAGE_LOAD_RETRIES = 2
AD_TIMEOUT = 90          # Skip ad if processing takes longer than 90s
RESTART_EVERY = 50       # Restart Chrome every N ads to prevent memory leak

def kill_all_chrome():
    """Nuclear cleanup — kill ALL chrome/chromedriver processes for this user"""
    for proc_name in ['google-chrome', 'chrome', 'chromedriver', 'undetected_chromedriver']:
        try:
            sp.run(['pkill', '-9', '-f', proc_name],
                   stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
        except Exception:
            pass

# Register cleanup on ANY exit — normal, crash, SIGTERM, SIGINT
atexit.register(kill_all_chrome)
signal.signal(signal.SIGTERM, lambda s, f: (kill_all_chrome(), sys.exit(1)))
signal.signal(signal.SIGINT, lambda s, f: (kill_all_chrome(), sys.exit(1)))


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
        self.total_skipped = 0
        self.total_errors = 0
        self.seen_ids = set()
        self.driver = None
        self.chrome_restarts = 0

    def create_driver(self):
        """Create a fresh Chrome driver instance. Kills old one first if exists."""
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            time.sleep(5)  # Let Chrome fully die before restart

        print(f"  [CHROME] Starting fresh Chrome instance (restart #{self.chrome_restarts})...")
        options = uc.ChromeOptions()
        options.add_argument("--start-minimized")
        options.add_argument("--window-position=0,0")
        options.add_argument("--window-size=100,100")
        options.add_argument("--no-sandbox")
        options.add_argument("--lang=mk-MK")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument("--disk-cache-size=10485760")
        options.add_argument("--media-cache-size=10485760")
        options.add_argument("--aggressive-cache-discard")

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

        driver.set_page_load_timeout(60)
        self.driver = driver
        print(f"  [CHROME] Ready.")
        return driver

    def restart_chrome(self, reason="unknown"):
        """Restart Chrome after a crash. Returns new driver or None if max restarts reached."""
        self.chrome_restarts += 1
        print(f"\n  [CHROME RESTART #{self.chrome_restarts}] Reason: {reason}")

        if self.chrome_restarts > MAX_CHROME_RESTARTS:
            print(f"  [CHROME] Max restarts ({MAX_CHROME_RESTARTS}) reached. Giving up.")
            return None

        # Wait before restart to let system recover
        wait_time = 10 * self.chrome_restarts  # 10s, 20s, 30s
        print(f"  [CHROME] Waiting {wait_time}s before restart...")
        time.sleep(wait_time)

        try:
            return self.create_driver()
        except Exception as e:
            print(f"  [CHROME] Restart failed: {e}")
            return None

    def safe_page_load(self, url, retries=PAGE_LOAD_RETRIES):
        """Load a URL with hard timeout + retry. Returns True if page loaded, False if all retries failed."""
        for attempt in range(retries + 1):
            if self.timed_get(url, timeout=60):
                return True
            print(f"  [PAGE LOAD] Attempt {attempt+1}/{retries+1} failed: timed out or error")
            if attempt < retries:
                new_driver = self.restart_chrome(str(f"page load attempt {attempt+1}"))
                if new_driver is None:
                    return False
                self.driver = new_driver
                if self.timed_get(url, timeout=60):
                    return True
                print(f"  [PAGE LOAD] Post-restart load also failed")
        print(f"  [PAGE LOAD] All {retries+1} attempts failed for {url}")
        return False

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
        """Extract images from ad page via requests (not Chrome)"""
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

    def timed_get(self, url, timeout=60):
        """Load URL with a hard timeout via thread. Returns True/False."""
        result = [False]
        def _load():
            try:
                self.driver.get(url)
                result[0] = True
            except Exception:
                pass
        t = threading.Thread(target=_load, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            print(f"  [HARD TIMEOUT] {url} did not load in {timeout}s")
            return False
        return result[0]

    def timed_script(self, script, timeout=15):
        """Execute JS with hard timeout. Returns result or None."""
        result = [None]
        def _run():
            try:
                result[0] = self.driver.execute_script(script)
            except Exception:
                pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            print(f"  [SCRIPT TIMEOUT] JS did not complete in {timeout}s")
            return None
        return result[0]

    def timed_find(self, by, value, timeout=15):
        """Find elements with hard timeout. Returns list or empty list."""
        result = [[]]
        def _find():
            try:
                result[0] = self.driver.find_elements(by, value)
            except Exception:
                pass
        t = threading.Thread(target=_find, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            print(f"  [FIND TIMEOUT] find_elements did not complete in {timeout}s")
            return []
        return result[0]

    def process_single_ad(self, ad_id, ad_url, wait):
        """Process one ad. Returns True if saved, False if skipped."""
        for attempt in range(MAX_AD_RETRIES + 1):
            try:
                if not self.safe_page_load(ad_url):
                    print(f"  SKIP -> {ad_id} | page load failed after all retries")
                    self.total_skipped += 1
                    return False

                self.sleep(2, 4)

                title = self.get_real_title(wait)
                phone = self.get_phone(ad_id)
                images = self.get_images(ad_url)

                insert_ad(self.cur, self.conn, ad_id, title, "N/A", "N/A",
                          phone, images, ad_url, self.site, self.category)

                self.seen_ids.add(ad_id)
                self.total_new += 1
                print(f"  SUCCESS -> {ad_id} | {phone[:30]} | {title[:50]}...")
                self.sleep(1, 3)
                return True

            except (InvalidSessionIdException, ConnectionRefusedError,
                    ConnectionResetError, OSError) as e:
                print(f"  [AD ERROR] {ad_id} attempt {attempt+1}: {type(e).__name__}: {e}")
                if attempt < MAX_AD_RETRIES:
                    new_driver = self.restart_chrome(str(e))
                    if new_driver is None:
                        self.total_skipped += 1
                        return False
                    self.driver = new_driver
                    wait = WebDriverWait(self.driver, 20)
                else:
                    self.total_skipped += 1
                    return False

            except Exception as e:
                print(f"  [AD ERROR] {ad_id} unexpected: {type(e).__name__}: {e}")
                self.total_skipped += 1
                return False

        self.total_skipped += 1
        return False

    def scrape(self):
        print(f"\n{'='*60}")
        print(f"IMOTI247 SCRAPER — {self.category}")
        print(f"URL: {self.base_url}")
        print(f"Pages: {self.pages}")
        print(f"DB: {self.db_path}")
        print(f"{'='*60}")

        # Clean up any leftover Chrome from previous crashed runs
        kill_all_chrome()
        time.sleep(2)

        # Create initial Chrome instance
        try:
            driver = self.create_driver()
        except Exception as e:
            print(f"  [FATAL] Cannot start Chrome: {e}")
            self.conn.close()
            return

        wait = WebDriverWait(driver, 20)

        try:
            page = 1
            empty_streak = 0

            while page <= self.pages:
                url = f"{self.base_url}&page={page}"
                print(f"\n[Page {page:02d}] -> {url}")

                # Load listing page with retry
                if not self.safe_page_load(url):
                    print(f"  SKIP page {page} — could not load after retries")
                    page += 1
                    self.sleep(10, 15)
                    continue

                self.sleep(3, 6)

                # Scroll to load all ads — direct Selenium call (no threaded timeout)
                # The CDP pipe deadlocks if we abandon threads, so we block the main thread.
                try:
                    for _ in range(12):
                        self.driver.execute_script(
                            f"window.scrollBy(0, {random.randint(800, 1400)});")
                        self.sleep(0.3, 0.8)
                except Exception as e:
                    print(f"  [SCROLL] Scroll failed: {type(e).__name__}: {e} — restarting Chrome")
                    new_driver = self.restart_chrome(f"scroll failed: {e}")
                    if new_driver:
                        self.driver = new_driver
                    page += 1
                    self.sleep(5, 10)
                    continue

                # Collect unique ad links — direct Selenium call
                try:
                    links = self.driver.find_elements(
                        By.XPATH, "//a[contains(@href,'.html') and contains(@href,'-')]")
                except Exception as e:
                    print(f"  [COLLECT] Find links failed: {type(e).__name__}: {e} — restarting Chrome")
                    new_driver = self.restart_chrome(f"find_elements failed: {e}")
                    if new_driver:
                        self.driver = new_driver
                    page += 1
                    self.sleep(5, 10)
                    continue

                if not links:
                    print(f"  [COLLECT] No links found on page {page}")
                    page += 1
                    self.sleep(5, 10)
                    continue

                try:
                    unique_links = set(
                        link.get_attribute("href") for link in links
                        if link.get_attribute("href") and "imoti247.com" in link.get_attribute("href")
                    )
                except Exception as e:
                    print(f"  [COLLECT] Failed to process links: {e}")
                    page += 1
                    self.sleep(5, 10)
                    continue

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

                ads_since_restart = 0
                for ad in new_ads:
                    # Refresh wait object in case Chrome was restarted
                    wait = WebDriverWait(self.driver, 20)
                    self.process_single_ad(ad["id"], ad["href"], wait)

                    # Preventive Chrome restart every N ads to avoid memory leak
                    ads_since_restart += 1
                    if ads_since_restart >= RESTART_EVERY and self.driver:
                        print(f"  [PREVENTIVE RESTART] {RESTART_EVERY} ads processed — restarting Chrome")
                        try:
                            self.driver.quit()
                        except Exception:
                            pass
                        self.driver = None
                        self.chrome_restarts += 1
                        time.sleep(5)
                        new_driver = self.create_driver()
                        if new_driver is None:
                            print("  [FATAL] Cannot restart Chrome")
                            return
                        wait = WebDriverWait(self.driver, 20)
                        ads_since_restart = 0

                page += 1
                self.sleep(3, 6)

        except KeyboardInterrupt:
            print("\n  INTERRUPTED BY USER")
        except Exception as e:
            print(f"\n  [FATAL] Unexpected error in scrape loop: {type(e).__name__}: {e}")
        finally:
            try:
                self.driver.quit()
            except Exception:
                pass

        print(f"\n{'='*60}")
        print(f"DONE — {self.category}")
        print(f"New ads: {self.total_new}")
        print(f"Skipped: {self.total_skipped}")
        print(f"Errors:  {self.total_errors}")
        print(f"Chrome restarts: {self.chrome_restarts}")
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
