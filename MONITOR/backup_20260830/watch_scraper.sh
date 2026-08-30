#!/bin/bash

REMOTE="t60hermes"
SESSION="scraper"

exec /usr/bin/urxvt -title "WATCH SCRAPER T60" -e /bin/bash -c "
ssh -t $REMOTE 'tmux attach-session -t $SESSION'
"
