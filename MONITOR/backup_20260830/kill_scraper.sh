#!/bin/bash
echo "Killing scraper on T60..."
echo "========================================"
ssh t60hermes "killall -9 python3 google-chrome chromedriver undetected_chromedriver 2>/dev/null; sleep 2; pgrep -fa 'python3|chrome|chromedriver' | grep -v grep || echo 'ALL DEAD'; free -h"
echo ""
echo "========================================"
echo "Done."
echo "Press any key to close."
read -n 1
