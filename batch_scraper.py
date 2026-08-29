# batch_scraper.py
# Master runner - finds all 29 category configs and runs each scraper sequentially
# Usage: python3 batch_scraper.py

import os
import sys
import json
import subprocess
import time
import threading
import signal
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

# Timeout per category: 30 min for Pazar3/Reklama5, 45 min for Imoti247 (Chrome is slower)
TIMEOUT_DEFAULT = 1800   # 30 min
TIMEOUT_IMOTI = 2700     # 45 min

def run_scraper(config_info):
    """Run a single scraper for one category with proper timeout killing"""
    scraper = config_info["scraper"]
    config = config_info["config"]
    category = config_info["category"]
    site = config_info["site"]

    # Imoti247 uses Chrome — needs more time
    timeout_sec = TIMEOUT_IMOTI if site == "IMOTI247" else TIMEOUT_DEFAULT
    timeout_min = timeout_sec // 60

    print(f"\n{'#'*70}")
    print(f"# RUNNING: {category}")
    print(f"# Scraper: {scraper}")
    print(f"# Config:  {config}")
    print(f"# Timeout: {timeout_min} min")
    print(f"# Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")

    process = None
    timed_out = threading.Event()

    def kill_children(parent_pid):
        """Kill all child processes (Chrome/chromedriver) of a given parent"""
        try:
            # Kill process group — ensures all children die
            os.killpg(os.getpgid(parent_pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            os.kill(parent_pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def timeout_killer():
        """Runs in a thread — kills the process AND its Chrome children after timeout"""
        timed_out.wait(timeout_sec)
        if not timed_out.is_set() and process and process.poll() is None:
            print(f"\n⏰ KILLING {category} — exceeded {timeout_min} min timeout")
            kill_children(process.pid)

    try:
        process = subprocess.Popen(
            [sys.executable, "-u", scraper, config],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid  # New process group — killpg kills all children
        )

        # Start the watchdog timer
        killer = threading.Thread(target=timeout_killer, daemon=True)
        killer.start()

        # Stream output live — every line appears as it's produced
        for line in process.stdout:
            print(f"   {line}", end="")

        # stdout closed — process is done or hung
        process.wait(timeout=10)
        timed_out.set()  # Signal the killer thread to stop

        if process.returncode == 0:
            print(f"✅ {category} — COMPLETED")
        else:
            print(f"❌ {category} — FAILED (exit code {process.returncode})")

        # Clean up any orphaned Chrome children even on normal exit
        try:
            kill_children(process.pid)
        except Exception:
            pass

        return process.returncode == 0

    except Exception as e:
        print(f"💥 {category} — ERROR: {e}")
        if process and process.poll() is None:
            kill_children(process.pid)
        timed_out.set()
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
