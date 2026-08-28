# PAZAR3 BASE SCRAPER
# Reads config.json from category folder, scrapes that URL, saves to SQLite
# Usage: python3 _pazar3_scraper.py                        (runs ALL Pazar3 categories)
#        python3 _pazar3_scraper.py P3_STANOVI_RENTA/       (runs ONE category)

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
from utils import normalize_phone, is_agency, PAZAR3_PLATFORM_PHONE, init_db, ad_exists, insert_ad, UAS

def get_headers():
    return {"User-Agent": random.choice(UAS)}

def extract_price_size(text):
    """Extract price and size from ad text"""
    price = "N/A"
    price_m = re.search(r'(\d[\d\s\.\,]*)\s*€.*?/.*?месец', text, re.IGNORECASE)
    if not price_m:
        price_m = re.search(r'(\d[\d\s\.\,]*)\s*€', text)
    if price_m:
        num = price_m.group(1).replace(" ", "").replace(".", "").replace(",", "")
        price = f"{num} €"
    size_m = re.search(r'(\d+)\s*m²', text)
    size = f"{size_m.group(1)} m²" if size_m else "N/A"
    return price, size

def get_phone_pazar3(html):
    """Extract phone from Pazar3 ad HTML"""
    phones = set()
    patterns = [
        r'(?:\+?389|00389)?[\s\-/]*7\d{7,8}',
        r'0?7\d{7,8}',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html):
            normalized = normalize_phone(match)
            if normalized and normalized != PAZAR3_PLATFORM_PHONE:
                phones.add(normalized)
    # Also check between > < tags
    for bare in re.findall(r'>\s*(\d{7,9})\s*<', html):
        normalized = normalize_phone(bare)
        if normalized and normalized != PAZAR3_PLATFORM_PHONE:
            phones.add(normalized)
    if not phones:
        return ""
    return " | ".join(sorted(phones))

def get_images_pazar3(soup):
    """Extract images from Pazar3 ad page"""
    img_tags = soup.select("img[data-src*='pazar3']")
    images = [img.get('data-src') for img in img_tags if img.get('data-src')]
    return " | ".join(images) if images else ""

def scrape_category(config_path):
    """Main scraper function - reads config, scrapes, saves to DB"""
    # Load config
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    base_url = config["url"]
    site = config.get("site", "pazar3")
    category = config.get("category", "Unknown")
    pages = config.get("pages", 10)

    # Setup DB in the category folder's data/ directory
    category_dir = os.path.dirname(config_path)
    db_path = os.path.join(category_dir, "data", "pazar3.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn, cur = init_db(db_path)

    print(f"\n{'='*60}")
    print(f"PAZAR3 SCRAPER — {category}")
    print(f"URL: {base_url}")
    print(f"Pages: {pages}")
    print(f"DB: {db_path}")
    print(f"{'='*60}")

    total_new = 0
    total_phones = 0

    for page in range(1, pages + 1):
        url = f"{base_url}&page={page}"
        print(f"\n[Page {page}/{pages}] loading: {url}")

        try:
            r = requests.get(url, headers=get_headers(), timeout=20)
        except Exception as e:
            print(f"  -> Request failed: {e}")
            time.sleep(random.uniform(3, 6))
            continue

        if r.status_code != 200:
            print(f"  -> Status {r.status_code}, skipping...")
            time.sleep(random.uniform(3, 6))
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        anchors = soup.select("a[href^='/oglas/']")
        print(f"  -> found {len(anchors)} candidate ads")

        seen = set()
        page_new = 0

        for a in anchors:
            href = a.get("href")
            if not href or "/oglas/" not in href:
                continue
            ad_id = href.split("/")[-1].split("?")[0]
            if ad_id in seen or ad_id.isdigit() is False:
                continue
            seen.add(ad_id)

            # Skip if already in DB
            if ad_exists(cur, ad_id):
                continue

            full_link = "https://www.pazar3.mk" + href

            # Load ad page
            try:
                ad_r = requests.get(full_link, headers=get_headers(), timeout=20)
                time.sleep(random.uniform(0.8, 1.8))
            except Exception as e:
                print(f"  -> Failed to load ad {ad_id}: {e}")
                continue

            ad_html = ad_r.text
            ad_soup = BeautifulSoup(ad_html, "html.parser")

            # Title
            title_tag = ad_soup.find("h1")
            title = title_tag.get_text(strip=True) if title_tag else a.get_text(strip=True)
            title = re.sub(r'\s+', ' ', title).strip()
            if not title or len(title) < 5:
                continue

            # Agency filter
            phone_raw = get_phone_pazar3(ad_html)
            if is_agency(title, phone_raw if phone_raw else None):
                continue

            # Price and size
            price, size = extract_price_size(title)

            # Images
            images = get_images_pazar3(ad_soup)

            # Save to DB
            insert_ad(cur, conn, ad_id, title, price, size, phone_raw, images, full_link, site, category)
            page_new += 1
            total_new += 1
            if phone_raw:
                total_phones += 1

            print(f"  [+] {title[:55]:55} | {phone_raw[:20]}")
            time.sleep(random.uniform(1.5, 3.0))

        print(f"  -> {page_new} new ads on page {page}")
        time.sleep(random.uniform(3.0, 6.0))

    print(f"\n{'='*60}")
    print(f"DONE — {category}")
    print(f"New ads: {total_new}")
    print(f"With phone: {total_phones}")
    print(f"DB: {db_path}")
    print(f"{'='*60}")

    conn.close()
    return total_new, total_phones

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) < 2:
        # No argument — run ALL Pazar3 categories
        print(f"\n{'='*60}")
        print(f"PAZAR3 — RUNNING ALL CATEGORIES")
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
            ads, phones = scrape_category(cfg)
            total_ads += ads
            total_phones += phones

        print(f"\n{'='*60}")
        print(f"PAZAR3 ALL DONE")
        print(f"Total new ads: {total_ads}")
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

        scrape_category(config_path)
