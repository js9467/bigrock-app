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
