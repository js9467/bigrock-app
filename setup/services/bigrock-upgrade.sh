#!/usr/bin/env bash
# =============================================================================
# BigRock App — Version Upgrade Script
# =============================================================================
# Called automatically by bigrock-update.sh when setup/VERSION has increased.
# Runs as ROOT (via sudo) so it can install packages and update service files.
#
# HOW TO USE (for developers):
#   1. Make your breaking change (new apt dep, new service, new sudoers rule)
#   2. Update setup/VERSION by incrementing the integer by 1
#   3. Add the corresponding upgrade steps in the appropriate VERSION block below
#   4. Commit and push — all live Pis upgrade themselves within 1 hour
# =============================================================================
set -euo pipefail

APP_DIR="/home/pi/bigrock-app"
DEPLOYED_VERSION_FILE="/home/pi/.bigrock-version"
REPO_VERSION_FILE="$APP_DIR/setup/VERSION"
LOG="/home/pi/bigrock-update.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [upgrade] $*" | tee -a "$LOG"; }

DEPLOYED=$(cat "$DEPLOYED_VERSION_FILE" 2>/dev/null || echo "0")
REPO=$(cat "$REPO_VERSION_FILE" 2>/dev/null | tr -d '[:space:]' || echo "0")

if [ "$DEPLOYED" -ge "$REPO" ]; then
    log "Already at version $DEPLOYED — no upgrade needed."
    exit 0
fi

log "Upgrading from version $DEPLOYED to $REPO..."

# Run every version step from (deployed+1) up to repo version in order
for V in $(seq $((DEPLOYED + 1)) "$REPO"); do
    log "--- Applying upgrade step $V ---"

    case $V in

    1)
        # Initial full install — runs install.sh as pi user
        log "v1: Running full install..."
        chmod +x "$APP_DIR/setup/install.sh"
        su -c "bash $APP_DIR/setup/install.sh" pi
        ;;

    2)
        # Patch Chromium autostart to add --no-restore-last-session
        # Prevents crash-recovery mode after unclean shutdown (e.g. power loss)
        log "v2: Patching labwc autostart to add --no-restore-last-session..."
        AUTOSTART="/home/pi/.config/labwc/autostart"
        if grep -q 'disable-session-crashed-bubble' "$AUTOSTART" && ! grep -q 'no-restore-last-session' "$AUTOSTART"; then
            sed -i 's/--disable-session-crashed-bubble/--disable-session-crashed-bubble --no-restore-last-session/' "$AUTOSTART"
            log "v2: autostart patched."
        else
            log "v2: autostart already up to date — skipping."
        fi
        ;;

    3)
        # Ensure local copies of bundled JS assets exist (fixes CDN-failure white screen on boot)
        log "v3: Ensuring local JS assets exist in static/js/..."
        JS_DIR="$APP_DIR/static/js"
        ensure_js() {
            local file="$1" url="$2"
            [ -s "$JS_DIR/$file" ] && return
            log "v3: Downloading $file..."
            curl -sL --retry 3 --retry-delay 2 "$url" -o "$JS_DIR/$file" \
                && log "v3: $file downloaded." \
                || log "WARNING: failed to download $file"
        }
        ensure_js "vue.global.prod.js" "https://cdn.jsdelivr.net/npm/vue@3.4.15/dist/vue.global.prod.js"
        ensure_js "hls.min.js"         "https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js"
        ensure_js "tailwind.cdn.js"    "https://cdn.tailwindcss.com"
        ;;

    4)
        # Disable Chromium HTTP disk cache to prevent stale CSS/JS on boot.
        # Root cause of the "white screen / no Tailwind" bug: Chromium's disk cache
        # was serving a stale tailwind.cdn.js or index.html from a previous session.
        # --disk-cache-size=1 limits the cache to 1 byte (effectively disables it).
        # The service worker handles offline caching for static assets instead.
        log "v4: Rewriting labwc autostart with --disk-cache-size=1 flag..."
        AUTOSTART="/home/pi/.config/labwc/autostart"
        mkdir -p /home/pi/.config/labwc
        cat > "$AUTOSTART" << 'AUTOSTART_EOF'
# Hide mouse cursor after 5s of inactivity
unclutter -idle 5 -root &
# Pre-start on-screen keyboard hidden so it holds its Wayland connection before
# Chromium kiosk takes exclusive compositor access. Show/hide via SIGUSR2/SIGUSR1.
wvkbd-mobintl -L 220 --hidden &
sleep 1
# Launch app maximized. --disk-cache-size=1 disables the HTTP disk cache so
# Chromium never serves stale CSS/JS from a previous session.
chromium --start-maximized --ozone-platform=wayland --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble --no-restore-last-session --disk-cache-size=1 --disable-features=WebBluetooth --disable-notifications --app=http://localhost:5000 &
AUTOSTART_EOF
        chmod +x "$AUTOSTART"
        # Also clear any existing Chromium disk cache right now
        rm -rf /home/pi/.cache/chromium \
               /home/pi/.config/chromium/Default/Cache \
               "/home/pi/.config/chromium/Default/Code Cache" \
               2>/dev/null || true
        log "v4: autostart rewritten and Chromium cache cleared."
        # Schedule a reboot so new Chromium flags take effect (1 minute from now)
        log "v4: Scheduling reboot in 1 minute to apply new Chromium flags..."
        shutdown -r +1 "BigRock v4 upgrade: rebooting to apply --disk-cache-size=1" || true
        ;;

    5)
        # Install Playwright's bundled Chromium headless shell so the scraper can
        # render JavaScript-heavy pages (e.g. reeltime.app). Without this, scrapes
        # fall back to plain HTTP and only get raw nav/DOM text.
        log "v5: Installing Playwright Chromium headless shell..."
        PLAYWRIGHT_BROWSERS_PATH="/home/pi/.cache/ms-playwright"
        export PLAYWRIGHT_BROWSERS_PATH
        su -c "/home/pi/bigrock-app/venv/bin/python3 -m playwright install chromium" pi \
            && log "v5: Playwright Chromium installed." \
            || log "WARNING: playwright install failed — will retry next update cycle."
        ;;

    6)
        # Retry Playwright Chromium install. v5 may have failed silently if there was no
        # internet at upgrade time. This step retries unconditionally.
        log "v6: Retrying Playwright Chromium install..."
        su -c "/home/pi/bigrock-app/venv/bin/python3 -m playwright install chromium" pi \
            && log "v6: Playwright Chromium installed successfully." \
            || { log "WARNING: playwright install failed again. Check internet and retry by bumping VERSION."; true; }
        ;;

    # ---------------------------------------------------------------------------
    # TEMPLATE for future upgrades — copy this block and increment the number:
    #
    # 2)
    #     log "v2: Install new apt package / update service file / etc."
    #     apt-get install -y -qq some-new-package
    #     cp "$APP_DIR/setup/services/some-new.service" /etc/systemd/system/
    #     systemctl daemon-reload
    #     systemctl enable some-new.service
    #     ;;
    # ---------------------------------------------------------------------------

    *)
        log "WARNING: No upgrade steps defined for version $V — skipping."
        ;;
    esac

    log "--- Step $V complete ---"
done

# Write the new deployed version
echo "$REPO" > "$DEPLOYED_VERSION_FILE"
log "Upgrade complete. Deployed version is now $REPO."
