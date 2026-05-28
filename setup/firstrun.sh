#!/bin/bash
# =============================================================================
# BigRock App — First-Run Bootstrap
# Runs ONCE as root on first Pi boot, triggered by cmdline.txt injection.
# After completion the Pi reboots into the fully-configured kiosk app.
# =============================================================================
# This file lives on the FAT32 boot partition (/boot/firmware/) so it is
# readable/writable from Windows Explorer without any special tools.
# =============================================================================
set -euo pipefail

LOG="/boot/firmware/bigrock-firstrun.log"
exec > >(tee -a "$LOG") 2>&1

echo "==========================================="
echo " BigRock First-Run Bootstrap"
echo " $(date)"
echo "==========================================="

REPO_URL="https://github.com/js9467/bigrock-app.git"
APP_DIR="/home/pi/bigrock-app"

# ---------------------------------------------------------------------------
# Step 1: Wait for network (skip — WiFi portal will handle it after reboot)
# We don't need internet yet; install.sh handles the network check.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Step 2: Expand filesystem (Raspberry Pi OS does this on first boot already,
# but we trigger it explicitly so it's done before our installs)
# ---------------------------------------------------------------------------
echo ">>> Expanding filesystem..."
raspi-config --expand-rootfs 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 3: Create the pi user's home dirs if not already present
# ---------------------------------------------------------------------------
mkdir -p /home/pi
chown pi:pi /home/pi

# ---------------------------------------------------------------------------
# Step 4: System packages needed to bootstrap
# ---------------------------------------------------------------------------
echo ">>> Installing bootstrap packages..."
apt-get update -y -qq
apt-get install -y -qq git curl python3-pip python3-venv

# ---------------------------------------------------------------------------
# Step 5: Clone the app repo
# ---------------------------------------------------------------------------
echo ">>> Cloning BigRock app..."
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    git clone "$REPO_URL" "$APP_DIR"
fi
chown -R pi:pi "$APP_DIR"

# ---------------------------------------------------------------------------
# Step 6: Run the main install script (installs all deps, services, kiosk)
# ---------------------------------------------------------------------------
echo ">>> Running main install script..."
chmod +x "$APP_DIR/setup/install.sh"
# Run as pi so file ownership is correct, but pass sudo for privileged ops
su -c "bash $APP_DIR/setup/install.sh" pi

# ---------------------------------------------------------------------------
# Step 7: Remove this script from cmdline.txt so it doesn't run again
# ---------------------------------------------------------------------------
echo ">>> Cleaning up cmdline.txt..."
CMDLINE="/boot/firmware/cmdline.txt"
sed -i 's| systemd\.run=[^ ]*||g' "$CMDLINE"
sed -i 's| systemd\.run_success_action=[^ ]*||g' "$CMDLINE"
sed -i 's| systemd\.unit=[^ ]*||g' "$CMDLINE"

echo ">>> First-run complete. Rebooting..."
echo "==========================================="
sleep 3
reboot
