#!/bin/bash

REMOTE="t60hermes"
SESSION="scraper"
WORKDIR="/home/metropolis4/Documents/PROJECTS/SCRAPERS_FINAL"

echo "Connecting to T60..."
echo

ssh -t "$REMOTE" "
cd '$WORKDIR' || exit 1

if tmux has-session -t '$SESSION' 2>/dev/null; then
    echo 'Scraper session already exists.'
else
    echo 'Starting scraper on T60...'

    tmux new-session -d -s '$SESSION' -c '$WORKDIR' \
    'PYTHONUNBUFFERED=1 python3 -u batch_scraper.py 2>&1 | tee output/batch_log_\$(date +%Y%m%d_%H%M).txt;
    BATCH_EXIT=\${PIPESTATUS[0]};
    echo;
    echo \"BATCH EXIT: \$BATCH_EXIT\";
    echo;
    if [ \$BATCH_EXIT -eq 0 ]; then
        echo \"Starting serve_ana.py...\";
        PYTHONUNBUFFERED=1 python3 -u serve_ana.py 2>&1 | tee -a output/serve_log.txt;
    fi;
    echo;
    echo \"COMPLETE CYCLE FINISHED\";
    exec bash'
fi

echo
echo 'Opening T60 scraper tmux...'
exec tmux attach-session -t '$SESSION'
"
