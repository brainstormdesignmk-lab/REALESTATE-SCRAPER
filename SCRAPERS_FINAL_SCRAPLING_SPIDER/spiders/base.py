# spiders/base.py
# Shared base for the three site spiders. Each spider is instantiated with the
# path to one category's config.json, and writes into the SAME per-category
# SQLite layout the original scrapers used, so serve_ana.py / update_status.py
# keep working unchanged.
#
# Tuned for a low-RAM target (IBM Core 2 Duo / 3 GB):
#   - one request in flight at a time  (concurrent_requests = 1)
#   - a fixed polite download_delay
#   - AutoThrottle on, backing off automatically when a site pushes back
#   - items are written to SQLite inside `on_scraped_item`, so nothing is held
#     in memory waiting for the crawl to finish

from __future__ import annotations

import os
import sys
import json
import sqlite3
from typing import Any, Dict, List, Optional

from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import FetcherSession

# Make _shared importable no matter where the runner is invoked from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "_shared"))

from utils import init_db, ad_exists, insert_ad, is_agency, normalize_phone  # noqa: E402

BLOCKED_CODES = (403, 429, 503)


class BaseCategorySpider(Spider):
    """Base class: config loading, DB lifecycle, item sink, HTTP session."""

    name = "base"

    # Politeness / resource settings (override in subclasses if needed).
    concurrent_requests = 1
    concurrent_requests_per_domain = 1
    download_delay = 1.5
    max_blocked_retries = 3
    autothrottle_enabled = True
    autothrottle_start_delay = 3.0
    autothrottle_max_delay = 60.0

    # Which session the listing pages use. Subclasses may change this.
    listing_sid = "http"

    def __init__(self, config_path: str, crawldir: Optional[str] = None, interval: float = 300.0):
        self.config_path = os.path.abspath(config_path)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.site = self.config.get("site", "unknown")
        self.category = self.config.get("category", "Unknown")
        self.pages = int(self.config.get("pages", 10))
        self.base_url = self.config["url"]

        self.category_dir = os.path.dirname(self.config_path)
        self.db_path = os.path.join(self.category_dir, "data", f"{self.site}.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn, self.cur = init_db(self.db_path)

        self.counts = {"new": 0, "blocked": 0, "errors": 0}

        # `name` is read by Spider.__init__; give it a unique, readable value.
        self.name = f"{self.site}_{os.path.basename(self.category_dir)}"

        super().__init__(crawldir=crawldir, interval=interval)

    # ------------------------------------------------------------------ sessions
    def configure_sessions(self, manager):
        manager.add(
            "http",
            FetcherSession(
                impersonate="chrome",
                stealthy_headers=True,
                retries=3,
                timeout=30.0,
            ),
        )

    # -------------------------------------------------------------- start requests
    def build_listing_url(self, page: int) -> str:
        raise NotImplementedError

    async def start_requests(self):
        for page in range(1, self.pages + 1):
            yield Request(self.build_listing_url(page), sid=self.listing_sid, callback=self.parse)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def status_of(resp) -> int:
        return getattr(resp, "status", None) or getattr(resp, "status_code", 0)

    @staticmethod
    def soup_of(resp):
        from bs4 import BeautifulSoup
        # `resp.text` is the element text (Response IS a Selector); the page
        # HTML is `.html_content`.
        return BeautifulSoup(resp.html_content or "", "lxml")

    def is_new(self, ad_id: str, seen: set) -> bool:
        if not ad_id or ad_id in seen:
            return False
        seen.add(ad_id)
        return not ad_exists(self.cur, ad_id)

    # -------------------------------------------------------------- item sink
    async def on_scraped_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Persist each scraped item immediately and keep it in memory."""
        try:
            insert_ad(
                self.cur, self.conn,
                item["id"], item["title"],
                item.get("price", "N/A"), item.get("size", "N/A"),
                item.get("contact", ""), item.get("images", ""),
                item["url"], item["site"], item["category"],
            )
            self.counts["new"] += 1
        except Exception as e:  # never let a bad row kill the crawl
            self.counts["errors"] += 1
            print(f"  [DB ERROR] {item.get('id')}: {type(e).__name__}: {e}")
        return item

    async def is_blocked(self, response) -> bool:
        blocked = self.status_of(response) in BLOCKED_CODES
        if blocked:
            self.counts["blocked"] += 1
        return blocked

    async def on_close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # The abstract parse() each site implements.
    async def parse(self, response: "Response"):  # pragma: no cover - abstract
        raise NotImplementedError
        yield
