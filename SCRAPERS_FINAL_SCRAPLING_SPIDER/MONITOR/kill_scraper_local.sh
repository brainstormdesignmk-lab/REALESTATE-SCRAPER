#!/bin/bash
# Stop the LOCAL scraper run for this variant.
# Kills the tmux session AND any venv python started from this project dir
# (covers the batch/spider process and its child scrapers + serve_ana).
#
# Usage: ./kill_scraper_local.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SESSION="scraper_$(echo "$PROJECT_NAME" | sed 's/^SCRAPERS_FINAL_//' | tr 'A-Z' 'a-z')"

if [ "${1:-}" = "--dry-run" ]; then
    echo "would kill session : $SESSION"
    echo "would pkill        : $PROJECT_DIR/.venv/bin/python"
    exit 0
fi

echo "Stopping LOCAL $PROJECT_NAME scraper on $(hostname)..."

tmux kill-session -t "$SESSION" 2>/dev/null || true
pkill -f "$PROJECT_DIR/.venv/bin/python" 2>/dev/null || true

echo "LOCAL $PROJECT_NAME scraper stopped."
