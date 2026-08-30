#!/bin/bash

SESSION="scraper"

echo "Stopping LOCAL scraper on Lenovo..."

tmux kill-session -t "$SESSION" 2>/dev/null || true

pkill -f "python3 -u batch_scraper.py" 2>/dev/null || true
pkill -f "python3 -u serve_ana.py" 2>/dev/null || true

echo "LOCAL scraper stopped."
