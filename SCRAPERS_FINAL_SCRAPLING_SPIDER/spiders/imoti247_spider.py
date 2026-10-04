# spiders/imoti247_spider.py
# IMOTI247 spider. Listing and ad pages load through an async stealth browser
# session (patchright/Chromium); the phone is fetched from the site's AJAX
# endpoint through the fast TLS-impersonating HTTP session.
#
# This uses Scrapling's multi-session routing: one spider, two session types.
# Requires browser binaries:  scrapling install

from __future__ import annotations

import os
import re
import sys
import shutil

from scrapling.spiders import Request
from scrapling.fetchers import FetcherSession, AsyncStealthySession

# Pick up a browser bundled inside the project folder (pinned version) if present.
_SHARED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
from browser import browser_launch_kwargs  # noqa: E402


def _real_chrome() -> bool:
    """Use the installed system Chrome when present (no browser download)."""
    env = os.environ.get("SCRAPING_REAL_CHROME")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "no", "off")
    return any(shutil.which(b) for b in
               ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"))

from .base import BaseCategorySpider
from .parsers import ad_id_from_url, phone_imoti, images_imoti


async def _scroll_listing(page):
    """Scrapling `page_action` (async variant): scroll listings to lazy-load.

    Ad pages (URLs ending in `.html`) are skipped. Failures are swallowed so a
    scroll problem can never break the fetch.
    """
    try:
        if page.url and ".html" in page.url:
            return
        for _ in range(12):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(300)
    except Exception:
        pass


class Imoti247Spider(BaseCategorySpider):
    name = "imoti247"
    listing_sid = "browser"

    # A single browser tab in flight on a low-RAM machine.
    concurrent_requests = 1
    download_delay = 1.0

    def configure_sessions(self, manager):
        manager.add("http", FetcherSession(impersonate="chrome", stealthy_headers=True,
                                           retries=3, timeout=30.0))
        browser_kwargs = {"real_chrome": _real_chrome()}
        browser_kwargs.update(browser_launch_kwargs())
        manager.add(
            "browser",
            AsyncStealthySession(
                headless=True,
                network_idle=True,
                timeout=60000,
                disable_resources=False,
                page_action=_scroll_listing,
                **browser_kwargs,
            ),
            lazy=True,
        )

    def build_listing_url(self, page: int) -> str:
        return f"{self.base_url}&page={page}"

    async def parse(self, response):
        soup = self.soup_of(response)
        seen = set()
        for a in soup.select("a[href*='.html']"):
            href = a.get("href")
            if not href or ".html" not in href:
                continue
            # Listing hrefs are RELATIVE (e.g. "/se-izdava-77048.html"); do not
            # require "imoti247.com" in the href.
            full = href if href.startswith("http") else (
                "https://imoti247.com" + (href if href.startswith("/") else "/" + href))
            ad_id = ad_id_from_url(full, "imoti247")
            if not ad_id or not self.is_new(ad_id, seen):
                continue
            yield Request(full, sid="browser", callback=self.parse_ad, meta={"ad_id": ad_id})

    async def parse_ad(self, response):
        ad_id = response.meta.get("ad_id") or ad_id_from_url(response.url, "imoti247")
        if not ad_id:
            return

        soup = self.soup_of(response)
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else "NO TITLE"
        images = images_imoti(soup)

        phone_url = f"https://imoti247.com/description.php?get_phone=1&id={ad_id}"
        yield Request(phone_url, sid="http", callback=self.parse_phone,
                      meta={"ad_id": ad_id, "title": title,
                            "images": images, "url": response.url})

    async def parse_phone(self, response):
        meta = response.meta
        phone = phone_imoti(response.html_content or "")
        yield {
            "id": meta.get("ad_id", ""),
            "title": meta.get("title", "NO TITLE"),
            "price": "N/A",
            "size": "N/A",
            "contact": phone,
            "images": meta.get("images", ""),
            "url": meta.get("url", response.url),
            "site": self.site,
            "category": self.category,
        }
