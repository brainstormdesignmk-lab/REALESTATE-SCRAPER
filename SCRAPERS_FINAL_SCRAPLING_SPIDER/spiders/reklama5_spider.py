# spiders/reklama5_spider.py
# REKLAMA5 spider. The HTTP session impersonates Chrome's TLS fingerprint,
# which is what defeats the 403 block. When the phone is hidden behind the
# site's "Show phone" link, a second request is issued for it.

from __future__ import annotations

from scrapling.spiders import Request

from .base import BaseCategorySpider
from .parsers import (
    ad_id_from_url,
    phone_reklama5,
    phone_from_text,
    images_reklama5,
)

import os
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_shared"))
from utils import is_agency  # noqa: E402

BASE = "https://reklama5.mk"


class Reklama5Spider(BaseCategorySpider):
    name = "reklama5"
    listing_sid = "http"

    def build_listing_url(self, page: int) -> str:
        url = re.sub(r"page=\d+", f"page={page}", self.base_url)
        if "page=" not in url:
            url = f"{url}&page={page}"
        return url

    async def parse(self, response):
        soup = self.soup_of(response)
        seen = set()
        for link in soup.find_all("a", href=re.compile(r"/AdDetails\?ad=")):
            title = link.get_text(strip=True)
            if len(title) < 8 or is_agency(title):
                continue
            href = link["href"]
            if not href.startswith("http"):
                href = BASE + href
            ad_id = ad_id_from_url(href, "reklama5")
            if not ad_id or not self.is_new(ad_id, seen):
                continue
            yield Request(href, sid="http", callback=self.parse_ad,
                          meta={"ad_id": ad_id, "title": title})

    async def parse_ad(self, response):
        ad_id = response.meta.get("ad_id") or ad_id_from_url(response.url, "reklama5")
        title = response.meta.get("title", "")
        if not ad_id:
            return

        soup = self.soup_of(response)
        phone = phone_reklama5(soup, response.html_content or "")
        images = images_reklama5(soup)

        if phone and is_agency(title, phone):
            return

        if not phone:
            show_link = soup.find("a", href=re.compile(r"/ShowPhone"))
            if show_link:
                show_url = BASE + show_link["href"]
                yield Request(show_url, sid="http", callback=self.parse_showphone,
                              meta={"ad_id": ad_id, "title": title,
                                    "images": images, "url": response.url})
                return

        yield self._item(ad_id, title, phone, images, response.url)

    async def parse_showphone(self, response):
        meta = response.meta
        phone = phone_from_text(response.html_content or "")
        yield self._item(meta.get("ad_id", ""), meta.get("title", ""),
                         phone, meta.get("images", ""), meta.get("url", response.url))

    def _item(self, ad_id, title, phone, images, url):
        return {
            "id": ad_id,
            "title": title,
            "price": "N/A",
            "size": "N/A",
            "contact": phone,
            "images": images,
            "url": url,
            "site": self.site,
            "category": self.category,
        }
