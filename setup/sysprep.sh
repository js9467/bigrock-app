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
# Stop GitHub Actions runner if present (not needed on kiosk clones)
systemctl stop  actions.runner.* 2>/dev/null || true
systemctl disable actions.runner.* 2>/dev/null || true

# ---------------------------------------------------------------------------
# Clear unique machine identifiers (regenerated on each clone's first boot)
# ---------------------------------------------------------------------------
echo ">>> Clearing machine-id..."
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

echo ">>> Clearing SSH host keys..."
rm -f /etc/ssh/ssh_host_*

# ---------------------------------------------------------------------------
# Clear per-device state files
# ---------------------------------------------------------------------------
echo ">>> Clearing WiFi configured flag..."
rm -f /home/pi/.bigrock-wifi-configured

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
