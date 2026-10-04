#!/bin/bash
# install_browser.sh — bundle a pinned browser INSIDE this scraper folder.
#
# Why: the IMOTI247 stealth scraper otherwise launches whatever Google Chrome is
# installed on the machine (`real_chrome=True`). A Chrome auto-update can then
# change or break the scraper. Bundling keeps a fixed version in ./browsers/,
# which _shared/browser.py auto-detects, so both the Lenovo and the T60 always
# launch the same browser.
#
# Usage:
#   ./install_browser.sh --cft [VERSION]   Chrome for Testing (default: latest stable)
#   ./install_browser.sh --copy-system     copy the installed Google Chrome
#   ./install_browser.sh --playwright      Playwright/patchright Chromium
#   ./install_browser.sh --status          show what would be used
#   ./install_browser.sh --remove          delete the bundled browser
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROWSERS="$ROOT/browsers"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
RESOLVER="$ROOT/_shared/browser.py"

status() {
    if [ -f "$RESOLVER" ]; then
        "$PY" - "$ROOT" <<'PY'
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], "_shared"))
import browser
print(browser.describe(sys.argv[1]))
PY
    else
        echo "resolver not found: $RESOLVER"
    fi
}

do_cft() {
    local ver="${1:-}"
    command -v curl >/dev/null || { echo "curl is required"; exit 1; }
    command -v unzip >/dev/null || { echo "unzip is required"; exit 1; }

    local url
    if [ -n "$ver" ]; then
        url="https://storage.googleapis.com/chrome-for-testing-public/${ver}/linux64/chrome-linux64.zip"
    else
        url=$("$PY" - <<'PY'
import json, urllib.request
endpoint = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
ch = json.load(urllib.request.urlopen(endpoint, timeout=30))["channels"]["Stable"]
for item in ch["downloads"]["chrome"]:
    if item["platform"] == "linux64":
        print(item["url"]); break
PY
)
    fi
    [ -n "$url" ] || { echo "could not resolve a Chrome for Testing URL"; exit 1; }

    mkdir -p "$BROWSERS"
    local zip="$BROWSERS/chrome-linux64.zip"
    echo "Downloading $url"
    curl -fL --retry 3 -o "$zip" "$url" || { echo "download failed"; rm -f "$zip"; exit 1; }
    rm -rf "$BROWSERS/chrome-linux64"
    unzip -q -o "$zip" -d "$BROWSERS" || { echo "unzip failed"; exit 1; }
    rm -f "$zip"
    chmod +x "$BROWSERS/chrome-linux64/chrome" 2>/dev/null || true
    echo "Installed Chrome for Testing into $BROWSERS/chrome-linux64/"
}

do_copy_system() {
    local bin src
    for b in google-chrome-stable google-chrome chromium chromium-browser; do
        bin="$(command -v "$b" 2>/dev/null)" && break
    done
    if [ -z "${bin:-}" ]; then
        echo "No system Chrome/Chromium found on PATH."; exit 1
    fi
    # Follow the wrapper script to the real binary, then take its directory
    # (Chrome needs its .pak/locale resources alongside the binary).
    local real
    real="$(readlink -f "$bin")"
    src="$(dirname "$real")"
    echo "Copying $src  (from $(readlink -f "$bin"))"
    rm -rf "$BROWSERS/chrome"
    mkdir -p "$BROWSERS/chrome"
    cp -a "$src/." "$BROWSERS/chrome/"
    chmod +x "$BROWSERS/chrome/chrome" 2>/dev/null || true
    echo "Copied into $BROWSERS/chrome/"
}

do_playwright() {
    [ -x "$ROOT/.venv/bin/python" ] || { echo ".venv not found; run ./setup.sh first"; exit 1; }
    echo "Installing Chromium into $BROWSERS/ (PLAYWRIGHT_BROWSERS_PATH)"
    PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" "$ROOT/.venv/bin/python" -m playwright install chromium
}

do_remove() {
    rm -rf "$BROWSERS"
    echo "Removed $BROWSERS"
}

case "${1:---status}" in
    --cft)         do_cft "${2:-}" ;;
    --copy-system) do_copy_system ;;
    --playwright)  do_playwright ;;
    --remove)      do_remove ;;
    --status)      status ;;
    *)
        echo "Usage: $0 [--cft [VERSION] | --copy-system | --playwright | --status | --remove]"
        exit 1
        ;;
esac

echo
echo "Current selection:"
status
