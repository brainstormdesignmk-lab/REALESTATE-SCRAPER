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

from utils import normalize_phone, PAZAR3_PLATFORM_PHONE  # noqa: E402


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
    phones = set()
    patterns = [
        r"(?:\+?389|00389)?[\s\-/]*7\d{7,8}",
        r"0?7\d{7,8}",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html):
            normalized = normalize_phone(match)
            if normalized and normalized != PAZAR3_PLATFORM_PHONE:
                phones.add(normalized)
    for bare in re.findall(r">\s*(\d{7,9})\s*<", html):
        normalized = normalize_phone(bare)
        if normalized and normalized != PAZAR3_PLATFORM_PHONE:
            phones.add(normalized)
    return " | ".join(sorted(phones)) if phones else ""


def images_pazar3(soup) -> str:
    img_tags = soup.select("img[data-src*='pazar3']")
    images = [img.get("data-src") for img in img_tags if img.get("data-src")]
    return " | ".join(images) if images else ""


# ------------------------------------------------------------------ REKLAMA5
def phone_reklama5(soup) -> str:
    page_text = soup.get_text(separator=" ")
    phones = re.findall(r"07[0-9\s\-]{8,14}07[0-9]{7}", page_text)
    phones += re.findall(r"07\d{7}", page_text)
    phones += re.findall(r"\+389\s?7\d\s?\d{3}\s?\d{3}", page_text)
    phones += re.findall(r"07\d\s?\d{3}\s?\d{3}", page_text)
    found = set()
    for p in phones:
        normalized = normalize_phone(p)
        if normalized:
            found.add(normalized)
    return " | ".join(sorted(found)) if found else ""


def phone_from_text(text: str) -> str:
    """Extract a phone from a raw response body (used by the ShowPhone fallback)."""
    match = re.search(r"07\d{7}", text)
    if not match:
        return ""
    normalized = normalize_phone(match.group(0))
    return normalized or ""


def images_reklama5(soup) -> str:
    img_urls = re.findall(r"photos/xbig/[a-f0-9-]+\.jpg", str(soup))
    img_urls = list(dict.fromkeys(img_urls))
    full = [f"https://reklama5.mk/{img}" for img in img_urls]
    return " | ".join(full) if full else ""


# ------------------------------------------------------------------- IMOTI247
def phone_imoti(raw_text: str) -> str:
    """Parse the AJAX phone endpoint response body."""
    cleaned = re.sub(r"[^\d+]", "", raw_text)
    mk_matches = re.findall(r"07[0-8]\d{6}", cleaned)
    if mk_matches:
        # Normalise to the SAME format as Pazar3/Reklama5 so that
        # serve_ana.py's cross-site phone dedup works.
        phones = []
        for m in mk_matches[:2]:
            n = normalize_phone(m)
            if n and n not in phones:
                phones.append(n)
        if phones:
            return " | ".join(phones) if len(phones) > 1 else phones[0]
    intl = re.findall(r"\+\d{10,15}", cleaned)
    if intl:
        return " | ".join(intl[:2])
    return ""


def images_imoti(soup) -> str:
    img_tags = soup.select("img[src*='imoti247']")
    images = [img.get("src") for img in img_tags
              if img.get("src") and "logo" not in img.get("src", "").lower()]
    return " | ".join(images) if images else ""
