#!/usr/bin/env bash
# setup.sh — create the Scrapling venv for SCRAPERS_FINAL_SCRAPLING_SPIDER
#
#   ./setup.sh                  # venv + Python deps
#   ./setup.sh --with-browser   # also bundle Chrome for Testing in ./browsers
#
# Scrapling needs Python >= 3.10.

set -euo pipefail
cd "$(dirname "$0")"

WANT_BROWSER=0
[ "${1:-}" = "--with-browser" ] && WANT_BROWSER=1

PY=""
for c in python3.13 python3.12 python3.11 python3.10; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

# Fall back to a user-local standalone Python (e.g. installed without root)
if [ -z "$PY" ]; then
  for c in "$HOME"/.local/python*/python/bin/python3.1[0-9]; do
    [ -x "$c" ] && { PY="$c"; break; }
  done
fi

if [ -z "$PY" ]; then
  echo "ERROR: no Python >= 3.10 found. Install one, e.g.:"
  echo "  sudo apt install python3.11 python3.11-venv"
  exit 1
fi

echo "Using interpreter: $($PY --version) ($PY)"
"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

if [ "$WANT_BROWSER" -eq 1 ]; then
  echo "Bundling Chrome for Testing for IMOTI247 (this needs disk + time)..."
  ./install_browser.sh --cft
fi

echo
echo "Browser in use for IMOTI247:"
./install_browser.sh --status || true

echo
echo "Smoke test:"
echo "  .venv/bin/python run_spiders.py --dry-run"
echo "  .venv/bin/python run_spiders.py --site REKLAMA5 --limit 1"
echo
echo "Full run:"
echo "  .venv/bin/python run_spiders.py"
