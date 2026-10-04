# _shared/utils.py
# Shared utilities for all scrapers: phone normalization, DB setup, constants

import re
import sqlite3
from datetime import datetime

# -------------------------------
# PHONE NORMALIZATION
# -------------------------------
def normalize_phone(p):
    """Normalize any MK phone to +389 7X XXX XXX format"""
    cleaned = re.sub(r'[^\d+]', '', p)
    if not cleaned:
        return None
    if cleaned.startswith('+389'):
        digits = cleaned[4:]
    elif cleaned.startswith('00389'):
        digits = cleaned[5:]
    elif cleaned.startswith('389') and len(cleaned) == 11:
        digits = cleaned[3:]
    else:
        digits = cleaned
        if digits.startswith('7') and len(digits) == 8:
            digits = '0' + digits
    if not digits.startswith(('070', '071', '072', '073', '075', '076', '077', '078')):
        return None
    if len(digits) < 8 or len(digits) > 9:
        return None
    if len(digits) == 8:
        digits = '0' + digits
    digits = digits[:9].ljust(9, '0')
    return f"+389 {digits[:3]} {digits[3:6]} {digits[6:9]}"

# -------------------------------
# AGENCY FILTERS
# -------------------------------
AGENCY_KEYWORDS = [
    "агенц", "agency", "real estate", "lux", "urban", "novel",
    "имоб", "лайф", "недви", "имоти", "савиќ", "savik", "secter", "home center"
]

# NOTE: these must match the exact output format of normalize_phone(),
# which emits a leading 0 after the country code (e.g. "+389 078 377 677").
# The original constants used "+389 78 ..."/"+389 70 ..." and therefore never
# matched, letting platform/agency numbers leak into contacts.
AGENCY_PHONES = [
    "+389 070 318 400",   # САВИЌ
    "+389 078 377 677",   # Pazar3 platform number
]

PAZAR3_PLATFORM_PHONE = "+389 078 377 677"

def is_agency(title, phone=None):
    """Check if an ad is from an agency"""
    if any(k in title.lower() for k in AGENCY_KEYWORDS):
        return True
    if phone and phone in AGENCY_PHONES:
        return True
    return False

# -------------------------------
# DATABASE SETUP
# -------------------------------
def init_db(db_path):
    """Initialize SQLite DB with listings table"""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            size TEXT,
            contact TEXT,
            images TEXT,
            url TEXT,
            status TEXT DEFAULT '',
            first_seen TEXT,
            last_served TEXT,
            times_served INTEGER DEFAULT 0,
            site TEXT,
            category TEXT
        )
    """)
    conn.commit()
    return conn, cur

def ad_exists(cur, ad_id):
    """Check if ad already exists in DB"""
    return cur.execute("SELECT 1 FROM listings WHERE id=?", (ad_id,)).fetchone() is not None

def insert_ad(cur, conn, ad_id, title, price, size, phone, images, url, site, category):
    """Insert a new ad into DB"""
    now = datetime.now().strftime("%d.%m %H:%M")
    cur.execute("""
        INSERT OR IGNORE INTO listings (id, title, price, size, contact, images, url, status, first_seen, site, category)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (ad_id, title, price, size, phone, images, url, '', now, site, category))
    conn.commit()

def mark_served(cur, conn, ad_id):
    """Mark an ad as served to Ana"""
    now = datetime.now().strftime("%d.%m %Y")
    cur.execute("""
        UPDATE listings SET status='served', last_served=?, times_served=times_served+1 WHERE id=?
    """, (now, ad_id))
    conn.commit()

def update_status(cur, conn, ad_id, status):
    """Update ad status (CONTACTED, ACCEPTED, NOT_INTERESTED, DEAD)"""
    cur.execute("UPDATE listings SET status=? WHERE id=?", (status, ad_id))
    conn.commit()

# -------------------------------
# USER AGENTS
# -------------------------------
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

# -------------------------------
# PRIORITY TIERS
# -------------------------------
PRIORITY = {
    "apartments_rent": 1,
    "apartments_sale": 1,
    "commercial_rent": 2,
    "commercial_sale": 2,
    "houses_rent": 2,
    "houses_sale": 2,
    "land_sale": 3,
    "garages_sale": 3,
    "warehouses": 3,
    "weekenders": 4,
    "containers": 4,
}

def get_priority_tier(category_name):
    """Get priority tier from category name"""
    cat_lower = category_name.lower()
    if "стан" in cat_lower or "stanovi" in cat_lower or "apartment" in cat_lower:
        if "изнајм" in cat_lower or "rent" in cat_lower or "renta" in cat_lower:
            return 1
        return 1
    if "делов" in cat_lower or "delov" in cat_lower or "commercial" in cat_lower:
        if "изнајм" in cat_lower or "rent" in cat_lower or "renta" in cat_lower:
            return 2
        return 2
    if "куќ" in cat_lower or "kukj" in cat_lower or "house" in cat_lower:
        return 2
    if "плац" in cat_lower or "plac" in cat_lower or "land" in cat_lower:
        return 3
    if "гараж" in cat_lower or "garaz" in cat_lower or "garage" in cat_lower:
        return 3
    if "бараќ" in cat_lower or "barak" in cat_lower or "warehous" in cat_lower or "магац" in cat_lower:
        return 3
    if "викенд" in cat_lower or "vikend" in cat_lower or "weekend" in cat_lower:
        return 4
    if "контejн" in cat_lower or "kontejn" in cat_lower or "container" in cat_lower:
        return 4
    return 3  # default
