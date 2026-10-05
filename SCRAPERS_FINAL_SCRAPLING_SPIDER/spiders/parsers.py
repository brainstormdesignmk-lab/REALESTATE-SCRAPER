# spiders/parsers.py
# Site-specific extraction helpers (phone / price / size / images).
# These mirror the logic from the original same-named scrapers so behaviour —
# including the agency filtering and the Pazar3 platform-number exclusion —
# is preserved.

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "_shared"))

from utils import (  # noqa: E402
    normalize_phone,
    PAZAR3_PLATFORM_PHONE,
    EXCLUDE_PHONES,
)
from phones import extract_phones, extract_phone_text  # noqa: E402


# --------------------------------------------------------------------- shared
def ad_id_from_url(url: str, site: str) -> str:
    if site == "reklama5":
        m = re.search(r"ad=(\d+)", url)
    elif site == "imoti247":
        m = re.search(r"-(\d+)\.html", url)
    else:  # pazar3
        m = re.search(r"/(\d+)(?:\?|$)", url)
    return m.group(1) if m else ""


def extract_price_size(text: str):
    """Pazar3-style price/size extraction from ad text."""
    price = "N/A"
    price_m = re.search(r"(\d[\d\s\.\,]*)\s*€.*?/.*?месец", text, re.IGNORECASE)
    if not price_m:
        price_m = re.search(r"(\d[\d\s\.\,]*)\s*€", text)
    if price_m:
        num = price_m.group(1).replace(" ", "").replace(".", "").replace(",", "")
        price = f"{num} €"
    size_m = re.search(r"(\d+)\s*m²", text)
    size = f"{size_m.group(1)} m²" if size_m else "N/A"
    return price, size


# -------------------------------------------------------------------- PAZAR3
def phone_pazar3(html: str) -> str:
    """Shared engine: tel: links, <bdi> dropdowns, contact buttons and body
    text. Excludes the Pazar3 platform number and known agency numbers, and
    rejects map coordinates. Returns the DB-ready "a | b" contact string."""
    return extract_phone_text(html=html, exclude=[PAZAR3_PLATFORM_PHONE] + EXCLUDE_PHONES)


def images_pazar3(soup) -> str:
    img_tags = soup.select("img[data-src*='pazar3']")
    images = [img.get("data-src") for img in img_tags if img.get("data-src")]
    return " | ".join(images) if images else ""


# ------------------------------------------------------------------ REKLAMA5
def phone_reklama5(soup, html: str = "") -> str:
    """Shared engine over both the parsed page (text + <bdi>) and the raw HTML
    (so tel: links are seen too)."""
    return extract_phone_text(soup=soup, html=html or None)


def phone_from_text(text: str) -> str:
    """Extract a phone from a raw response body (used by the ShowPhone fallback)."""
    phones = extract_phones(html=text)
    return phones[0] if phones else ""


def images_reklama5(soup) -> str:
    img_urls = re.findall(r"photos/xbig/[a-f0-9-]+\.jpg", str(soup))
    img_urls = list(dict.fromkeys(img_urls))
    full = [f"https://reklama5.mk/{img}" for img in img_urls]
    return " | ".join(full) if full else ""


# ------------------------------------------------------------------- IMOTI247
def phone_imoti(raw_text: str) -> str:
    """Parse the AJAX phone endpoint response body with the shared engine."""
    return extract_phone_text(html=raw_text)


def images_imoti(soup) -> str:
    img_tags = soup.select("img[src*='imoti247']")
    images = [img.get("src") for img in img_tags
              if img.get("src") and "logo" not in img.get("src", "").lower()]
    return " | ".join(images) if images else ""
