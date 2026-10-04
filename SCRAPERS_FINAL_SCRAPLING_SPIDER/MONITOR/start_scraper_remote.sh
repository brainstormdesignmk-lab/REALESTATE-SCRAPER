#!/bin/bash
# Start the scraper cycle on the T60 (remote) inside a tmux session, then attach.
# Scrapling-variant aware: uses the variant's .venv on the remote and
# auto-detects the entry point (batch_scraper.py or run_spiders.py).
# The remote folder is found automatically whether it sits next to
# SCRAPERS_FINAL (sibling) or mirrors this machine's relative path.
#
# Usage:        ./start_scraper_remote.sh
# Config check: ./start_scraper_remote.sh --dry-run

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SESSION="scraper_$(echo "$PROJECT_NAME" | sed 's/^SCRAPERS_FINAL_//' | tr 'A-Z' 'a-z')"

if [ -f "$PROJECT_DIR/run_spiders.py" ]; then ENTRY="run_spiders.py"; else ENTRY="batch_scraper.py"; fi
PYBIN=".venv/bin/python"
ARGS="${SCRAPER_ARGS:-}"

REMOTE="t60hermes"
REMOTE_HOME="/home/metropolis4"
# Candidate remote locations, checked in order:
#   1) sibling layout   ~/Documents/PROJECTS/<variant>          (T60 default)
#   2) mirrored layout  same relative path as on this machine
CAND_SIBLING="$REMOTE_HOME/Documents/PROJECTS/$PROJECT_NAME"
CAND_MIRROR="$REMOTE_HOME${PROJECT_DIR#$HOME}"

if [ "${1:-}" = "--dry-run" ]; then
    echo "remote  : $REMOTE"
    echo "workdir : $CAND_SIBLING"
    echo "fallback: $CAND_MIRROR"
    echo "session : $SESSION"
    echo "entry   : $PYBIN -u $ENTRY $ARGS"
    exit 0
fi

echo "Connecting to T60..."
echo

ssh -t "$REMOTE" "
WORKDIR=''
for c in '$CAND_SIBLING' '$CAND_MIRROR'; do
    if [ -d \"\$c\" ]; then WORKDIR=\"\$c\"; break; fi
done
if [ -z \"\$WORKDIR\" ]; then
    echo 'ERROR: cannot locate $PROJECT_NAME on the T60. Deploy it with setup.sh first.'
    exec bash
fi

cd \"\$WORKDIR\" || exit 1
mkdir -p output

if [ ! -x '$PYBIN' ]; then
    echo \"ERROR: \$WORKDIR/$PYBIN not found. Run ./setup.sh on the T60.\"
    exec bash
fi

if tmux has-session -t '$SESSION' 2>/dev/null; then
    echo 'Scraper session ($SESSION) already exists.'
else
    echo \"Starting $PROJECT_NAME on T60 (in \$WORKDIR)...\"
    tmux new-session -d -s '$SESSION' -c \"\$WORKDIR\" \
    'PYTHONUNBUFFERED=1 $PYBIN -u $ENTRY $ARGS 2>&1 | tee output/batch_log_\$(date +%Y%m%d_%H%M).txt;
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
    exec bash'
fi

echo
echo 'Opening $PROJECT_NAME tmux...'
exec tmux attach-session -t '$SESSION'
"
