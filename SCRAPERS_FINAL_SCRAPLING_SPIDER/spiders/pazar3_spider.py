# spiders/pazar3_spider.py
# PAZAR3 spider — listing pages are parsed for ad links; each new ad page is
# fetched through the shared TLS-impersonating HTTP session.

from __future__ import annotations

from scrapling.spiders import Request

from .base import BaseCategorySpider
from .parsers import (
    ad_id_from_url,
    extract_price_size,
    phone_pazar3,
    images_pazar3,
)

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_shared"))
from utils import is_agency  # noqa: E402

BASE = "https://www.pazar3.mk"


class Pazar3Spider(BaseCategorySpider):
    name = "pazar3"
    listing_sid = "http"

    def build_listing_url(self, page: int) -> str:
        return f"{self.base_url}&page={page}"

    async def parse(self, response):
        soup = self.soup_of(response)
        seen = set()
        for a in soup.select("a[href^='/oglas/']"):
            href = a.get("href")
            if not href or "/oglas/" not in href:
                continue
            ad_id = href.split("/")[-1].split("?")[0]
            if not ad_id.isdigit():
                continue
            if not self.is_new(ad_id, seen):
                continue
            yield Request(BASE + href, sid="http", callback=self.parse_ad)

    async def parse_ad(self, response):
        ad_id = ad_id_from_url(response.url, "pazar3")
        if not ad_id:
            return

        soup = self.soup_of(response)
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title or len(title) < 5:
            return

        phone = phone_pazar3(response.html_content or "")
        if is_agency(title, phone or None):
            return

        price, size = extract_price_size(title)
        images = images_pazar3(soup)

        yield {
            "id": ad_id,
            "title": title,
            "price": price,
            "size": size,
            "contact": phone,
            "images": images,
            "url": response.url,
            "site": self.site,
            "category": self.category,
        }
