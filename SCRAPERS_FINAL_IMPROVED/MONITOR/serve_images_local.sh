#!/bin/bash
# Serve the processed property images (for the Cloudflare Tunnel to expose).
# Runs in its own tmux session so it keeps serving while you work.
#
# Usage:
#   ./serve_images_local.sh                 # start on 127.0.0.1:8088
#   PORT=8090 ./serve_images_local.sh
#   METROPOLIS_IMAGES_DIR=/data/imgs ./serve_images_local.sh
#   ./serve_images_local.sh --dry-run       # show what would run
#   ./serve_images_local.sh --stop          # stop the server session
#
# Files live under $METROPOLIS_IMAGES_DIR (default: ~/metropolis-images).
# Expose it publicly with ./expose_images_tunnel.sh.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYBIN="$PROJECT_DIR/.venv/bin/python"

PORT="${PORT:-8088}"
HOST="${HOST:-127.0.0.1}"
ROOT="${METROPOLIS_IMAGES_DIR:-$HOME/metropolis-images}"
SESSION="${SESSION:-metropolis_images}"
LOG="$PROJECT_DIR/output/images_server_log.txt"

if [ "${1:-}" = "--stop" ]; then
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    echo "images server stopped (session $SESSION)."
    exit 0
fi

if [ "${1:-}" = "--dry-run" ]; then
    echo "session : $SESSION"
    echo "root    : $ROOT"
    echo "entry   : METROPOLIS_IMAGES_DIR=$ROOT $PYBIN -u serve_images.py --host $HOST --port $PORT"
    exit 0
fi

if [ ! -x "$PYBIN" ]; then
    echo "ERROR: $PYBIN not found. Run ./setup.sh first."
    exit 1
fi

mkdir -p "$ROOT" "$PROJECT_DIR/output"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Images server already running (session $SESSION)."
    exec tmux attach-session -t "$SESSION"
fi

echo "Serving $ROOT on http://$HOST:$PORT  (session $SESSION)"
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" \
"METROPOLIS_IMAGES_DIR='$ROOT' PYTHONUNBUFFERED=1 $PYBIN -u serve_images.py --host '$HOST' --port '$PORT' 2>&1 | tee -a '$LOG';
exec bash"

exec tmux attach-session -t "$SESSION"
