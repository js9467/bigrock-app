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

# Optional branch override: echo "dev" > /home/pi/.bigrock-branch to track dev
BRANCH_OVERRIDE_FILE="/home/pi/.bigrock-branch"
TARGET_BRANCH=$(cat "$BRANCH_OVERRIDE_FILE" 2>/dev/null | tr -d '[:space:]' || echo "main")

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

cd "$APP_DIR"

# ---------------------------------------------------------------------------
# 1. Fetch latest code
# ---------------------------------------------------------------------------
PREV=$(git rev-parse HEAD 2>/dev/null || echo "UNKNOWN")

if ! git fetch origin "$TARGET_BRANCH" 2>>"$LOG"; then
    log "WARNING: git fetch failed (no internet?). Skipping update."
    exit 0
fi

NEW=$(git rev-parse "origin/$TARGET_BRANCH")

if [ "$PREV" = "$NEW" ]; then
    log "Already up to date at ${PREV:0:7}. No changes."
    exit 0
fi

log "Update: ${PREV:0:7} -> ${NEW:0:7} (branch: $TARGET_BRANCH)"
git reset --hard "origin/$TARGET_BRANCH"

# ---------------------------------------------------------------------------
# 1b. Ensure bundled JS assets are present (local copies avoid CDN failures on boot)
# ---------------------------------------------------------------------------
JS_DIR="$APP_DIR/static/js"
ensure_js() {
    local file="$1" url="$2"
    [ -s "$JS_DIR/$file" ] && return
    log "Downloading missing JS asset: $file"
    curl -sL --retry 3 --retry-delay 2 "$url" -o "$JS_DIR/$file" || log "WARNING: failed to download $file"
}
ensure_js "vue.global.prod.js"  "https://cdn.jsdelivr.net/npm/vue@3.4.15/dist/vue.global.prod.js"
ensure_js "hls.min.js"          "https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js"
ensure_js "tailwind.cdn.js"     "https://cdn.tailwindcss.com"
ensure_js "chart.min.js"        "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"

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
# 3. Python dep refresh (always — ensures deps are present after any failure)
# ---------------------------------------------------------------------------
log "Ensuring Python deps are installed..."
./venv/bin/pip install -r requirements.txt --quiet 2>&1 | grep -v 'already satisfied' | tee -a "$LOG" || log "WARNING: pip install failed."

# ---------------------------------------------------------------------------
# 3b. Playwright browser (always — install is a no-op if already present)
# ---------------------------------------------------------------------------
if ! ./venv/bin/python3 -c 'from playwright.sync_api import sync_playwright; sync_playwright().__enter__().chromium.executable_path' &>/dev/null; then
    log "Playwright browser missing — installing..."
    su -c "cd '$APP_DIR' && ./venv/bin/python3 -m playwright install chromium" pi \
        && log "Playwright browser installed." \
        || log "WARNING: playwright install failed — will retry next cycle."
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
