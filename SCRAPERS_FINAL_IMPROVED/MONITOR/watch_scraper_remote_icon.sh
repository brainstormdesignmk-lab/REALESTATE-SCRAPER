#!/bin/bash
# Desktop launcher: watch (attach to) the REMOTE scraper on the T60.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$(cd "$DIR/.." && pwd)")"
exec /usr/bin/urxvt \
    -title "WATCH SCRAPER - $PROJECT_NAME" \
    -e /bin/bash "$DIR/watch_scraper_remote.sh"
