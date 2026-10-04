#!/bin/bash
# Desktop launcher: starts/attaches the REMOTE scraper cycle on the T60.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$(cd "$DIR/.." && pwd)")"
exec /usr/bin/urxvt \
    -title "SCRAPER REMOTE - $PROJECT_NAME" \
    -e /bin/bash "$DIR/start_scraper_remote.sh"
