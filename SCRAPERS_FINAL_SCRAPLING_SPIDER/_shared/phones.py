# _shared/phones.py
# Shared phone extraction + normalization for Pazar3 / Reklama5 / Imoti247.
#
# Why this module exists (bug report "BUGS PAZAR3 1.txt"):
#   The original extractors used narrow regexes plus `normalize_phone()`, which:
#     - had NO `074` prefix in its whitelist  -> every 074 number was dropped,
#     - rejected ALL foreign numbers (MK-only whitelist),
#     - could not match dashed/spaced numbers ("071-751-588", "072 240 604"),
#     - only looked at raw HTML, missing <bdi> dropdowns, tel: links and
#       numbers written in the ad body text.
#
# This module fixes that:
#   - `normalize_phone()` returns the canonical MK form for Macedonian mobile
#     numbers, a compact E.164 form for everything else, or None.
#   - `extract_phones()` / `extract_phone_text()` collect candidates from every
#     surface (tel: links, <bdi>, contact buttons, spans, visible page text),
#     de-duplicate them, and return the primary number first.

from __future__ import annotations

import re

# North Macedonia mobile prefixes (national form, leading zero).
MK_MOBILE_PREFIXES = ("070", "071", "072", "073", "074", "075", "076", "077", "078", "079")

# Reasonable E.164 bounds for the digits AFTER the leading '+'.
_INTL_MIN_DIGITS = 8
_INTL_MAX_DIGITS = 15


def _strip_to_digits_plus(value: str) -> str:
    return re.sub(r"[^\d+]", "", value or "")


def _normalize_mk_national(s: str):
    """Canonicalise a Macedonian national number (8 or 9 digits)."""
    if not s or not s.isdigit():
        return None
    if s.startswith("7") and len(s) == 8:
        s = "0" + s
    if len(s) == 9 and s[:3] in MK_MOBILE_PREFIXES:
        return f"+389 {s[:3]} {s[3:6]} {s[6:9]}"
    return None


def _normalize_plus(s: str):
    """Canonicalise a '+'-prefixed number. MK -> canonical, else compact E.164."""
    digits = s[1:]
    if not digits.isdigit():
        return None
    if len(digits) < _INTL_MIN_DIGITS or len(digits) > _INTL_MAX_DIGITS:
        return None
    if digits.startswith("389"):
        canonical = _normalize_mk_national(digits[3:])
        # A +389 number that is not a mobile number we understand is dropped.
        return canonical
    return "+" + digits


def normalize_phone(p):
    """Return the canonical phone, or None if it is not a usable number.

    Macedonian mobile numbers become ``+389 0XX XXX XXX`` (so cross-site dedup
    and the agency blocklist keep working). Foreign numbers are preserved as
    compact E.164, e.g. ``+4917620549606``.
    """
    if p is None:
        return None
    raw = str(p).strip()
    if not raw:
        return None

    cleaned = _strip_to_digits_plus(raw)
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        return _normalize_plus(cleaned)
    if cleaned.startswith("00"):
        return _normalize_plus("+" + cleaned[2:])
    # Bare country code (e.g. "389 78 377 677" -> "38978377677").
    if cleaned.startswith("389") and len(cleaned) >= 11:
        return _normalize_mk_national("0" + cleaned[3:])
    # Bare national form.
    return _normalize_mk_national(cleaned)


def is_foreign(phone) -> bool:
    """True for a normalized number that is not a Macedonian mobile."""
    return bool(phone) and phone.startswith("+") and not phone.startswith("+389")


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

# Macedonian mobile, tolerant of separators, optional country code and the
# 074/079 prefixes. Matches 7XXXXXXXX / 07XXXXXXXX. The lookbehind/ahead stop
# it matching inside a longer digit run.
# NOTE: the lookbehind also rejects a leading '.' or digit, so map
# coordinates such as "42.00863251183686" can never be read as a phone.
_MK_TEXT_RE = re.compile(
    r"(?<![\d\.])"                    # not preceded by a digit or decimal point
    r"(?:00389|\+?389)?"             # optional country code
    r"[\s\-\./]?"                    # optional separator
    r"0?"                            # optional trunk zero
    r"(7[0-9])"                      # mobile prefix
    r"[\s\-\./]?(\d{3})"             # 3 digits
    r"[\s\-\./]?(\d{3})"             # 3 digits
    r"(?!\d)"                        # not followed by a digit
)

# Any '+'- or '00'-prefixed number with separators (foreign).
_INTL_TEXT_RE = re.compile(
    r"(?<![\d\.])"
    r"((?:\+|00)\d(?:[\d\s\-\.\(\)/]{4,17})\d)"
    r"(?!\d)"
)

_TEL_RE = re.compile(r"""href\s*=\s*["']\s*tel:([^"']+)""", re.IGNORECASE)


def _soup(html=None, soup=None):
    if soup is not None:
        return soup
    if not html:
        return None
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "lxml")
    except Exception:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")


def _visible_text(html=None, soup=None) -> str:
    """Page text with <script>/<style> removed (best effort)."""
    if html:
        s = _soup(html=html)
    else:
        s = soup
    if s is None:
        return re.sub(r"<[^>]+>", " ", html or "")
    try:
        for tag in s(["script", "style", "noscript", "template"]):
            tag.decompose()
        return s.get_text(" ")
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")


def extract_phones(html=None, soup=None, site=None, exclude=()) -> list:
    """Return normalized phone numbers found on a page, primary first.

    ``exclude`` is an iterable of normalized/raw numbers to drop (e.g. the
    Pazar3 platform number and agency numbers).
    """
    excluded = set()
    for e in exclude or ():
        normalized = normalize_phone(e)
        excluded.add(normalized or str(e))

    result = []
    seen = set()

    def add(value):
        normalized = normalize_phone(value)
        if not normalized or normalized in seen or normalized in excluded:
            return
        seen.add(normalized)
        result.append(normalized)

    # 1) tel: links (highest confidence)
    for m in _TEL_RE.finditer(html or ""):
        add(m.group(1))

    s = _soup(html=html, soup=soup)

    # 2) structured contact elements: <bdi> dropdowns and contact buttons
    if s is not None:
        try:
            for el in s.select("bdi"):
                add(el.get_text(" "))
            for el in s.select(".main-contact, .secondary-contacts, .secondary-contacts *"):
                add(el.get_text(" "))
        except Exception:
            pass

    # 3) visible text: MK mobile + foreign numbers written in the ad body
    text = _visible_text(html=html, soup=soup)
    for m in _MK_TEXT_RE.finditer(text):
        add(m.group(0))
    for m in _INTL_TEXT_RE.finditer(text):
        add(m.group(1))

    return result


def extract_phone_text(html=None, soup=None, site=None, exclude=(), separator=" | ") -> str:
    """Convenience wrapper returning the DB-ready `contact` string."""
    phones = extract_phones(html=html, soup=soup, site=site, exclude=exclude)
    return separator.join(phones) if phones else ""
