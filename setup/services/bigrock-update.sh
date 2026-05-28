#!/usr/bin/env bash
# =============================================================================
# BigRock Auto-Update Script
# Pulls the latest code from GitHub, applies version upgrades if needed,
# and restarts the app when Python files change.
# Run by bigrock-update.timer (2 min after boot, then every hour).
# =============================================================================
set -euo pipefail

APP_DIR="/home/pi/bigrock-app"
DEPLOYED_VERSION_FILE="/home/pi/.bigrock-version"
LOG="/home/pi/bigrock-update.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

cd "$APP_DIR"

# ---------------------------------------------------------------------------
# 1. Fetch latest code
# ---------------------------------------------------------------------------
PREV=$(git rev-parse HEAD 2>/dev/null || echo "UNKNOWN")

if ! git fetch origin main 2>>"$LOG"; then
    log "WARNING: git fetch failed (no internet?). Skipping update."
    exit 0
fi

NEW=$(git rev-parse origin/main)

if [ "$PREV" = "$NEW" ]; then
    log "Already up to date at ${PREV:0:7}. No changes."
    exit 0
fi

log "Update: ${PREV:0:7} -> ${NEW:0:7}"
git reset --hard origin/main

# ---------------------------------------------------------------------------
# 2. Version upgrade (runs upgrade.sh as root when setup/VERSION increases)
#    This handles: new apt packages, new service files, sudoers changes, etc.
# ---------------------------------------------------------------------------
DEPLOYED=$(cat "$DEPLOYED_VERSION_FILE" 2>/dev/null || echo "0")
REPO=$(cat "$APP_DIR/setup/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0")

if [ "$DEPLOYED" -lt "$REPO" ]; then
    log "Version upgrade required: $DEPLOYED -> $REPO. Running upgrade script..."
    chmod +x "$APP_DIR/setup/services/bigrock-upgrade.sh"
    sudo bash "$APP_DIR/setup/services/bigrock-upgrade.sh"
    # upgrade.sh writes the new version to $DEPLOYED_VERSION_FILE
fi

# ---------------------------------------------------------------------------
# 3. Python dep refresh (only if requirements.txt changed)
# ---------------------------------------------------------------------------
if git diff --name-only "$PREV" "$NEW" 2>/dev/null | grep -q "requirements.txt"; then
    log "requirements.txt changed — reinstalling Python deps..."
    ./venv/bin/pip install -r requirements.txt --quiet
fi

# ---------------------------------------------------------------------------
# 4. Restart app if any Python or template files changed
# ---------------------------------------------------------------------------
CHANGED=$(git diff --name-only "$PREV" "$NEW" 2>/dev/null || echo "")
if echo "$CHANGED" | grep -qE '\.(py|html|css|js)$'; then
    log "App files changed — restarting bigrock.service..."
    sudo systemctl restart bigrock.service
    log "Service restarted."
else
    log "No app files changed — no restart needed."
fi

log "Update complete."
