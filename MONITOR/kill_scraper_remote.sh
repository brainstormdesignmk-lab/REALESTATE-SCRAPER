#!/bin/bash

REMOTE="t60hermes"
SESSION="scraper"

echo "Stopping REMOTE scraper on T60..."

ssh "$REMOTE" "
tmux kill-session -t '$SESSION' 2>/dev/null || true
pkill -f 'python3 -u batch_scraper.py' 2>/dev/null || true
pkill -f 'python3 -u serve_ana.py' 2>/dev/null || true
"

echo "REMOTE scraper stopped."
