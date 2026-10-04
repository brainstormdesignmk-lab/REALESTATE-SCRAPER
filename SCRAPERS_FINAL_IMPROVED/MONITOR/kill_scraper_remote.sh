#!/bin/bash
# Stop the REMOTE scraper run for this variant on the T60.
# Auto-detects the variant folder (sibling or mirrored layout), same as
# start_scraper_remote.sh.
#
# Usage:        ./kill_scraper_remote.sh
# Config check: ./kill_scraper_remote.sh --dry-run

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SESSION="scraper_$(echo "$PROJECT_NAME" | sed 's/^SCRAPERS_FINAL_//' | tr 'A-Z' 'a-z')"

REMOTE="t60hermes"
REMOTE_HOME="/home/metropolis4"
CAND_SIBLING="$REMOTE_HOME/Documents/PROJECTS/$PROJECT_NAME"
CAND_MIRROR="$REMOTE_HOME${PROJECT_DIR#$HOME}"

if [ "${1:-}" = "--dry-run" ]; then
    echo "would kill remote session : $SESSION on $REMOTE"
    echo "would pkill              : <workdir>/.venv/bin/python"
    echo "workdir search           : $CAND_SIBLING"
    echo "                           $CAND_MIRROR"
    exit 0
fi

echo "Stopping REMOTE $PROJECT_NAME scraper on T60..."

ssh "$REMOTE" "
WORKDIR=''
for c in '$CAND_SIBLING' '$CAND_MIRROR'; do
    if [ -d \"\$c\" ]; then WORKDIR=\"\$c\"; break; fi
done

tmux kill-session -t '$SESSION' 2>/dev/null || true
if [ -n \"\$WORKDIR\" ]; then
    pkill -f \"\$WORKDIR/.venv/bin/python\" 2>/dev/null || true
fi
"

echo "REMOTE $PROJECT_NAME scraper stopped."
