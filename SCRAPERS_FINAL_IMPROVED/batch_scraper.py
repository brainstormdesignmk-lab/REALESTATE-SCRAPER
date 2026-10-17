# batch_scraper.py  (Scrapling edition)
# Master runner - finds all category configs and runs each scraper sequentially.
#
# Usage:
#   python batch_scraper.py                 # run every category on all 3 sites
#   python batch_scraper.py --site REKLAMA5 # run one site only
#   python batch_scraper.py --dry-run       # list what would run, do nothing
#   python batch_scraper.py --limit 3       # run only the first 3 categories
#
# Always run this through the venv so the child scrapers use the same Python
# that has Scrapling installed:
#   .venv/bin/python batch_scraper.py
# If you must call a different interpreter, set SCRAPER_PYTHON=/path/to/python.

import os
import sys
import argparse
import subprocess
import time
import threading
import signal
from datetime import datetime

# Force ALL print() calls to flush immediately — fixes SSH live output
_original_print = print


def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    return _original_print(*args, **kwargs)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITES = ["PAZAR3", "REKLAMA5", "IMOTI247"]

# Timeout per category. The stealth browser on a Core 2 Duo is slow, so
# Imoti247 gets a generous budget; the HTTP sites are much faster.
TIMEOUT_DEFAULT = 1800   # 30 min
TIMEOUT_IMOTI = 7200     # 120 min


def find_all_configs(site_filter=None):
    """Find all config.json files across the three sites."""
    configs = []
    for site_dir in SITES:
        if site_filter and site_dir != site_filter:
            continue
        site_path = os.path.join(BASE_DIR, site_dir)
        if not os.path.isdir(site_path):
            continue

        scraper_name = f"_{site_dir.lower()}_scraper.py"
        scraper_path = os.path.join(site_path, scraper_name)
        if not os.path.exists(scraper_path):
            print(f"WARNING: Base scraper not found: {scraper_path}")
            continue

        for category_dir in sorted(os.listdir(site_path)):
            config_path = os.path.join(site_path, category_dir, "config.json")
            if os.path.exists(config_path):
                configs.append({
                    "config": config_path,
                    "scraper": scraper_path,
                    "site": site_dir,
                    "category": category_dir,
                })
    return configs


def run_scraper(config_info):
    """Run a single scraper for one category with timeout killing."""
    scraper = config_info["scraper"]
    config = config_info["config"]
    category = config_info["category"]
    site = config_info["site"]

    timeout_sec = TIMEOUT_IMOTI if site == "IMOTI247" else TIMEOUT_DEFAULT
    timeout_min = timeout_sec // 60
    interpreter = os.environ.get("SCRAPER_PYTHON", sys.executable)

    print(f"\n{'#' * 70}")
    print(f"# RUNNING: {category}")
    print(f"# Python:  {interpreter}")
    print(f"# Scraper: {scraper}")
    print(f"# Config:  {config}")
    print(f"# Timeout: {timeout_min} min")
    print(f"# Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#' * 70}")

    process = None
    timed_out = threading.Event()
    timeout_hit = threading.Event()
    blocked_seen = {"count": 0}

    def kill_children(parent_pid):
        try:
            os.killpg(os.getpgid(parent_pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            os.kill(parent_pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def timeout_killer():
        timed_out.wait(timeout_sec)
        if not timed_out.is_set() and process and process.poll() is None:
            timeout_hit.set()
            print(f"\n  KILLING {category} — exceeded {timeout_min} min timeout")
            kill_children(process.pid)

    try:
        process = subprocess.Popen(
            [interpreter, "-u", scraper, config],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )

        killer = threading.Thread(target=timeout_killer, daemon=True)
        killer.start()

        for line in process.stdout:
            if "BLOCKED" in line:
                blocked_seen["count"] += 1
            print(f"   {line}", end="")

        process.wait(timeout=10)
        timed_out.set()

        if timeout_hit.is_set():
            failure_reason = f"timed out after {timeout_min} min (exit code {process.returncode})"
            print(f"FAIL {category} — {failure_reason}")
        elif process.returncode == 0:
            failure_reason = ""
            print(f"OK   {category} — COMPLETED")
        else:
            failure_reason = f"exit code {process.returncode}"
            print(f"FAIL {category} — {failure_reason}")

        try:
            kill_children(process.pid)
        except Exception:
            pass

        return process.returncode == 0 and not timeout_hit.is_set(), blocked_seen["count"], failure_reason

    except Exception as e:
        print(f"ERROR {category} — {e}")
        if process and process.poll() is None:
            kill_children(process.pid)
        timed_out.set()
        return False, blocked_seen["count"], f"{type(e).__name__}: {e}"


def main():
    parser = argparse.ArgumentParser(description="Run all real-estate scrapers sequentially.")
    parser.add_argument("--site", choices=SITES, default=None,
                        help="Only run categories for this site.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run the first N categories (for testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="List the categories that would run, then exit.")
    args = parser.parse_args()

    print(f"{'=' * 70}")
    print(f"BATCH SCRAPER (Scrapling) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Interpreter: {os.environ.get('SCRAPER_PYTHON', sys.executable)}")
    print(f"{'=' * 70}")

    configs = find_all_configs(args.site)
    if args.limit:
        configs = configs[:args.limit]

    if not configs:
        print("ERROR: no scraper categories found; refusing to report an empty run as successful.")
        return 2

    print(f"\nFound {len(configs)} categories to scrape:")
    for c in configs:
        print(f"  {c['site']}/{c['category']}")

    if args.dry_run:
        print("\n--dry-run: nothing executed.")
        return

    results = {"success": [], "failed": []}
    total_blocked = 0
    start_time = time.time()

    for i, config in enumerate(configs):
        print(f"\n[{i + 1}/{len(configs)}] Starting...")
        success, blocked, failure_reason = run_scraper(config)
        total_blocked += blocked
        label = f"{config['site']}/{config['category']}"
        (results["success"] if success else results["failed"]).append(label)
        if not success:
            results.setdefault("failure_details", []).append((label, failure_reason or "unknown scraper failure"))

        if i < len(configs) - 1:
            time.sleep(5)

    elapsed = time.time() - start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)

    print(f"\n{'=' * 70}")
    print(f"BATCH COMPLETE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {hours}h {minutes}m")
    print(f"Success: {len(results['success'])}/{len(configs)}")
    print(f"Failed:  {len(results['failed'])}/{len(configs)}")
    if results["failed"]:
        print(f"Failed categories: {', '.join(results['failed'])}")
    if total_blocked:
        print(f"BLOCKED responses seen: {total_blocked}  <-- investigate")
    print(f"{'=' * 70}")

    # Category failures are partial-run warnings, not a reason to discard
    # successful category data. The launch wrappers hand this data to Ana on
    # exit code zero, so record the failures and continue the handoff.
    if results["failed"]:
        output_dir = os.path.join(BASE_DIR, "output")
        os.makedirs(output_dir, exist_ok=True)
        failure_log = os.path.join(output_dir, "scraper_failures.log")
        run_stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(failure_log, "a", encoding="utf-8") as log:
            log.write(f"\n[{run_stamp}] PARTIAL SCRAPE — {len(results['failed'])}/{len(configs)} categories failed\n")
            for label, reason in results.get("failure_details", []):
                log.write(f"  - {label}: {reason}\n")
            log.write("  Ana handoff: continuing with data from all category databases.\n")
        print("WARNING: partial scrape; continuing to Ana with available category data.")
        print(f"Failure details written to: {failure_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
