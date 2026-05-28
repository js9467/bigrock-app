#!/bin/bash
# =============================================================================
# BigRock First-Boot Individualizer
# Runs ONCE on each cloned Pi's first boot.
# Installed by sysprep.sh, self-removes after running.
# =============================================================================
set -euo pipefail

LOG="/boot/firmware/bigrock-firstboot.log"
exec > >(tee -a "$LOG") 2>&1

echo ""
echo "==========================================="
echo "  BigRock First-Boot Setup"
echo "  $(date)"
echo "==========================================="

# ---------------------------------------------------------------------------
# Regenerate machine-id
# ---------------------------------------------------------------------------
echo ">>> Regenerating machine-id..."
rm -f /etc/machine-id
systemd-machine-id-setup
# Keep dbus in sync
if [ -L /var/lib/dbus/machine-id ]; then
    true  # already a symlink to /etc/machine-id
else
    cp /etc/machine-id /var/lib/dbus/machine-id
fi

# ---------------------------------------------------------------------------
# Regenerate SSH host keys
# ---------------------------------------------------------------------------
echo ">>> Regenerating SSH host keys..."
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
systemctl restart ssh 2>/dev/null || true

# ---------------------------------------------------------------------------
# Set hostname based on last 3 bytes of primary network interface MAC
# Result looks like: bigrock-a1b2c3
# ---------------------------------------------------------------------------
echo ">>> Setting hostname..."
HOSTNAME=""
for IFACE in eth0 end0 wlan0; do
    MAC_FILE="/sys/class/net/$IFACE/address"
    if [ -f "$MAC_FILE" ]; then
        SUFFIX=$(cat "$MAC_FILE" | tr -d ':' | tail -c 7)
        if [ -n "$SUFFIX" ]; then
            HOSTNAME="bigrock-${SUFFIX}"
            break
        fi
    fi
done
# Fallback to random if no interface found
if [ -z "$HOSTNAME" ]; then
    HOSTNAME="bigrock-$(head -c 3 /dev/urandom | xxd -p)"
fi

hostnamectl set-hostname "$HOSTNAME"
# Update /etc/hosts so local name resolution works
sed -i "s/127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts || \
    echo "127.0.1.1	$HOSTNAME" >> /etc/hosts
echo "  Hostname set to: $HOSTNAME"

# ---------------------------------------------------------------------------
# Self-remove so this never runs again
# ---------------------------------------------------------------------------
echo ">>> Disabling firstboot service..."
systemctl disable bigrock-firstboot.service 2>/dev/null || true
rm -f /etc/systemd/system/bigrock-firstboot.service
rm -f /usr/local/bin/bigrock-firstboot.sh
systemctl daemon-reload

echo ""
echo "==========================================="
echo "  First-boot complete!"
echo "  This Pi is: $HOSTNAME"
echo "==========================================="
