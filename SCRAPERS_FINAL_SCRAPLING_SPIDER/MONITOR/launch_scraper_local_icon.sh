#!/bin/bash
# Desktop launcher: opens a terminal running the LOCAL scraper cycle.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$(cd "$DIR/.." && pwd)")"
exec /usr/bin/urxvt \
    -title "LOCAL SCRAPER - $PROJECT_NAME" \
    -e /bin/bash "$DIR/launch_scraper_local.sh"
