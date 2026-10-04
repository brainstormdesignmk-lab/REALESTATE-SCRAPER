# healthcheck.py
# Pre-flight check that runs WITHOUT Scrapling installed, so you can verify the
# layout on any machine before setting up the venv.
#
# Usage:
#   python healthcheck.py             # structural checks only
#   python healthcheck.py --network   # also test reachability of each site
#   python healthcheck.py --network --show-body   # print first bytes of response
#
# Exit code is 0 if all structural checks pass, 1 otherwise.

from __future__ import annotations

import os
import sys
import json
import sqlite3
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "_shared"))  # for scrapling_fetch during --network
SITES = ["PAZAR3", "REKLAMA5", "IMOTI247"]
SITE_HOME = {
    "PAZAR3": "https://www.pazar3.mk/",
    "REKLAMA5": "https://reklama5.mk/",
    "IMOTI247": "https://imoti247.com/",
}
DB_NAME = {"PAZAR3": "pazar3.db", "REKLAMA5": "reklama5.db", "IMOTI247": "imoti247.db"}
EXPECTED = {"PAZAR3": 9, "REKLAMA5": 12, "IMOTI247": 8}

errors = []
warnings = []


def check_python():
    major, minor = sys.version_info[:2]
    print(f"Python: {sys.version.split()[0]}")
    if (major, minor) < (3, 10):
        warnings.append(
            "Python < 3.10 — Scrapling requires 3.10+. The structural checks "
            "still work, but the Scrapling fetchers will not import."
        )


def check_scrapling():
    try:
        import scrapling  # noqa: F401
        print(f"Scrapling: installed (version {getattr(scrapling, '__version__', '?')})")
        try:
            from scrapling.fetchers import Fetcher  # noqa: F401
            print("Scrapling fetchers: available (curl_cffi present)")
            return True
        except Exception as e:
            warnings.append(f"scrapling core imports, but fetchers do not: {e}")
            return False
    except Exception:
        warnings.append("Scrapling NOT installed for this interpreter (expected before setup).")
        return False


def check_browser():
    """Report which browser the IMOTI247 stealth scrapers will use."""
    import shutil

    bundled = None
    try:
        from browser import bundled_browser_path, describe
        bundled = bundled_browser_path(BASE_DIR)
        print(describe(BASE_DIR))
    except Exception as e:
        print(f"Bundled browser: (browser.py not importable: {e})")

    system = [b for b in ("google-chrome", "google-chrome-stable",
                          "chromium", "chromium-browser") if shutil.which(b)]
    if system:
        print(f"System Chrome/Chromium on PATH: {', '.join(system)}")
    if not bundled and not system:
        warnings.append(
            "No bundled browser and no system Chrome/Chromium — IMOTI247 needs "
            "one. Run ./install_browser.sh --cft (or install Chrome)."
        )


def check_layout():
    total = 0
    for site in SITES:
        site_dir = os.path.join(BASE_DIR, site)
        if not os.path.isdir(site_dir):
            errors.append(f"Missing site directory: {site}")
            continue

        scraper = os.path.join(site_dir, f"_{site.lower()}_scraper.py")
        if not os.path.exists(scraper):
            errors.append(f"Missing base scraper: {scraper}")

        cats = []
        for d in sorted(os.listdir(site_dir)):
            cfg = os.path.join(site_dir, d, "config.json")
            if os.path.exists(cfg):
                cats.append(d)
                try:
                    with open(cfg, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for key in ("url", "site", "category", "pages"):
                        if key not in data:
                            errors.append(f"{site}/{d}/config.json missing '{key}'")
                except Exception as e:
                    errors.append(f"{site}/{d}/config.json unreadable: {e}")

                db_path = os.path.join(site_dir, d, "data", DB_NAME[site])
                if os.path.exists(db_path):
                    try:
                        conn = sqlite3.connect(db_path)
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM listings")
                        n = cur.fetchone()[0]
                        conn.close()
                        print(f"  {site}/{d}: config OK, DB {n} rows")
                    except Exception as e:
                        errors.append(f"{site}/{d} DB unreadable: {e}")
                else:
                    warnings.append(f"{site}/{d}: no DB yet at {db_path}")

        total += len(cats)
        print(f"{site}: {len(cats)} categories (expected {EXPECTED[site]})")
        if len(cats) != EXPECTED[site]:
            warnings.append(f"{site}: expected {EXPECTED[site]} categories, found {len(cats)}")

    print(f"Total categories: {total}")
    return total


def check_network():
    print("\nNetwork reachability:")
    try:
        from scrapling_fetch import http_get, ScraplingUnavailable
    except Exception as e:
        warnings.append(f"Could not import scrapling_fetch for network check: {e}")
        return

    for site, url in SITE_HOME.items():
        try:
            resp = http_get(url, timeout=20)
            status = getattr(resp, "status", None) or getattr(resp, "status_code", 0)
            flag = "OK" if status == 200 else "PROBLEM"
            print(f"  {site:9} {url} -> HTTP {status}  [{flag}]")
            if status in (403, 429, 503):
                errors.append(f"{site} returned HTTP {status} even with impersonation")
        except ScraplingUnavailable:
            warnings.append("Network check skipped: Scrapling not installed.")
            return
        except Exception as e:
            warnings.append(f"{site} check failed: {type(e).__name__}: {e}")
            print(f"  {site:9} {url} -> ERROR {type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true", help="Also test site reachability.")
    args = parser.parse_args()

    print("=" * 70)
    print("SCRAPERS_FINAL_IMPROVED — HEALTH CHECK")
    print("=" * 70)

    check_python()
    check_scrapling()
    print("\nBrowser (IMOTI247):")
    check_browser()
    print("\nLayout:")
    check_layout()

    scrapling_ok = False
    try:
        import scrapling  # noqa: F401
        scrapling_ok = True
    except Exception:
        pass

    if args.network:
        if scrapling_ok:
            check_network()
        else:
            warnings.append("--network requested but Scrapling is not installed; skipping.")

    print("\n" + "=" * 70)
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        print(f"\nRESULT: FAILED ({len(errors)} errors)")
        sys.exit(1)
    print("RESULT: OK" + (" (with warnings)" if warnings else ""))


if __name__ == "__main__":
    main()
