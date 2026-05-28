#!/usr/bin/env bash
# =============================================================================
# BigRock Auto-Update Script
# Pulls the latest code from GitHub and restarts the app if anything changed.
# Run by bigrock-update.timer (on boot + every hour).
# =============================================================================
set -euo pipefail

APP_DIR="/home/pi/bigrock-app"
LOG="/home/pi/bigrock-update.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

cd "$APP_DIR"

PREV=$(git rev-parse HEAD 2>/dev/null || echo "UNKNOWN")

if ! git fetch origin main 2>>"$LOG"; then
    log "WARNING: git fetch failed (no internet?). Skipping update."
    exit 0
fi

NEW=$(git rev-parse origin/main)

if [ "$PREV" = "$NEW" ]; then
    log "Already up to date at $PREV. No restart needed."
    exit 0
fi

log "Update available: $PREV -> $NEW"
git reset --hard origin/main

# Reinstall Python deps if requirements.txt changed
if git diff --name-only "$PREV" "$NEW" 2>/dev/null | grep -q "requirements.txt"; then
    log "requirements.txt changed — reinstalling deps..."
    ./venv/bin/pip install -r requirements.txt --quiet
fi

log "Restarting bigrock.service..."
sudo systemctl restart bigrock.service

log "Update complete."
