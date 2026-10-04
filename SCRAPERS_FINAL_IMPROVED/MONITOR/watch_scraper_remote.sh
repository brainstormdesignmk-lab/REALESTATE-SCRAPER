#!/bin/bash
# Attach to the running scraper tmux session on the T60 (read/observe).
#
# Usage:        ./watch_scraper_remote.sh
# Config check: ./watch_scraper_remote.sh --dry-run

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SESSION="scraper_$(echo "$PROJECT_NAME" | sed 's/^SCRAPERS_FINAL_//' | tr 'A-Z' 'a-z')"
REMOTE="t60hermes"

if [ "${1:-}" = "--dry-run" ]; then
    echo "remote  : $REMOTE"
    echo "session : $SESSION"
    exit 0
fi

echo "Connecting to T60 scraper ($PROJECT_NAME)..."

exec ssh -t "$REMOTE" "
if tmux has-session -t '$SESSION' 2>/dev/null; then
    exec tmux attach-session -t '$SESSION'
else
    echo
    echo 'ERROR: No $PROJECT_NAME scraper session ($SESSION) running on T60.'
    echo
    echo 'Use START SCRAPER REMOTE to start it.'
    echo
    exec bash
fi
"
