#!/bin/bash
# Launch the scraper cycle LOCALLY (this machine) inside a tmux session.
# Scrapling-variant aware: uses the variant's .venv interpreter and
# auto-detects the entry point (batch_scraper.py or run_spiders.py).
#
# Usage:        ./launch_scraper_local.sh
# Config check: ./launch_scraper_local.sh --dry-run
# Extra args:   SCRAPER_ARGS="--site REKLAMA5 --limit 1" ./launch_scraper_local.sh
# One site only: SITE=REKLAMA5 ./launch_scraper_local.sh   (its own tmux session,
#                so you do not wait for Pazar3/Imoti247 to finish)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"

# Optional single-site run: SITE=PAZAR3|REKLAMA5|IMOTI247
SITE="${SITE:-}"
SITE_TAG=""
[ -n "$SITE" ] && SITE_TAG="_$(echo "$SITE" | tr 'A-Z' 'a-z')"
SESSION="scraper_$(echo "$PROJECT_NAME" | sed 's/^SCRAPERS_FINAL_//' | tr 'A-Z' 'a-z')$SITE_TAG"

if [ -f "$PROJECT_DIR/run_spiders.py" ]; then ENTRY="run_spiders.py"; else ENTRY="batch_scraper.py"; fi
PYBIN=".venv/bin/python"
ARGS="${SCRAPER_ARGS:-}"
# Our batch runner takes --site; the spider runner takes --site too.
[ -n "$SITE" ] && ARGS="${ARGS:+$ARGS }--site $SITE"

if [ "${1:-}" = "--dry-run" ]; then
    echo "project : $PROJECT_DIR"
    echo "session : $SESSION"
    echo "entry   : $PYBIN -u $ENTRY $ARGS"
    exit 0
fi

cd "$PROJECT_DIR" || exit 1
mkdir -p output

if [ ! -x "$PYBIN" ]; then
    echo "ERROR: $PROJECT_DIR/$PYBIN not found. Run ./setup.sh first."
    exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "$PROJECT_NAME is already running (session $SESSION)."
    exec tmux attach-session -t "$SESSION"
fi

echo "Starting $PROJECT_NAME cycle locally..."
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" \
"PYTHONUNBUFFERED=1 $PYBIN -u $ENTRY $ARGS 2>&1 | tee output/batch_log_\$(date +%Y%m%d_%H%M).txt;
BATCH_EXIT=\${PIPESTATUS[0]};
echo;
echo \"BATCH EXIT: \$BATCH_EXIT\";
echo;
if [ \$BATCH_EXIT -eq 0 ]; then
    echo \"Starting serve_ana.py...\";
    PYTHONUNBUFFERED=1 $PYBIN -u serve_ana.py 2>&1 | tee -a output/serve_log.txt;
fi;
echo;
echo \"COMPLETE CYCLE FINISHED\";
exec bash"

exec tmux attach-session -t "$SESSION"
