# update_status.py
# Reads Ana's updated CSV and updates DBs with CONTACTED/ACCEPTED status
# Usage: python3 update_status.py /path/to/ana_batch_YYYY-MM-DD.csv

import os
import sys
import csv
import sqlite3
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
                        dbs.append(os.path.join(db_path, db_file))
    return dbs

def update_dbs(csv_path):
    """Read CSV and update all matching DBs"""
    if not os.path.exists(csv_path):
        print(f"CSV not found: {csv_path}")
        return

    # Read CSV
    updates = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ad_id = row.get("id") or row.get("ID") or row.get("ad_id")
            status = row.get("status", "")
            if ad_id and status:
                updates[ad_id] = status

    print(f"Found {len(updates)} status updates in CSV")

    # Find all DBs
    dbs = find_all_dbs()
    print(f"Checking {len(dbs)} databases...")

    total_updated = 0
    for db_path in dbs:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        db_updates = 0
        for ad_id, status in updates.items():
            cur.execute("UPDATE listings SET status=? WHERE id=?", (status, ad_id))
            if cur.rowcount > 0:
                db_updates += 1

        conn.commit()
        conn.close()

        if db_updates > 0:
            print(f"  Updated {db_updates} ads in {os.path.basename(db_path)}")
            total_updated += db_updates

    print(f"\nTotal ads updated across all DBs: {total_updated}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 update_status.py /path/to/ana_batch_YYYY-MM-DD.csv")
        print("Example: python3 update_status.py output/ana_batch_2026-08-28.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    update_dbs(csv_path)
