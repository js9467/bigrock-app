#!/usr/bin/env python3
"""
BigRock First-Boot WiFi Setup Portal
=====================================
On first boot (when no WiFi is configured), this script:
  1. Scans for available WiFi networks
  2. Creates a hotspot named "BigRock-Setup" (password: bigrock1234) using NetworkManager
  3. Runs a web portal at http://10.42.0.1 where the user enters their WiFi credentials
  4. Connects the Pi to the selected network, disables the hotspot, and reboots

Run as root (required for nmcli connection management and binding to port 80).
"""
import subprocess
import sys
import time
import os
from flask import Flask, request, render_template_string

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOTSPOT_SSID = "BigRock-Setup"
HOTSPOT_PASS = "bigrock1234"
HOTSPOT_IP   = "10.42.0.1"
PORTAL_PORT  = 80
FLAG_FILE    = "/home/pi/.bigrock-wifi-configured"

app = Flask(__name__)
_scanned_networks: list[dict] = []

# ---------------------------------------------------------------------------
# HTML template — mobile-friendly, no external dependencies
# ---------------------------------------------------------------------------
_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BigRock WiFi Setup</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #002855; color: #fff; min-height: 100vh;
           display: flex; align-items: center; justify-content: center; padding: 16px; }
    .card { background: #fff; color: #333; border-radius: 12px;
            padding: 28px 24px; max-width: 420px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,.4); }
    h1  { font-size: 1.4rem; color: #002855; margin-bottom: 4px; }
    p.sub { font-size: .85rem; color: #666; margin-bottom: 20px; }
    label { font-size: .85rem; font-weight: 600; color: #444;
            display: block; margin-bottom: 4px; margin-top: 14px; }
    select, input[type=text], input[type=password] {
      width: 100%; padding: 10px 12px; border: 1px solid #ccc;
      border-radius: 6px; font-size: 1rem; }
    select:focus, input:focus { outline: 2px solid #002855; }
    .btn { display: block; width: 100%; margin-top: 22px; padding: 13px;
           background: #002855; color: #fff; border: none; border-radius: 8px;
           font-size: 1rem; font-weight: 700; cursor: pointer; }
    .btn:active { opacity: .85; }
    .err { background: #fde8e8; border: 1px solid #f5c6c6; color: #c0392b;
           padding: 10px 12px; border-radius: 6px; font-size: .9rem; margin-top: 14px; }
    .ok  { background: #e8f8e8; border: 1px solid #c6f5c6; color: #27ae60;
           padding: 10px 12px; border-radius: 6px; font-size: .9rem; margin-top: 14px; }
    #spinner { display: none; text-align: center; margin-top: 12px; color: #666; }
  </style>
</head>
<body>
  <div class="card">
    <h1>&#9744; BigRock WiFi Setup</h1>
    <p class="sub">Select your WiFi network and enter the password to connect.</p>

    {% if error %}
    <div class="err">{{ error }}</div>
    {% endif %}

    <form method="POST" action="/connect" onsubmit="document.getElementById('spinner').style.display='block'">
      <label for="ssid">WiFi Network</label>
      <select name="ssid" id="ssid">
        {% for net in networks %}
        <option value="{{ net.ssid }}">{{ net.ssid }}
          {%- if net.signal >= 70 %} (Strong)
          {%- elif net.signal >= 40 %} (Good)
          {%- else %} (Weak){% endif %}
        </option>
        {% endfor %}
        <option value="__other__">Other (type below)...</option>
      </select>

      <label for="ssid_manual">Or type SSID manually</label>
      <input type="text" name="ssid_manual" id="ssid_manual"
             placeholder="Leave blank to use selection above" autocorrect="off" autocapitalize="none">

      <label for="password">Password</label>
      <input type="password" name="password" id="password"
             placeholder="Leave blank for open networks" autocomplete="current-password">

      <button type="submit" class="btn">Connect &amp; Reboot</button>
    </form>
    <div id="spinner">Connecting... the Pi will reboot automatically. Please wait.</div>
  </div>
</body>
</html>"""

_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Connected!</title>
  <style>
    body { font-family: sans-serif; background: #002855; color: #fff;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; }
    .card { background: #fff; color: #333; border-radius: 12px; padding: 32px 28px;
            max-width: 360px; text-align: center; }
    h1 { color: #27ae60; margin-bottom: 8px; }
    p { font-size: .9rem; color: #666; }
  </style>
</head>
<body>
  <div class="card">
    <h1>&#10003; Connected!</h1>
    <p>The Pi is rebooting and will start the BigRock app automatically.</p>
    <p style="margin-top:12px">You can close this page.</p>
  </div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def scan_networks() -> list[dict]:
    """Scan for available WiFi networks before creating the hotspot."""
    result = _run(
        ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list',
         '--rescan', 'yes'],
        timeout=30
    )
    nets: list[dict] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        # nmcli -t separates fields with ':'; SSID may itself contain ':'
        # The format is  SSID:SIGNAL:SECURITY
        parts = line.split(':')
        if len(parts) < 2:
            continue
        ssid = parts[0].strip()
        if not ssid or ssid == HOTSPOT_SSID or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal = int(parts[1])
        except (ValueError, IndexError):
            signal = 0
        nets.append({'ssid': ssid, 'signal': signal})
    nets.sort(key=lambda x: -x['signal'])
    return nets[:25]


def create_hotspot() -> None:
    """Create a NetworkManager WiFi hotspot."""
    # Remove any existing connection with the same name
    _run(['nmcli', 'connection', 'delete', HOTSPOT_SSID])

    subprocess.run([
        'nmcli', 'connection', 'add', 'type', 'wifi',
        'ifname', 'wlan0', 'con-name', HOTSPOT_SSID,
        'autoconnect', 'no', 'ssid', HOTSPOT_SSID
    ], check=True)
    subprocess.run([
        'nmcli', 'connection', 'modify', HOTSPOT_SSID,
        '802-11-wireless.mode', 'ap',
        '802-11-wireless.band', 'bg',
        'ipv4.method', 'shared',
        'ipv4.addresses', f'{HOTSPOT_IP}/24',
        'wifi-sec.key-mgmt', 'wpa-psk',
        'wifi-sec.psk', HOTSPOT_PASS,
    ], check=True)
    subprocess.run(['nmcli', 'connection', 'up', HOTSPOT_SSID], check=True)
    time.sleep(3)  # let DHCP settle


def connect_wifi(ssid: str, password: str) -> tuple[bool, str]:
    """Attempt to connect to the given WiFi network via NetworkManager."""
    cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
    if password:
        cmd += ['password', password]
    result = _run(cmd, timeout=45)
    if result.returncode == 0:
        return True, ''
    return False, result.stderr.strip()

# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path=''):
    return render_template_string(_HTML, networks=_scanned_networks, error=None)


@app.route('/connect', methods=['POST'])
def do_connect():
    ssid_select = request.form.get('ssid', '').strip()
    ssid_manual = request.form.get('ssid_manual', '').strip()
    password    = request.form.get('password', '').strip()

    # Manual entry takes priority if filled in
    ssid = ssid_manual if ssid_manual else ssid_select
    if not ssid or ssid == '__other__':
        return render_template_string(_HTML, networks=_scanned_networks,
                                      error='Please select or type a WiFi network name.')

    ok, err = connect_wifi(ssid, password)
    if ok:
        # Mark as configured and schedule reboot
        open(FLAG_FILE, 'w').close()
        subprocess.Popen(['systemctl', 'disable', 'bigrock-wifi-setup.service'])
        subprocess.Popen(['reboot'])
        return _SUCCESS_HTML
    else:
        return render_template_string(_HTML, networks=_scanned_networks,
                                      error=f'Could not connect to "{ssid}": {err}')

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    global _scanned_networks

    # Check if WiFi is already working — if so, just mark as configured and exit
    connectivity = _run(['nmcli', '-t', '-f', 'CONNECTIVITY', 'general']).stdout.strip()
    if 'full' in connectivity or 'limited' in connectivity:
        print("WiFi already connected — writing flag and exiting setup portal.")
        open(FLAG_FILE, 'w').close()
        sys.exit(0)

    print("No internet connection detected. Starting WiFi setup portal...")
    print(f"Scanning for networks...")
    _scanned_networks = scan_networks()
    print(f"Found {len(_scanned_networks)} network(s).")

    print(f"Creating hotspot '{HOTSPOT_SSID}'...")
    try:
        create_hotspot()
    except subprocess.CalledProcessError as e:
        print(f"WARNING: Could not create hotspot: {e}")
        print("Portal will still run — user must manually navigate to the Pi's IP.")

    print(f"Portal running at http://{HOTSPOT_IP}:{PORTAL_PORT}")
    print(f"Connect your phone/laptop to WiFi '{HOTSPOT_SSID}' (password: {HOTSPOT_PASS})")
    app.run(host='0.0.0.0', port=PORTAL_PORT, debug=False)


if __name__ == '__main__':
    if os.geteuid() != 0:
        print("ERROR: wifi_portal.py must run as root (sudo).")
        sys.exit(1)
    main()
