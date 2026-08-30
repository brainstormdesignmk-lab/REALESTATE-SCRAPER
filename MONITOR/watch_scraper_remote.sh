#!/bin/bash

REMOTE="t60hermes"
SESSION="scraper"

echo "Connecting to T60 scraper..."

exec ssh -t "$REMOTE" "
if tmux has-session -t '$SESSION' 2>/dev/null; then
    exec tmux attach-session -t '$SESSION'
else
    echo
    echo 'ERROR: No scraper tmux session is running on T60.'
    echo
    echo 'Use START SCRAPER REMOTE to start it.'
    echo
    exec bash
fi
"
