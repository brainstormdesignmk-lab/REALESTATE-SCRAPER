# _shared/browser.py
# Locate a browser bundled INSIDE the project folder, so the stealth sessions
# (IMOTI247) always launch the same pinned browser instead of whatever Chrome
# happens to be installed on the machine.
#
# A bundled browser is picked up from  <project>/browsers/  in any of these
# layouts (first match wins):
#
#   browsers/chrome-linux64/chrome   Chrome for Testing  (install_browser.sh --cft)
#   browsers/chrome/chrome           copied /opt/google/chrome (--copy-system)
#   browsers/chrome-linux/chrome     Playwright/patchright Chromium (--playwright)
#
# Set SCRAPING_BROWSER_PATH to an explicit executable to override the search.
# When nothing is bundled we return {} so the caller falls back to the
# machine's Chrome (real_chrome=True) exactly as before.

from __future__ import annotations

import glob
import os

# Layouts relative to the project root (first match wins).
_LAYOUTS = (
    os.path.join("browsers", "chrome-linux64", "chrome"),  # Chrome for Testing
    os.path.join("browsers", "chrome", "chrome"),          # copied system Chrome
    os.path.join("browsers", "chrome-linux", "chrome"),    # playwright chromium
)

# Globs for the Playwright/patchright cache layout, which nests a revision dir:
#   browsers/chromium-1234/chrome-linux/chrome
_GLOBS = (
    os.path.join("browsers", "chromium-*", "chrome-linux", "chrome"),
    os.path.join("browsers", "chromium-*", "chrome-linux64", "chrome"),
)


def project_dir() -> str:
    """Project root: this file lives in <project>/_shared/browser.py."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled_browser_path(root: str | None = None) -> str | None:
    """Absolute path to the bundled browser executable, or None."""
    override = os.environ.get("SCRAPING_BROWSER_PATH")
    if override:
        return override if os.path.isfile(override) else None

    root = root or project_dir()
    for rel in _LAYOUTS:
        path = os.path.join(root, rel)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    for pattern in _GLOBS:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def browser_launch_kwargs(root: str | None = None) -> dict:
    """Extra stealth-session kwargs for the bundled browser (empty if none).

    `real_chrome` is set from the layout: Chrome for Testing and a copied
    Google Chrome are real Chrome builds (match Chrome's UA), whereas a
    Playwright Chromium build is not.
    """
    path = bundled_browser_path(root)
    if not path:
        return {}
    normalised = path.replace(os.sep, "/")
    is_playwright_chromium = "/chrome-linux/" in normalised
    return {"executable_path": path, "real_chrome": not is_playwright_chromium}


def describe(root: str | None = None) -> str:
    """Human-readable status for healthcheck output."""
    path = bundled_browser_path(root)
    if path:
        return f"bundled browser: {path}"
    return "bundled browser: none (falling back to installed Chrome)"
