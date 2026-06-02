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
# This script runs as root. Touch + chown the log immediately so the pi user
# can always write to it after we're done (even if we exit early or reboot).
touch "$LOG" 2>/dev/null || true
chown pi:pi "$LOG" 2>/dev/null || true

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
        echo "4" > "$DEPLOYED_VERSION_FILE"
        shutdown -r +1 "BigRock v4 upgrade: rebooting to apply --disk-cache-size=1" || true
        exit 0
        ;;

    5)
        # Playwright install skipped — bundled Node binary requires ARMv8.2+ instructions
        # not available on all hardware. Scraper uses system Chromium as fallback.
        log "v5: Playwright install skipped (not supported on this hardware)."
        ;;

    6)
        # Playwright install skipped — see v5.
        log "v6: Playwright install skipped (not supported on this hardware)."
        ;;

    7)
        # Install emoji font — required for the Enrolled/Today/Watching icons
        # and any emoji in the UI. Missing on clones that were set up before
        # this was added to the system package list in install.sh.
        log "v7: Installing fonts-noto-color-emoji..."
        apt-get install -y -qq fonts-noto-color-emoji \
            && log "v7: Emoji font installed." \
            || log "WARNING: emoji font install failed — check internet."
        ;;

    8)
        # Reboot to apply the emoji font installed in v7. Chromium kiosk must
        # restart to load newly installed system fonts — a service restart alone
        # is not enough because the kiosk process caches fonts at launch.
        log "v8: Scheduling reboot in 1 minute to apply emoji font..."
        fc-cache -f 2>/dev/null || true
        echo "8" > "$DEPLOYED_VERSION_FILE"
        shutdown -r +1 "BigRock v8: rebooting to apply emoji font" || true
        exit 0
        ;;

    9)
        # Install PulseAudio + Bluetooth module and rewrite labwc autostart so
        # PulseAudio starts before Chromium. Required for BT speaker audio routing.
        log "v9: Installing pulseaudio pulseaudio-module-bluetooth..."
        apt-get install -y -qq pulseaudio pulseaudio-module-bluetooth \
            && log "v9: PulseAudio installed." \
            || log "WARNING: pulseaudio install failed — check internet."
        log "v9: Rewriting labwc autostart with PulseAudio startup..."
        AUTOSTART="/home/pi/.config/labwc/autostart"
        mkdir -p /home/pi/.config/labwc
        cat > "$AUTOSTART" << 'AUTOSTART_EOF'
# Hide mouse cursor after 5s of inactivity
unclutter -idle 5 -root &
# Start PulseAudio (with Bluetooth module) before Chromium opens audio device
pulseaudio --start --log-target=syslog &
sleep 1
# Pre-start on-screen keyboard hidden so it holds its Wayland connection before
# Chromium kiosk takes exclusive compositor access. Show/hide via SIGUSR2/SIGUSR1.
wvkbd-mobintl -L 220 --hidden &
sleep 1
# Launch app maximized (not --kiosk) so wvkbd layer-shell renders above it.
# labwc rc.xml strips the title bar via windowRule below.
chromium --start-maximized --ozone-platform=wayland --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble --no-restore-last-session --disk-cache-size=1 --disable-features=WebBluetooth --disable-notifications --app=http://localhost:5000 &
AUTOSTART_EOF
        chmod +x "$AUTOSTART"
        log "v9: autostart rewritten. Scheduling reboot to apply PulseAudio..."
        echo "9" > "$DEPLOYED_VERSION_FILE"
        shutdown -r +1 "BigRock v9: rebooting to start PulseAudio for BT audio" || true
        exit 0
        ;;

    10)
        # Playwright install skipped — see v5.
        log "v10: Playwright install skipped (not supported on this hardware)."
        ;;

    11)
        # Redeploy bigrock-update.service with ExecStartPre chmod lines.
        # This makes the service self-healing against git stripping the execute bit,
        # so it can NEVER get stuck in Permission denied again.
        log "v11: Redeploying bigrock-update.service with ExecStartPre chmod fix..."
        cp "$APP_DIR/setup/services/bigrock-update.service" /etc/systemd/system/bigrock-update.service
        systemctl daemon-reload
        log "v11: bigrock-update.service updated."
        ;;

    12)
        # Switch audio stack from PulseAudio to PipeWire + WirePlumber.
        # Pi OS Bookworm uses PipeWire natively; it handles BT A2DP routing
        # automatically via WirePlumber — no manual pactl/reconcile needed.
        log "v12: Installing PipeWire + WirePlumber + Bluetooth SPA plugin..."
        apt-get remove -y -qq pulseaudio pulseaudio-module-bluetooth 2>/dev/null || true
        apt-get install -y -qq \
            pipewire pipewire-pulse wireplumber \
            libspa-0.2-bluetooth pipewire-audio-client-libraries \
            && log "v12: PipeWire installed." \
            || log "WARNING: PipeWire install failed — check internet."

        log "v12: Rewriting autostart with PipeWire..."
        AUTOSTART="/home/pi/.config/labwc/autostart"
        mkdir -p /home/pi/.config/labwc
        cat > "$AUTOSTART" << 'AUTOSTART_EOF'
# Hide mouse cursor after 5s of inactivity
unclutter -idle 5 -root &
# Start PipeWire audio stack (handles BT A2DP routing automatically)
pipewire &
sleep 0.5
wireplumber &
sleep 0.5
pipewire-pulse &
sleep 1
# Pre-start on-screen keyboard hidden so it holds its Wayland connection before
# Chromium kiosk takes exclusive compositor access. Show/hide via SIGUSR2/SIGUSR1.
wvkbd-mobintl -L 220 --hidden &
sleep 1
# Launch app maximized (not --kiosk) so wvkbd layer-shell renders above it.
# labwc rc.xml strips the title bar via windowRule below.
chromium --start-maximized --ozone-platform=wayland --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble --no-restore-last-session --disk-cache-size=1 --disable-features=WebBluetooth --disable-notifications --app=http://localhost:5000 &
AUTOSTART_EOF
        chmod +x "$AUTOSTART"
        chown pi:pi "$AUTOSTART"
        log "v12: autostart rewritten. Scheduling reboot..."
        echo "12" > "$DEPLOYED_VERSION_FILE"
        shutdown -r +1 "BigRock v12: rebooting to start PipeWire for BT audio" || true
        exit 0
        ;;

    13)
        # Retry PipeWire install after reboot (v12 apt may have failed on first run).
        log "v13: Ensuring PipeWire packages are installed..."
        apt-get install -y -qq \
            pipewire pipewire-pulse wireplumber \
            libspa-0.2-bluetooth pipewire-audio-client-libraries \
            && log "v13: PipeWire packages confirmed." \
            || log "WARNING: PipeWire install still failing — will retry next cycle."
        ;;

    14)
        # Redeploy bigrock-update.service with the + prefix on ExecStartPre chown.
        # Without it, the chown runs as pi (User=pi) and cannot fix a root-owned log
        # file, so the service fails with Permission denied after every upgrade run.
        log "v14: Redeploying bigrock-update.service with root-chown ExecStartPre fix..."
        cp "$APP_DIR/setup/services/bigrock-update.service" /etc/systemd/system/bigrock-update.service
        systemctl daemon-reload
        log "v14: bigrock-update.service updated."
        ;;

    15)
        # Fix silent audio failure introduced in v12.
        # v12 rewrote autostart to manually start pipewire, wireplumber, and
        # pipewire-pulse as background processes. On Bookworm, systemd user services
        # also manage these via socket activation — the two instances compete for the
        # same sockets, leaving Chromium with no audio sink (no BT, no HDMI).
        # Fix: remove manual starts from autostart; let systemd own the lifecycle.
        log "v15: Rewriting autostart to remove conflicting PipeWire manual starts..."
        AUTOSTART="/home/pi/.config/labwc/autostart"
        mkdir -p /home/pi/.config/labwc
        cat > "$AUTOSTART" << 'AUTOSTART_EOF'
# Hide mouse cursor after 5s of inactivity
unclutter -idle 5 -root &
# PipeWire (pipewire, wireplumber, pipewire-pulse) is managed by systemd user
# services via socket activation on Bookworm — do NOT start them here.
# Starting them manually creates duplicate instances that fight over the sockets,
# leaving Chromium with no audio sink. Give systemd 2s to activate them.
sleep 2
# Pre-start on-screen keyboard hidden so it holds its Wayland connection before
# Chromium kiosk takes exclusive compositor access. Show/hide via SIGUSR2/SIGUSR1.
wvkbd-mobintl -L 220 --hidden &
sleep 1
# Launch app maximized (not --kiosk) so wvkbd layer-shell renders above it.
# labwc rc.xml strips the title bar via windowRule below.
chromium --start-maximized --ozone-platform=wayland --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble --no-restore-last-session --disk-cache-size=1 --disable-features=WebBluetooth --disable-notifications --app=http://localhost:5000 &
AUTOSTART_EOF
        chmod +x "$AUTOSTART"
        chown pi:pi "$AUTOSTART"
        log "v15: autostart rewritten. Scheduling reboot to apply..."
        echo "15" > "$DEPLOYED_VERSION_FILE"
        shutdown -r +1 "BigRock v15: rebooting to apply audio fix (remove duplicate PipeWire)" || true
        exit 0
        ;;

    # ---------------------------------------------------------------------------
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

    # Save progress after each step so reboots mid-chain resume from the right step
    echo "$V" > "$DEPLOYED_VERSION_FILE"
    log "--- Step $V complete ---"
done

log "Upgrade complete. Deployed version is now $REPO."
# Return log ownership to pi — upgrade.sh runs as root and tee-writes to the
# log throughout. Without this chown, the next update run (as pi) gets
# "Permission denied" and fails before writing a single line.
chown pi:pi "$LOG" 2>/dev/null || true
