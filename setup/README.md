# BigRock App — SD Card Setup Guide

## Overview

Each Raspberry Pi runs the app **locally** and auto-updates itself from GitHub every hour.  
On first boot, if no WiFi is configured the Pi creates a temporary hotspot so you can enter credentials.

---

## 1. Flash the SD Card

Use **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)** with:
- **OS**: Raspberry Pi OS Lite (64-bit) — Bookworm or later
- **Customize settings (gear icon)**:
  - Set hostname to something unique, e.g. `bigrock-1`, `bigrock-2` …
  - Enable SSH
  - Username: `pi` / Password: `gie5Dieg!` (or your own)
  - *(WiFi is optional here — the app will prompt on first boot if omitted)*

---

## 2. First Boot — Install the App

SSH into the Pi (or connect a keyboard/monitor) and run:

```bash
curl -sSL https://raw.githubusercontent.com/js9467/bigrock-app/main/setup/install.sh | bash
sudo reboot
```

The script takes ~5 minutes.  It:
- Installs all dependencies
- Clones the repo
- Configures the Wayland kiosk (labwc + Chromium)
- Writes the sudoers rule for service management
- Enables all systemd services

---

## 3. First Boot — WiFi Setup (if not pre-configured)

After rebooting, if the Pi has no internet connection:

1. A hotspot named **`BigRock-Setup`** (password `bigrock1234`) appears.
2. Connect your phone or laptop to that network.
3. Open a browser and go to **`http://10.42.0.1`**.
4. Select your home/venue WiFi and enter the password.
5. The Pi connects, saves the credentials, and reboots into the kiosk app.

*After this first-time setup, WiFi credentials are saved permanently by NetworkManager.*

---

## 4. Auto-Updates

Every hour (and on each boot), the Pi:
1. Checks GitHub for new commits.
2. If changes are found, pulls them and restarts the app service.
3. Logs to `/home/pi/bigrock-update.log`.

No manual intervention needed. Simply push to `main` and every Pi picks it up within an hour.

---

## 5. Multiple Devices

Give each Pi a different hostname (`bigrock-1.local`, `bigrock-2.local`, …) via Raspberry Pi Imager.  
All other configuration is repo-based — every device stays in sync automatically.

**There are no hardcoded IP addresses in the application.** The Flask server binds to `0.0.0.0:5000` and Chromium opens `http://localhost:5000`.

---

## Useful Commands (on the Pi)

| Action | Command |
|--------|---------|
| Check app status | `sudo systemctl status bigrock` |
| Restart app | `sudo systemctl restart bigrock` |
| View app logs | `journalctl -u bigrock -f` |
| Force update now | `sudo systemctl start bigrock-update` |
| View update log | `cat ~/bigrock-update.log` |
| Reset WiFi setup | `rm ~/.bigrock-wifi-configured && sudo reboot` |
