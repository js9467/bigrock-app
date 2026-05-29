#!/bin/bash
# =============================================================================
# BigRock Sysprep - Prepare master Pi for SD card cloning
# =============================================================================
# Run this ONCE on the fully-configured "master" Pi before imaging the card.
# After this script runs the Pi powers off. Move the card to your Windows PC
# and run "Create Image.bat" to save a distributable .img.gz file.
#
# Usage:
#   ssh pi@<ip>
#   sudo bash /home/pi/bigrock-app/setup/sysprep.sh
# =============================================================================
set -euo pipefail

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: Run as root:  sudo bash sysprep.sh"
    exit 1
fi

APP_DIR="/home/pi/bigrock-app"

# =============================================================================
# PRE-FLIGHT: Abort if master Pi isn't fully healthy
# =============================================================================
echo ""
echo "--- Pre-flight checks ---"
PREFLIGHT_FAIL=0

# 1. bigrock Flask app must be active
if ! systemctl is-active --quiet bigrock; then
    echo "FAIL: 'bigrock' service is not running. Start it and verify the app before imaging."
    PREFLIGHT_FAIL=1
else
    echo "OK:   bigrock service is active"
fi

# 2. App must respond on HTTP
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:5000 || true)
if [ "$HTTP_CODE" != "200" ]; then
    echo "FAIL: Flask app did not return HTTP 200 (got '$HTTP_CODE'). Fix the app before imaging."
    PREFLIGHT_FAIL=1
else
    echo "OK:   Flask app returned HTTP 200"
fi

# 3. Actions runner must be active
RUNNER_SVC=$(systemctl list-units --type=service --state=active --no-legend 2>/dev/null | grep -o 'actions\.runner\.[^ ]*' | head -1 || true)
if [ -z "$RUNNER_SVC" ]; then
    echo "FAIL: GitHub Actions runner service is not active. Set it up before imaging."
    PREFLIGHT_FAIL=1
else
    echo "OK:   Actions runner is active ($RUNNER_SVC)"
fi

# 4. Pi must have internet access (confirms WiFi is working)
if ! curl -s --max-time 5 https://github.com > /dev/null; then
    echo "FAIL: No internet access — ensure the Pi is connected to WiFi before imaging."
    PREFLIGHT_FAIL=1
else
    echo "OK:   Internet access confirmed"
fi

if [ "$PREFLIGHT_FAIL" -eq 1 ]; then
    echo ""
    echo "==========================================="
    echo "  SYSPREP ABORTED — fix the issues above"
    echo "==========================================="
    exit 1
fi

echo ""
echo "All pre-flight checks passed."

echo ""
echo "==========================================="
echo "  BigRock Sysprep"
echo "  $(date)"
echo "==========================================="
echo ""
echo "This will prepare the Pi for cloning and POWER IT OFF."
echo "Press Ctrl+C within 5 seconds to cancel..."
sleep 5

# ---------------------------------------------------------------------------
# Stop all app services cleanly
# ---------------------------------------------------------------------------
echo ">>> Stopping services..."
systemctl stop bigrock.service            2>/dev/null || true
systemctl stop bigrock-update.timer       2>/dev/null || true
systemctl stop bigrock-update.service     2>/dev/null || true
systemctl stop bigrock-wifi-setup.service 2>/dev/null || true
# Stop and remove GitHub Actions runner (not needed on kiosk clones)
systemctl stop actions.runner.* 2>/dev/null || true
systemctl disable actions.runner.* 2>/dev/null || true
rm -rf /home/pi/actions-runner

# ---------------------------------------------------------------------------
# Clear unique machine identifiers (regenerated on each clone's first boot)
# ---------------------------------------------------------------------------
echo ">>> Clearing machine-id..."
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

echo ">>> Clearing SSH host keys..."
rm -f /etc/ssh/ssh_host_*

# ---------------------------------------------------------------------------
# Clear per-device state files (clones need fresh WiFi setup)
# ---------------------------------------------------------------------------
echo ">>> Clearing WiFi configured flag (clones will run portal on first boot)..."
rm -f /home/pi/.bigrock-wifi-configured

echo ">>> Removing WiFi credentials (clones must not inherit master's network)..."
rm -f /etc/NetworkManager/system-connections/*.nmconnection

echo ">>> Keeping WiFi portal service disabled (app handles WiFi natively)..."
systemctl disable bigrock-wifi-setup.service 2>/dev/null || true
systemctl mask bigrock-wifi-setup.service 2>/dev/null || true

echo ">>> Resetting cloud-init instance ID so it re-runs on each clone..."
CLI=/boot/firmware/cmdline.txt
sed -i 's|i=[^ ]*|i=bigrock-clone-ready|g' "$CLI"
# Also clear cloud-init cached state so the new instance ID triggers a fresh run
rm -rf /var/lib/cloud/instances /var/lib/cloud/instance /var/lib/cloud/data /var/lib/cloud/sem 2>/dev/null || true

# Stamp version so clones don't needlessly re-run install.sh on first update
REPO_VERSION=$(cat "$APP_DIR/setup/VERSION" 2>/dev/null || echo "1")
echo "$REPO_VERSION" > /home/pi/.bigrock-version
echo ">>> Stamped app version: $REPO_VERSION"

# ---------------------------------------------------------------------------
# Install the firstboot individualizer (runs once on each clone's first boot)
# ---------------------------------------------------------------------------
echo ">>> Installing firstboot service..."
cp "$APP_DIR/setup/firstboot.sh" /usr/local/bin/bigrock-firstboot.sh
chmod +x /usr/local/bin/bigrock-firstboot.sh
cp "$APP_DIR/setup/services/bigrock-firstboot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bigrock-firstboot.service

# ---------------------------------------------------------------------------
# Clean up logs, history, temp files
# ---------------------------------------------------------------------------
echo ">>> Cleaning logs and history..."
journalctl --rotate 2>/dev/null || true
journalctl --vacuum-time=1s 2>/dev/null || true
rm -f /var/log/syslog* /var/log/auth.log* /var/log/kern.log* /var/log/daemon.log* 2>/dev/null || true
truncate -s 0 /var/log/lastlog 2>/dev/null || true
rm -f /home/pi/.bash_history /root/.bash_history 2>/dev/null || true
rm -f /home/pi/bigrock-app/cache/*.json 2>/dev/null || true
apt-get clean -qq 2>/dev/null || true

echo ""
echo "==========================================="
echo "  Sysprep complete!"
echo "==========================================="
echo ""
echo "Next steps:"
echo "  1. Wait for Pi to power off"
echo "  2. Remove the SD card"
echo "  3. Insert it into your Windows PC"
echo "  4. Double-click: setup\Create Image.bat"
echo "  5. Flash copies with Raspberry Pi Imager -> Use custom -> .img.gz"
echo ""
echo "Powering off in 3 seconds..."
sleep 3
poweroff
