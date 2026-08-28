# batch_scraper.py
# Master runner - finds all 29 category configs and runs each scraper sequentially
# Usage: python3 batch_scraper.py

import os
import sys
import json
import subprocess
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_all_configs():
    """Find all config.json files across PAZAR3, REKLAMA5, IMOTI247"""
    configs = []
    for site_dir in ["PAZAR3", "REKLAMA5", "IMOTI247"]:
        site_path = os.path.join(BASE_DIR, site_dir)
        if not os.path.isdir(site_path):
            continue
        # Find the base scraper
        scraper_name = f"_{site_dir.lower()}_scraper.py"
        scraper_path = os.path.join(site_path, scraper_name)
        if not os.path.exists(scraper_path):
            print(f"WARNING: Base scraper not found: {scraper_path}")
            continue

        # Find all category folders with config.json
        for category_dir in sorted(os.listdir(site_path)):
            config_path = os.path.join(site_path, category_dir, "config.json")
            if os.path.exists(config_path):
                configs.append({
                    "config": config_path,
                    "scraper": scraper_path,
                    "site": site_dir,
                    "category": category_dir
                })

    return configs

def run_scraper(config_info):
    """Run a single scraper for one category"""
    scraper = config_info["scraper"]
    config = config_info["config"]
    category = config_info["category"]

    print(f"\n{'#'*70}")
    print(f"# RUNNING: {category}")
    print(f"# Scraper: {scraper}")
    print(f"# Config:  {config}")
    print(f"# Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")

    try:
        result = subprocess.run(
            [sys.executable, scraper, config],
            cwd=BASE_DIR,
            timeout=3600,  # 1 hour max per category
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print(f"✅ {category} — COMPLETED")
            if result.stdout:
                # Print last few lines of output
                lines = result.stdout.strip().split('\n')
                for line in lines[-5:]:
                    print(f"   {line}")
        else:
            print(f"❌ {category} — FAILED (exit code {result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:500]}")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        print(f"⏰ {category} — TIMEOUT (1 hour)")
        return False
    except Exception as e:
        print(f"💥 {category} — ERROR: {e}")
        return False

def main():
    print(f"{'='*70}")
    print(f"BATCH SCRAPER — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    configs = find_all_configs()
    print(f"\nFound {len(configs)} categories to scrape:")
    for c in configs:
        print(f"  {c['site']}/{c['category']}")

    results = {"success": [], "failed": []}
    start_time = time.time()

    for i, config in enumerate(configs):
        print(f"\n[{i+1}/{len(configs)}] Starting...")
        success = run_scraper(config)
        if success:
            results["success"].append(config["category"])
        else:
            results["failed"].append(config["category"])

        # Brief pause between categories
        if i < len(configs) - 1:
            time.sleep(5)

    elapsed = time.time() - start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)

    print(f"\n{'='*70}")
    print(f"BATCH COMPLETE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {hours}h {minutes}m")
    print(f"Success: {len(results['success'])}/{len(configs)}")
    print(f"Failed:  {len(results['failed'])}/{len(configs)}")
    if results['failed']:
        print(f"Failed categories: {', '.join(results['failed'])}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
