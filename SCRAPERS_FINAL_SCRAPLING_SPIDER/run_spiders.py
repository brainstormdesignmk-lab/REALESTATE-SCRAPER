# run_spiders.py  (Scrapling Spider variant)
# Runs one spider per category, sequentially, writing into the same per-category
# SQLite layout as the original scrapers.
#
# Usage:
#   python run_spiders.py                  # all categories, all sites
#   python run_spiders.py --site REKLAMA5  # one site
#   python run_spiders.py --limit 1        # smoke test: first category only
#   python run_spiders.py --dry-run        # list, do nothing
#
# Run through the venv:
#   .venv/bin/python run_spiders.py
#
# IMOTI247 needs the stealth browser installed once:  .venv/bin/scrapling install

from __future__ import annotations

import os
import sys
import time
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

SITES = ["PAZAR3", "REKLAMA5", "IMOTI247"]


def find_configs(site_filter=None):
    configs = []
    for site in SITES:
        if site_filter and site != site_filter:
            continue
        site_dir = os.path.join(BASE_DIR, site)
        if not os.path.isdir(site_dir):
            continue
        for cat in sorted(os.listdir(site_dir)):
            cfg = os.path.join(site_dir, cat, "config.json")
            if os.path.exists(cfg):
                configs.append({"site": site, "category": cat, "config": cfg})
    return configs


def run_one(entry):
    """Instantiate and run the spider for one category."""
    from spiders import SITE_SPIDERS

    spider_cls = SITE_SPIDERS[entry["site"]]
    spider = spider_cls(entry["config"], crawldir=entry.get("crawldir"))

    started = time.time()
    result = spider.start()
    elapsed = time.time() - started

    items = len(result.items) if hasattr(result, "items") else 0
    print(f"  items streamed: {items}")
    print(f"  DB writes:      {spider.counts['new']}")
    print(f"  blocked:        {spider.counts['blocked']}")
    print(f"  errors:         {spider.counts['errors']}")
    print(f"  elapsed:        {elapsed:.1f}s")
    return spider.counts


def main():
    parser = argparse.ArgumentParser(description="Run Scrapling spiders per category.")
    parser.add_argument("--site", choices=SITES, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--crawldir", default=None,
                        help="Enable checkpoint/resume. Base dir; per-category subdirs are created.")
    args = parser.parse_args()

    print(f"{'=' * 70}")
    print(f"SCRAPLING SPIDER RUNNER — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")

    configs = find_configs(args.site)
    if args.limit:
        configs = configs[:args.limit]

    print(f"\nFound {len(configs)} categories:")
    for c in configs:
        print(f"  {c['site']}/{c['category']}")

    if args.dry_run:
        print("\n--dry-run: nothing executed.")
        return

    totals = {"new": 0, "blocked": 0, "errors": 0}
    failures = []
    start = time.time()

    for i, entry in enumerate(configs):
        label = f"{entry['site']}/{entry['category']}"
        print(f"\n{'#' * 70}")
        print(f"# [{i + 1}/{len(configs)}] {label}")
        print(f"# Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#' * 70}")
        try:
            crawldir = None
            if args.crawldir:
                crawldir = os.path.join(args.crawldir, f"{entry['site']}_{entry['category']}")
            counts = run_one({**entry, "crawldir": crawldir})
            for k in totals:
                totals[k] += counts.get(k, 0)
        except Exception as e:
            print(f"FAIL {label}: {type(e).__name__}: {e}")
            failures.append(label)

    elapsed = time.time() - start
    print(f"\n{'=' * 70}")
    print(f"SPIDER RUN COMPLETE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {int(elapsed // 60)}m {int(elapsed % 60)}s")
    print(f"Categories run: {len(configs) - len(failures)}/{len(configs)}")
    print(f"New DB writes:  {totals['new']}")
    if totals["blocked"]:
        print(f"BLOCKED:        {totals['blocked']}  <-- investigate")
    if totals["errors"]:
        print(f"DB errors:      {totals['errors']}")
    if failures:
        print(f"Failed: {', '.join(failures)}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
