#!/bin/bash
# Expose the local image server through a Cloudflare Tunnel.
#
# Two modes:
#   --quick            zero-account tunnel (random *.trycloudflare.com URL). Good
#                      for testing; the URL changes every restart.
#   --name <tunnel>    a named, stable tunnel you created with `cloudflared tunnel
#                      login` + `cloudflared tunnel create` (needs a Cloudflare
#                      account + a domain). This is the production setup.
#
# Usage:
#   ./expose_images_tunnel.sh --quick
#   ./expose_images_tunnel.sh --name metropolis-images
#   PORT=8088 ./expose_images_tunnel.sh --name metropolis-images
#   ./expose_images_tunnel.sh --dry-run --quick
#   ./expose_images_tunnel.sh --stop
#
# The image server itself is started by ./serve_images_local.sh.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
PORT="${PORT:-8088}"
SESSION="${SESSION:-metropolis_tunnel}"
LOG="$PROJECT_DIR/output/tunnel_log.txt"

MODE="quick"
NAME=""
while [ $# -gt 0 ]; do
    case "$1" in
        --quick) MODE="quick" ;;
        --name) MODE="named"; NAME="${2:-}"; shift ;;
        --stop) MODE="stop" ;;
        --dry-run) MODE="dry-run" ;;
        *) echo "unknown arg: $1"; exit 2 ;;
    esac
    shift
done

if [ "$MODE" = "stop" ]; then
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    echo "tunnel stopped (session $SESSION)."
    exit 0
fi

[ -x "$CLOUDFLARED" ] || { echo "ERROR: cloudflared not found at $CLOUDFLARED"; exit 1; }

if [ "$MODE" = "quick" ]; then
    CMD="$CLOUDFLARED tunnel --no-autoupdate --url http://127.0.0.1:$PORT"
elif [ "$MODE" = "named" ]; then
    [ -n "$NAME" ] || { echo "ERROR: --name needs a tunnel name"; exit 2; }
    CMD="$CLOUDFLARED tunnel --no-autoupdate run $NAME"
else
    echo "session : $SESSION"
    echo "mode    : $MODE"
    echo "local   : http://127.0.0.1:$PORT"
    [ "$MODE" = "named" ] && echo "tunnel  : $NAME"
    echo "entry   : $CLOUDFLARED tunnel ..."
    exit 0
fi

mkdir -p "$PROJECT_DIR/output"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Tunnel already running (session $SESSION)."
    exec tmux attach-session -t "$SESSION"
fi

echo "Starting Cloudflare tunnel ($MODE) for http://127.0.0.1:$PORT ..."
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" \
"$CMD 2>&1 | tee -a '$LOG';
exec bash"

if [ "$MODE" = "quick" ]; then
    echo "Waiting for the public URL..."
    for _ in $(seq 1 20); do
        url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)"
        [ -n "$url" ] && { echo "Public URL: $url"; break; }
        sleep 1
    done
fi

exec tmux attach-session -t "$SESSION"
