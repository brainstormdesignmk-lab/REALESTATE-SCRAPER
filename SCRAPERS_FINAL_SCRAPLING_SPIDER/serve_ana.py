# serve_ana.py
# Reads all 29 category DBs, generates prioritized daily CSV for Ana
# Usage: python3 serve_ana.py

import os
import sys
import sqlite3
import csv
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_all_dbs():
    """Find all SQLite DBs across category folders"""
    dbs = []
    for site_dir in ["PAZAR3", "REKLAMA5", "IMOTI247"]:
        site_path = os.path.join(BASE_DIR, site_dir)
        if not os.path.isdir(site_path):
            continue
        for category_dir in sorted(os.listdir(site_path)):
            db_path = os.path.join(site_path, category_dir, "data")
            if os.path.isdir(db_path):
                for db_file in os.listdir(db_path):
                    if db_file.endswith(".db"):
                        dbs.append({
                            "db_path": os.path.join(db_path, db_file),
                            "site": site_dir,
                            "category": category_dir
                        })
    return dbs

def read_new_leads(db_info):
    """Read all new/served (not contacted/accepted/dead) leads from a DB"""
    db_path = db_info["db_path"]
    site = db_info["site"]
    category = db_info["category"]

    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get all leads that are not yet contacted/accepted/dead
    cur.execute("""
        SELECT id, title, price, size, contact, images, url, status, first_seen, category
        FROM listings
        WHERE status NOT IN ('CONTACTED', 'ACCEPTED', 'NOT_INTERESTED', 'DEAD')
        AND contact != ''
        AND contact IS NOT NULL
        ORDER BY first_seen DESC
    """)

    leads = []
    for row in cur.fetchall():
        leads.append({
            "id": row[0],
            "title": row[1],
            "price": row[2],
            "size": row[3],
            "phone": row[4],
            "images": row[5],
            "url": row[6],
            "status": row[7],
            "first_seen": row[8],
            "source_category": row[9] if row[9] else category,
            "site": site,
            "folder_category": category
        })

    conn.close()
    return leads

def get_priority(category_name):
    """Get priority tier from category name"""
    cat_lower = category_name.lower()
    # Tier 1: Apartments
    if any(x in cat_lower for x in ["стан", "stanovi", "apartment"]):
        return 1
    # Tier 2: Commercial + Houses
    if any(x in cat_lower for x in ["делов", "delov", "commercial", "куќ", "kukj", "house"]):
        return 2
    # Tier 3: Land, Garages, Warehouses
    if any(x in cat_lower for x in ["плац", "plac", "land", "гараж", "garaz", "garage",
                                      "бараќ", "barak", "warehous", "магац", "magacin"]):
        return 3
    # Tier 4: Weekenders, Containers
    if any(x in cat_lower for x in ["викенд", "vikend", "weekend", "контejн", "kontejn", "container"]):
        return 4
    return 3

def dedup_by_phone(leads):
    """Deduplicate leads by phone number - keep the one with most images"""
    seen_phones = {}
    for lead in leads:
        phone = lead["phone"]
        if not phone:
            continue
        # Normalize phone for comparison
        phone_key = phone.replace(" ", "").replace("+389", "389")
        if phone_key in seen_phones:
            # Keep the one with more images
            existing = seen_phones[phone_key]
            existing_images = len(existing["images"].split(" | ")) if existing["images"] else 0
            new_images = len(lead["images"].split(" | ")) if lead["images"] else 0
            if new_images > existing_images:
                seen_phones[phone_key] = lead
        else:
            seen_phones[phone_key] = lead

    # Also keep leads with no phone (shouldn't happen but safety)
    no_phone = [l for l in leads if not l["phone"]]
    deduped = list(seen_phones.values()) + no_phone
    return deduped

def generate_csv(leads, output_path):
    """Generate CSV for Ana"""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "category", "title", "price", "size", "phone", "images", "url", "status", "date"])

        for lead in leads:
            writer.writerow([
                lead["site"],
                lead["source_category"],
                lead["title"],
                lead["price"],
                lead["size"],
                lead["phone"],
                lead["images"],
                lead["url"],
                lead["status"],
                lead["first_seen"]
            ])

    return len(leads)

def main():
    print(f"{'='*70}")
    print(f"SERVE ANA — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    # Find all DBs
    dbs = find_all_dbs()
    print(f"\nFound {len(dbs)} category databases")

    # Read all leads
    all_leads = []
    for db_info in dbs:
        leads = read_new_leads(db_info)
        print(f"  {db_info['site']}/{db_info['category']}: {len(leads)} leads")
        all_leads.extend(leads)

    print(f"\nTotal leads (before dedup): {len(all_leads)}")

    # Dedup by phone
    deduped = dedup_by_phone(all_leads)
    print(f"After dedup: {len(deduped)}")

    # Sort by priority (apartments first, then commercial/houses, then others)
    deduped.sort(key=lambda x: (get_priority(x["source_category"]), x["first_seen"]))

    # Generate CSV
    output_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"ana_batch_{datetime.now().strftime('%Y-%m-%d')}.csv")

    count = generate_csv(deduped, output_path)

    print(f"\n{'='*70}")
    print(f"CSV GENERATED: {output_path}")
    print(f"Total leads: {count}")
    print(f"{'='*70}")

    # Summary by priority
    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for lead in deduped:
        tier = get_priority(lead["source_category"])
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    print(f"\nBy priority tier:")
    print(f"  TIER 1 (Apartments):     {tier_counts[1]}")
    print(f"  TIER 2 (Commercial/Houses): {tier_counts[2]}")
    print(f"  TIER 3 (Land/Garages):   {tier_counts[3]}")
    print(f"  TIER 4 (Weekenders):     {tier_counts[4]}")

if __name__ == "__main__":
    main()
