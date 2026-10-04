# _shared/scrapling_fetch.py
# Shared fetch layer built on Scrapling, used by all three base scrapers.
#
# Why this exists:
#   - Reklama5 blocks plain requests/curl with HTTP 403 based on the TLS/JA3
#     fingerprint. Scrapling's `Fetcher` uses curl_cffi under the hood and
#     `impersonate="chrome"` makes us look like a real Chrome browser.
#   - Imoti247 is a JS-heavy site; Scrapling's `StealthySession` (patchright)
#     replaces the fragile Selenium/undetected-chromedriver stack.
#
# Scrapling is imported lazily so that this module (and the health check) can be
# imported on a machine where Scrapling is not installed yet. The actual fetch
# calls raise a clear, actionable error in that case.

from __future__ import annotations

import os
import random
import shutil
import time
from contextlib import contextmanager
from typing import Any, Optional

__all__ = [
    "ScraplingUnavailable",
    "http_session",
    "http_get",
    "stealth_session",
    "open_session",
    "robust_get",
    "robust_fetch",
    "status_of",
    "html_of",
    "chrome_available",
    "default_real_chrome",
    "polite_sleep",
    "IMPERSONATE",
]


def chrome_available() -> bool:
    """True if a system Chrome/Chromium binary is on PATH."""
    return any(shutil.which(b) for b in
               ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"))


def default_real_chrome() -> bool:
    """Use the installed system Chrome by default when present.

    This avoids downloading a bundled browser and reuses the system Chrome that
    already has its shared libraries satisfied (important on old machines with
    no root access). Override with SCRAPING_REAL_CHROME=0/1.
    """
    env = os.environ.get("SCRAPING_REAL_CHROME")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "no", "off")
    return chrome_available()

# Statuses that indicate we were throttled/challenged and should back off and
# retry. Scrapling's own `retries` only covers transport errors, NOT 5xx status
# codes, so a 503 is returned as-is unless we retry it ourselves.
RETRY_STATUS = (403, 429, 500, 502, 503, 504)

# Which browser fingerprint to mimic. "chrome" tracks the latest available
# Chrome version in curl_cffi. Set SCRAPING_IMPERSONATE to override, e.g.
# "chrome110" or "firefox" if a site starts blocking the default.
IMPERSONATE = os.environ.get("SCRAPING_IMPERSONATE", "chrome")


class ScraplingUnavailable(RuntimeError):
    """Raised when Scrapling (or its fetchers extra) is not installed."""


def _require_scrapling() -> None:
    try:
        import scrapling  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on host env
        raise ScraplingUnavailable(
            "Scrapling is not installed for this interpreter.\n"
            "  Install it with:  pip install -r requirements.txt\n"
            "  then (for Imoti247):  scrapling install\n"
            "  Or run through the venv:  ./setup.sh && .venv/bin/python ...\n"
            f"  (underlying import error: {exc})"
        ) from exc


def http_session(
    impersonate: Optional[str] = None,
    retries: int = 3,
    timeout: float = 30.0,
    follow_redirects: str = "safe",
    proxy: Optional[str] = None,
    **extra: Any,
):
    """Create a persistent Scrapling HTTP session (curl_cffi backed).

    Returns a `FetcherSession` usable as a context manager, with `.get()` /
    `.post()` methods. Cookies are kept across requests within the session.

    All parameters are documented Scrapling `RequestsSession` fields; `extra`
    is forwarded for advanced options (headers, http3, verify, ...).
    """
    _require_scrapling()
    from scrapling.fetchers import FetcherSession

    kwargs: dict[str, Any] = {
        "impersonate": impersonate or IMPERSONATE,
        "stealthy_headers": True,
        "retries": retries,
        "timeout": timeout,
        "follow_redirects": follow_redirects,
    }
    if proxy:
        kwargs["proxy"] = proxy
    kwargs.update(extra)
    return FetcherSession(**kwargs)


def http_get(url: str, **kwargs: Any):
    """One-off HTTP GET through Scrapling (TLS impersonation, auto retries).

    Useful for small side requests such as Imoti247's phone AJAX endpoint.
    """
    _require_scrapling()
    from scrapling.fetchers import Fetcher

    kwargs.setdefault("impersonate", IMPERSONATE)
    kwargs.setdefault("stealthy_headers", True)
    kwargs.setdefault("retries", 3)
    kwargs.setdefault("timeout", 30.0)
    return Fetcher.get(url, **kwargs)


def stealth_session(
    headless: bool = True,
    network_idle: bool = True,
    timeout: int = 60000,
    solve_cloudflare: bool = False,
    disable_resources: bool = False,
    retries: int = 2,
    **extra: Any,
):
    """Create a Scrapling stealth browser session (patchright/Chromium).

    Tuned for a low-RAM target (IBM Core 2 Duo / 3 GB): keep ONE session open
    and reuse it for every page instead of starting a browser per request.

    `timeout` is in milliseconds (Scrapling convention). `solve_cloudflare`
    forces a >= 60s timeout internally when enabled.
    """
    _require_scrapling()
    from scrapling.fetchers import StealthySession

    kwargs: dict[str, Any] = {
        "headless": headless,
        "network_idle": network_idle,
        "timeout": timeout,
        "solve_cloudflare": solve_cloudflare,
        "disable_resources": disable_resources,
        "retries": retries,
    }
    # Prefer the installed system Chrome (no browser download needed).
    kwargs.setdefault("real_chrome", default_real_chrome())
    kwargs.update(extra)
    return StealthySession(**kwargs)


def status_of(resp) -> int:
    """HTTP status from a Scrapling Response (tolerates either attribute name)."""
    return getattr(resp, "status", None) or getattr(resp, "status_code", 0)


def html_of(resp) -> str:
    """Raw HTML/text of a Scrapling Response.

    IMPORTANT: `Response` subclasses the parser `Selector`, so `resp.text` is the
    *element text* (empty at the document root), NOT the page HTML. The HTML
    lives in `.html_content`. Always use this helper, never `resp.text`, when
    you want the page source.
    """
    return getattr(resp, "html_content", None) or ""


def _retry_loop(do_request, target, attempts, base_delay, factor, max_delay):
    last = None
    for i in range(attempts):
        try:
            resp = do_request()
            last = resp
            status = status_of(resp)
            if status not in RETRY_STATUS:
                return resp
            print(f"  [retry {i + 1}/{attempts}] HTTP {status} -> backing off")
        except Exception as e:
            print(f"  [retry {i + 1}/{attempts}] {type(e).__name__}: {e}")
        if i < attempts - 1:
            time.sleep(min(max_delay, base_delay * (factor ** i)))
    return last


def robust_get(session, url, attempts: int = 4, base_delay: float = 3.0,
               factor: float = 2.0, max_delay: float = 30.0, **kwargs):
    """`session.get(url)` with explicit retry/backoff on throttle statuses.

    Returns the last Response (which may still be a 5xx if every attempt
    failed) so the caller can inspect and report it.
    """
    return _retry_loop(lambda: session.get(url, **kwargs), url, attempts,
                       base_delay, factor, max_delay)


def robust_fetch(session, url, attempts: int = 4, base_delay: float = 3.0,
                 factor: float = 2.0, max_delay: float = 30.0, **kwargs):
    """`session.fetch(url)` (browser session) with retry/backoff on throttling."""
    return _retry_loop(lambda: session.fetch(url, **kwargs), url, attempts,
                       base_delay, factor, max_delay)


@contextmanager
def open_session(factory, **kwargs):
    """Context-manage any Scrapling session, guaranteeing cleanup.

    Scrapling sessions are context managers, but wrapping here keeps the
    scrapers' control flow simple and ensures the browser/socket is always
    released even if scraping raises.
    """
    session = factory(**kwargs)
    try:
        with session:
            yield session
    finally:
        # `with session:` already closes; this is a belt-and-braces guard.
        try:
            session.close()
        except Exception:
            pass


def polite_sleep(low: float = 1.5, high: float = 3.0) -> None:
    """Randomized human-like delay between requests."""
    time.sleep(random.uniform(low, high))
