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

    # Read CSV. `id` is required (serve_ana now emits it); `source` (site) is
    # optional and, when present, scopes the update to that site's DBs so an id
    # that exists on two sites is never updated in the wrong one.
    updates = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ad_id = row.get("id") or row.get("ID") or row.get("ad_id")
            status = row.get("status", "")
            source = (row.get("source") or row.get("site") or "").strip()
            if ad_id and status:
                updates.append((source, str(ad_id), status))

    if not updates:
        print("No rows with both `id` and `status` found in the CSV.")
        print("If this is Ana's lead file, it has no status column — export a "
              "status CSV (id,source,status) from the back-office first.")
        return

    print(f"Found {len(updates)} status updates in CSV")

    # Find all DBs
    dbs = find_all_dbs()
    print(f"Checking {len(dbs)} databases...")

    total_updated = 0
    for db_path in dbs:
        site = next((s for s in ("PAZAR3", "REKLAMA5", "IMOTI247")
                     if os.sep + s + os.sep in db_path), "")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        db_updates = 0
        for source, ad_id, status in updates:
            if source and site and source.upper() != site:
                continue
            cur.execute("UPDATE listings SET status=? WHERE id=?", (status, ad_id))
            if cur.rowcount > 0:
                db_updates += 1

        conn.commit()
        conn.close()

        if db_updates > 0:
            print(f"  Updated {db_updates} ads in {db_path}")
            total_updated += db_updates

    print(f"\nTotal ads updated across all DBs: {total_updated}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 update_status.py /path/to/ana_batch_YYYY-MM-DD.csv")
        print("Example: python3 update_status.py output/ana_batch_2026-08-28.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    update_dbs(csv_path)
