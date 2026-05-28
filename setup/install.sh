#!/usr/bin/env bash
# =============================================================================
# BigRock App — Fresh Raspberry Pi Setup Script
# =============================================================================
# Can be run two ways:
#
#   A) Manually via SSH as the pi user:
#      curl -sSL https://raw.githubusercontent.com/js9467/bigrock-app/main/setup/install.sh | bash
#
#   B) Automatically on first boot via firstrun.sh (runs as pi, firstrun runs as root)
#
# This script:
#   1. Installs system dependencies
#   2. Clones (or updates) the app repo
#   3. Creates a Python virtual env and installs pip deps
#   4. Writes the sudoers rule so the runner/update service can manage services
#   5. Installs and enables all systemd services
#   6. Configures the Wayland kiosk (labwc + Chromium)
#   7. Sets up auto-login on tty1
# =============================================================================
set -euo pipefail

# Works whether run as pi (manual) or as pi via su from root (firstrun.sh)
SUDO="sudo"
if [ "$(id -u)" = "0" ]; then SUDO=""; fi

APP_DIR="/home/pi/bigrock-app"
REPO_URL="https://github.com/js9467/bigrock-app.git"
LOG="/home/pi/bigrock-setup.log"

exec > >(tee -a "$LOG") 2>&1
echo "===== BigRock Setup — $(date) ====="
echo "Running as: $(whoami)"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo ""
echo ">>> Installing system packages..."
$SUDO apt-get update -y
$SUDO apt-get install -y \
    python3-pip python3-venv python3-dev \
    git curl unclutter \
    chromium \
    build-essential libssl-dev libffi-dev \
    network-manager \
    labwc wlr-randr

# ---------------------------------------------------------------------------
# 2. Clone or update the repo
# ---------------------------------------------------------------------------
echo ""
echo ">>> Setting up app repo at $APP_DIR..."
if [ -d "$APP_DIR/.git" ]; then
    echo "Repo exists — pulling latest..."
    cd "$APP_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    echo "Cloning repo..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ---------------------------------------------------------------------------
# 3. Python virtual environment + dependencies
# ---------------------------------------------------------------------------
echo ""
echo ">>> Setting up Python virtual environment..."
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt --quiet
echo "Python deps installed."

# ---------------------------------------------------------------------------
# 4. Required directories
# ---------------------------------------------------------------------------
mkdir -p "$APP_DIR/cache"
mkdir -p "$APP_DIR/static/boat-images"

# ---------------------------------------------------------------------------
# 5. Sudoers rule (one-time; enables CI runner + update service to manage services)
# ---------------------------------------------------------------------------
echo ""
echo ">>> Writing sudoers rule..."
SUDOERS_CONTENT="pi ALL=(ALL) NOPASSWD: \
/usr/bin/systemctl restart bigrock.service, \
/usr/bin/systemctl stop bigrock.service, \
/usr/bin/systemctl start bigrock.service, \
/usr/bin/systemctl status bigrock.service, \
/usr/bin/systemctl restart bigrock-update.service, \
/usr/bin/systemctl disable bigrock-wifi-setup.service, \
/usr/bin/systemctl daemon-reload, \
/usr/bin/apt-get, \
/usr/bin/nmcli, \
/sbin/reboot, \
/usr/bin/bash $APP_DIR/setup/services/bigrock-upgrade.sh"
echo "$SUDOERS_CONTENT" | $SUDO tee /etc/sudoers.d/bigrock > /dev/null
$SUDO chmod 440 /etc/sudoers.d/bigrock
echo "Sudoers rule written to /etc/sudoers.d/bigrock"

# ---------------------------------------------------------------------------
# 6. Install systemd service files
# ---------------------------------------------------------------------------
echo ""
echo ">>> Installing systemd services..."
$SUDO cp "$APP_DIR/setup/services/"*.service /etc/systemd/system/
if ls "$APP_DIR/setup/services/"*.timer 1>/dev/null 2>&1; then
    $SUDO cp "$APP_DIR/setup/services/"*.timer /etc/systemd/system/
fi
$SUDO systemctl daemon-reload
$SUDO systemctl enable bigrock.service
$SUDO systemctl enable bigrock-update.timer
$SUDO systemctl enable bigrock-wifi-setup.service
echo "Services enabled."

# ---------------------------------------------------------------------------
# 7. Auto-login on tty1 (required for kiosk without display manager)
# ---------------------------------------------------------------------------
echo ""
echo ">>> Configuring auto-login..."
$SUDO mkdir -p /etc/systemd/system/getty@tty1.service.d
cat << 'EOF' | $SUDO tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF

# ---------------------------------------------------------------------------
# 8. Kiosk configuration (labwc Wayland compositor)
# ---------------------------------------------------------------------------
echo ""
echo ">>> Configuring kiosk..."
mkdir -p /home/pi/.config/labwc

# labwc autostart: launch Chromium in kiosk mode pointing at the local app
cat << 'EOF' > /home/pi/.config/labwc/autostart
# Hide mouse cursor after 5s of inactivity
unclutter -idle 5 -root &
# Launch app in kiosk mode
chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-session-crashed-bubble \
    --app=http://localhost:5000 &
EOF
chmod +x /home/pi/.config/labwc/autostart

# labwc rc.xml: minimal config, no window decorations
mkdir -p /home/pi/.config/labwc
if [ ! -f /home/pi/.config/labwc/rc.xml ]; then
    cat << 'EOF' > /home/pi/.config/labwc/rc.xml
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <theme><name>Clearlooks</name></theme>
  <desktops><number>1</number></desktops>
</openbox_config>
EOF
fi

# .bashrc: auto-start Wayland session on tty1 login
if ! grep -q "bigrock-kiosk" /home/pi/.bashrc 2>/dev/null; then
    cat << 'EOF' >> /home/pi/.bashrc

# BigRock kiosk: auto-start Wayland on tty1
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec labwc 2>/dev/null
fi
EOF
    echo ".bashrc updated for kiosk auto-start."
fi

# ---------------------------------------------------------------------------
# Done — stamp the deployed version so update script knows what's installed
# ---------------------------------------------------------------------------
REPO_VERSION=$(cat "$APP_DIR/setup/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "1")
echo "$REPO_VERSION" > /home/pi/.bigrock-version
echo "Deployed version stamped: $REPO_VERSION"
echo ""
echo "===== BigRock Setup Complete ====="
echo ""
echo "Next steps:"
echo "  1. Reboot the Pi: sudo reboot"
echo "  2. On first boot, if no WiFi is configured, the Pi will create a"
echo "     hotspot named 'BigRock-Setup' (password: bigrock1234)."
echo "  3. Connect your phone/laptop to that network and visit:"
echo "     http://10.42.0.1 to configure WiFi."
echo "  4. After WiFi is configured, the Pi reboots into the kiosk app."
echo ""
echo "Log saved to: $LOG"
