from flask import Flask, jsonify, request, render_template
import json
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta
import random
import subprocess
import time
from bs4 import BeautifulSoup


from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

import requests

from playwright.sync_api import sync_playwright

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

print("App starting... PLAYWRIGHT_AVAILABLE:", PLAYWRIGHT_AVAILABLE)

app = Flask(__name__, template_folder='static')
SETTINGS_FILE = 'settings.json'
MOCK_DATA_FILE = 'mock_data.json'
HISTORICAL_DATA_FILE = 'historical_data.json'
CACHE_FILE = 'cache.json'
PARTICIPANTS_CACHE_FILE = 'participants.json'
import subprocess

def get_version():
    try:
        with open("version.txt") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

known_boat_images = {}

def normalize_boat_name(name):
    return name.strip().lower()\
        .replace(',', '')\
        .replace(' ', '_')\
        .replace('-', '_')\
        .replace('__', '_')  # Collapse double underscores



#cache
def cache_boat_image(name, image_url):
    """Download and cache image to static/images/boats/, return local path."""
    safe_name = normalize_boat_name(name)
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ('_', '-'))  # strip quotes etc.
    ext = ".jpg" if ".jpg" in image_url.lower() else ".png"
    filename = f"{safe_name}{ext}"
    local_path = os.path.join("static", "images", "boats", filename)
    relative_path = f"/static/images/boats/{filename}"
   

    if not os.path.exists(local_path):
        try:
            response = requests.get(image_url, timeout=10, verify=False)
            if response.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(response.content)
                print(f"📥 Cached image for {name}")
            else:
                print(f"⚠️ Failed to download image for {name}: HTTP {response.status_code}")
        except Exception as e:
            print(f"⚠️ Error downloading image for {name}: {e}")
            return "/static/images/placeholder.png"

    return relative_path

REMOTE_SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"
REMOTE_SETTINGS_CACHE = {"last_fetch": 0, "data": {}}

def load_remote_settings(force=False):
    now = time.time()
    if not force and now - REMOTE_SETTINGS_CACHE["last_fetch"] < 300:
        return REMOTE_SETTINGS_CACHE["data"]
    try:
        response = requests.get(REMOTE_SETTINGS_URL, timeout=5, verify=False)
        response.raise_for_status()
        data = response.json()
        REMOTE_SETTINGS_CACHE["data"] = data
        REMOTE_SETTINGS_CACHE["last_fetch"] = now
        print("🔁 Loaded remote tournament settings.")
        return data
    except Exception as e:
        print(f"⚠️ Failed to load remote settings: {e}")
        return REMOTE_SETTINGS_CACHE["data"]

EVENTS_CACHES = {}  # tournament_key: {"last_time": 0, "data": []}

def scrape_events(tournament):
    remote = load_remote_settings()
    config = remote.get(tournament, {})
    if not config:
        print(f"❌ No config for tournament: {tournament}")
        return []

    url = config.get("events")
    if not url:
        print(f"❌ No events URL for {tournament} in remote settings.")
        return []

    cache_key = tournament.replace(" ", "_").lower()
    if cache_key not in EVENTS_CACHES:
        EVENTS_CACHES[cache_key] = {"last_time": 0, "data": []}

    cache = EVENTS_CACHES[cache_key]
    now = time.time()
    if cache["data"] and now - cache["last_time"] < 300:
        return cache["data"]

    events = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36", ignore_https_errors=True)
            page = context.new_page()

            print(f"🔗 Navigating to {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("#feed-all article", timeout=30000)
            except:
                print("No activities found or selector timeout.")
            feed_items = page.query_selector_all("#feed-all article")

            print(f"✅ Found {len(feed_items)} activity items for {tournament}")

            for item in feed_items:
                try:
                    boat = item.query_selector("h4").inner_text().strip()
                    description = item.query_selector("p strong").inner_text().strip()
                    timestamp = item.query_selector("p.pull-right").inner_text().strip()

                    events.append({
                        "boat": boat,
                        "message": description,
                        "time": timestamp,
                        "action": description.lower(),
                        "image": "/static/images/placeholder.png"
                    })
                except Exception as e:
                    print(f"⚠️ Failed to parse one item: {e}")

            context.close()
            browser.close()

    except Exception as e:
        print(f"❌ Scrape failed for {tournament}: {e}")

    cache["data"] = events
    cache["last_time"] = now
    return events


def get_current_tournament():
    try:
        with open("settings.json", "r") as f:
            settings = json.load(f)
            return settings.get("tournament", "Big Rock")
    except Exception as e:
        print("⚠️ Could not load tournament from settings:", e)
        return "Big Rock"

PARTICIPANTS_MASTER_FILE = 'participants_master.json'

def generate_uid(tournament, name):
    return f"{tournament.lower().replace(' ', '_')}_{normalize_boat_name(name).replace(' ', '_')}"

def save_participant_to_master(entry):
    data = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
            data = json.load(f)

    if not any(p["uid"] == entry["uid"] for p in data):
        data.append(entry)
        with open(PARTICIPANTS_MASTER_FILE, 'w') as f:
            json.dump(data, f, indent=2)



def get_mac_address():
    try:
        mac = subprocess.check_output(['cat', '/sys/class/net/wlan0/address']).decode().strip().replace(':', '')[-4:].lower()
        return mac
    except Exception as e:
        print(f"Error getting MAC address: {e}")
        return '0000'

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
    return {
        'sounds': {'hooked': True, 'released': True, 'boated': True},
        'followed_boats': [],
        'effects_volume': 0.5,
        'radio_volume': 0.5,
        'tournament': 'Kids',
        'wifi_ssid': None,
        'wifi_password': None,
        'data_source': 'current',
        'disable_sleep_mode': False
    }

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

def load_cache(tournament):
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            print(f"Error loading cache: {e}")
    return load_mock_data(tournament)

def save_cache(tournament, data):
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump({tournament: data}, f, indent=4)
    except Exception as e:
        print(f"Error saving cache: {e}")

def load_mock_data(tournament):
    if os.path.exists(MOCK_DATA_FILE):
        try:
            with open(MOCK_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            print(f"Error loading mock data: {e}")
    # Use known for mock participants
    participants = [{'name': name, 'image': image} for name, image in known_boat_images.items()]
    return {'events': [], 'participants': participants, 'leaderboard': [], 'gallery': []}

def load_historical_data(tournament):
    if os.path.exists(HISTORICAL_DATA_FILE):
        try:
            with open(HISTORICAL_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            print(f"Error loading historical data: {e}")
    return {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []}

def check_internet():
    try:
        subprocess.check_call(['ping', '-c', '1', '8.8.8.8'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def check_video_trigger():
    settings = load_settings()
    tournament = settings.get('tournament', 'Kids')
    if settings['data_source'] == 'historical':
        events = load_historical_data(tournament).get('events', [])
    elif settings['data_source'] == 'demo':
        events = generate_demo_events(tournament)
    else:
        events = scrape_events(tournament)
    now = datetime.now()
    for event in events:
        if event['action'].lower() == 'boated' and event.get('eta'):
            try:
                eta_time = datetime.strptime(event['eta'], '%I:%M %p').replace(year=now.year, month=now.month, day=now.day)
                time_diff = (eta_time - now).total_seconds() / 60
                if 0 <= time_diff <= 15:
                    return {'trigger': True, 'boat': event['boat'], 'eta': event['eta']}
            except ValueError:
                continue
    return {'trigger': False}

from flask import render_template_string


PARTICIPANTS_CACHES = {}  # tournament_key: {"last_time": 0, "data": []}

def scrape_participants(tournament):
    print(f"🔍 Launching Playwright to scrape participants for {tournament}...")
    boats = []

    settings = load_remote_settings()
    config = settings.get(tournament, {})
    if not config:
        print(f"❌ No config for tournament: {tournament}")
        return []

    url = config.get("participants")
    if not url:
        print(f"❌ No participant URL for {tournament} in remote settings.")
        return []

    cache_key = tournament.replace(" ", "_").lower()
    if cache_key not in PARTICIPANTS_CACHES:
        PARTICIPANTS_CACHES[cache_key] = {"last_time": 0, "data": []}

    cache = PARTICIPANTS_CACHES[cache_key]
    now = time.time()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True, user_agent="...")
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)

            html_content = page.content()
            print(f"Page HTML snippet for {tournament}:\n{html_content[:500]}...")

            try:
                page.wait_for_selector(".participant, .boat, .entry-list", timeout=30000)
            except:
                print("No participant list found or selector timeout.")

            exclude_patterns = config.get("exclude_patterns", [",", "2025 Edisto Invitational Billfish"])
            name_selector = config.get("name_selector", "h1, h2, h3, h4, h5, h6, span.name, div.name, p.name, .participant-name, .title, .boat-name")
            image_selector = config.get("image_selector", "img")

            entries = page.evaluate(f"""
                () => {{
                    const boats = [];
                    const participantContainers = document.querySelectorAll('div.boat-entry, li.boat, article.boat, section.boat, div, li, article, section');
                    participantContainers.forEach(container => {{
                        const nameTag = container.querySelector('{name_selector}');
                        const imgTag = container.querySelector('{image_selector}');
                        const name = nameTag?.textContent?.trim();
                        let image = imgTag?.getAttribute('src') || imgTag?.getAttribute('data-src');
                        if (image && !image.startsWith('http')) {{
                            image = `https:${{image}}`;
                        }}
                        if (name) {{
                            boats.push({{ name, image: image || '' }});
                        }}
                    }});
                    return boats;
                }}
            """)

            print(f"Found {len(entries)} potential participants for {tournament}")

            for entry in entries:
                name = entry['name'].strip()
                if not name or any(pattern in name for pattern in exclude_patterns):
                    print(f"Skipping invalid entry: {name}")
                    continue

                image_url = entry['image']
                local_image = cache_boat_image(name, image_url)
                participant = {
                    "uid": generate_uid(tournament, name),
                    "boat": name,
                    "image": local_image
                }

                if participant not in boats:
                    save_participant_to_master(participant)
                    boats.append(participant)

            context.close()
            browser.close()

            print(f"✅ Scraped and cached {len(boats)} valid boats for {tournament}")

    except Exception as e:
        print(f"❌ Playwright error for {tournament}: {e}")
        print(f"URL: {url}")
        print(f"Config: {config}")
        boats = []

    cache["data"] = boats
    cache["last_time"] = now
    return boats


# demo events 
def generate_demo_events(tournament):
    import random
    from datetime import datetime, timedelta

    tournament_key = tournament.lower().replace(" ", "_")
    events = []

    # Load real participants for this tournament
    participants = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        with open(PARTICIPANTS_MASTER_FILE, "r") as f:
            all_participants = json.load(f)
            participants = [
                p for p in all_participants if p["uid"].startswith(tournament_key)
            ]

    if not participants:
        print("⚠️ No participants found for demo mode.")
        return []

    now = datetime.now()
    timeline = []

    random.shuffle(participants)
    sample_boats = participants[:6]  # limit to 6 for less crowding

    for p in sample_boats:
        angler = p.get("angler", p.get("boat", "Unknown Angler"))
        boat = p.get("boat", "Unknown Boat")
        uid = p.get("uid")
        image = p.get("image", "/static/images/placeholder.png")

        # Random delay before this boat hooks up (30s–3min)
        hookup_delay_sec = random.randint(30, 180)
        now += timedelta(seconds=hookup_delay_sec)

        # Step 1: Hooked Up
        hookup_event = {
            "boat": boat,
            "angler": angler,
            "uid": uid,
            "image": image,
            "action": "hooked up.",
            "message": f"{angler} hooked up.",
            "time": now.strftime("Jul %d @ %I:%M %p"),
            "hookup_id": f"{uid}_{now.strftime('%H%M%S')}"
        }
        timeline.append(hookup_event)

        # Random delay before outcome (2–10 minutes)
        resolution_delay = random.randint(2, 10)
        now += timedelta(minutes=resolution_delay)

        # Step 2: Follow-up result (weighted)
        result_action, result_type = random.choices(
            population=[
                ("pulled hook.", "pulled"),
                ("wrong species.", "wrong"),
                ("released a blue marlin.", "released"),
                ("released a white marlin.", "released"),
                ("boated a blue marlin.", "boated"),
                ("boated a white marlin.", "boated"),
            ],
            weights=[3, 2, 4, 4, 1, 2],
            k=1
        )[0]

        resolution_event = {
            "boat": boat,
            "angler": angler,
            "uid": uid,
            "image": image,
            "action": result_action,
            "message": f"{angler} {result_action}",
            "time": now.strftime("Jul %d @ %I:%M %p"),
            "hookup_id": hookup_event["hookup_id"]
        }
        timeline.append(resolution_event)

        # Step 3: Headed to Scales — only for boated blue marlin
        if result_action == "boated a blue marlin.":
            now += timedelta(minutes=random.randint(1, 3))
            scales_event = {
                "boat": boat,
                "angler": angler,
                "uid": uid,
                "image": image,
                "action": "headed to scales.",
                "message": f"{angler} is headed to scales with a blue marlin.",
                "time": now.strftime("Jul %d @ %I:%M %p"),
                "hookup_id": hookup_event["hookup_id"],
                "eta": (datetime.now() + timedelta(minutes=random.randint(5, 15))).strftime("%I:%M %p")
            }
            timeline.append(scales_event)

    # Return in reverse chronological order (newest first)
    return sorted(timeline, key=lambda x: datetime.strptime(x["time"], "Jul %d @ %I:%M %p"), reverse=True)




# scrape leaderboard 
def scrape_leaderboard(tournament):
    if not check_internet():
        return load_cache(tournament)['leaderboard']

    remote = load_remote_settings()
    url = remote.get(tournament, {}).get("leaderboard")
    if not url:
        print(f"No leaderboard URL for {tournament}")
        return load_cache(tournament)['leaderboard']

    try:
        response = requests.get(url, timeout=5, verify=False)
        response.raise_for_status()
        print(f"Leaderboard response status ({tournament}): {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        leaderboard = []
        for item in soup.select('.leaderboard-item, .entry-content p, .leaderboard-table tr'):
            text = item.get_text(strip=True)
            if 'Place' in text or 'Winner' in text or text.startswith(('1.', '2.', '3.')):
                parts = text.split(',')
                if len(parts) >= 2:
                    boat = parts[0].replace('1.', '').replace('2.', '').replace('3.', '').strip()
                    points = parts[-1].strip() if 'Points' in parts[-1] or 'lb' in parts[-1] else text.split(' ')[-1].strip()
                    leaderboard.append({'boat': boat, 'points': points})
        if not leaderboard:
            print(f"No leaderboard found for {tournament}, using cache")
            leaderboard = load_cache(tournament)['leaderboard']
        else:
            cache = load_cache(tournament)
            cache['leaderboard'] = leaderboard
            save_cache(tournament, cache)
        return leaderboard[:3]
    except Exception as e:
        print(f"Scraping error (leaderboard, {tournament}): {e}")
        return load_cache(tournament)['leaderboard']
# scrape gallery 

def scrape_gallery():
    if not check_internet():
        settings = load_settings()
        return load_cache(settings['tournament'])['gallery']
    try:
        url = 'https://thebigrock.smugmug.com/2025-GALLERY'
        response = requests.get(url, timeout=5, verify=False)
        response.raise_for_status()
        print(f"Gallery response status: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        images = []
        for img in soup.select('img.sm-gallery-image, img.sm-image'):
            src = img.get('src')
            if src and src.startswith('https://'):
                images.append(src)
        if not images:
            print("No gallery images found, using cache")
            settings = load_settings()
            images = load_cache(settings['tournament'])['gallery']
        else:
            settings = load_settings()
            cache = load_cache(settings['tournament'])
            cache['gallery'] = images
            save_cache(settings['tournament'], cache)
        return images[:5]
    except Exception as e:
        print(f"Scraping error (gallery): {e}")
        settings = load_settings()
        return load_cache(settings['tournament'])['gallery']


# routes

        
@app.route('/')
def index():
    try:
        with open("settings.json", "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except:
        settings = {"tournament": "Big Rock"}
        tournament = "Big Rock"

    theme_class = f"theme-{tournament.lower().replace(' ', '-')}"
    version = get_version()
    return render_template("index.html", theme_class=theme_class, version=version, settings=settings)


    






@app.route('/settings-page')
def settings_page():
    return app.send_static_file('settings.html')

@app.route("/participants")
def participants_page():
    return app.send_static_file("participants.html")

@app.route('/api/participants')
def get_participants():
    try:
        with open("settings.json", "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except Exception as e:
        print(f"⚠️ Failed to load settings.json: {e}")
        tournament = "Big Rock"

    print(f"🎯 Using tournament: {tournament}")

    prefix = tournament.lower().replace(" ", "_")

    # 🟢 Load from master file
    all_participants = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                all_participants = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Master participant file is corrupt or empty.")

    filtered = [p for p in all_participants if p['uid'].startswith(prefix)]

    # 🟡 If nothing cached, scrape and retry
    if not filtered:
        print(f"⚠️ No participants found for '{prefix}', scraping...")
        scrape_participants(tournament)

        # Retry after scrape
        if os.path.exists(PARTICIPANTS_MASTER_FILE):
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                try:
                    all_participants = json.load(f)
                    filtered = [p for p in all_participants if p['uid'].startswith(prefix)]
                except json.JSONDecodeError:
                    print("⚠️ Master file still broken after scrape.")

    return jsonify(filtered)



@app.route('/wifi', methods=['GET', 'POST'])
def wifi():
    if request.method == 'POST':
        ssid = request.form.get('ssid')
        password = request.form.get('password')
        settings = load_settings()
        settings['wifi_ssid'] = ssid
        settings['wifi_password'] = password
        save_settings(settings)
        try:
            subprocess.run(['sudo', 'nmcli', 'con', 'add', 'type', 'wifi', 'ifname', 'wlan0', 'con-name', 'bigrock-wifi', 'ssid', ssid] + (['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password] if password else []), check=True)
            subprocess.run(['sudo', 'nmcli', 'con', 'up', 'bigrock-wifi'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
            return jsonify({'status': 'success'})
        except subprocess.CalledProcessError as e:
            print(f"Error connecting to WiFi: {e}")
            return jsonify({'status': 'error', 'message': str(e)})
    return render_template('wifi.html')

@app.route('/events')
def events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")

    try:
        events = scrape_events(tournament)
    except Exception as e:
        print(f"Scraping error (events, {tournament}): {e}")
        events = []

    try:
        if os.path.exists(PARTICIPANTS_MASTER_FILE):
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                participants = json.load(f)
                name_to_image = {
                    normalize_boat_name(p['boat']): p['image']
                    for p in participants
                    if p['uid'].startswith(tournament.lower().replace(" ", "_"))
                }

                for e in events:
                    norm_name = normalize_boat_name(e['boat'])
                    e['image'] = name_to_image.get(norm_name, "/static/images/placeholder.png")
    except Exception as e:
        print(f"⚠️ Failed to enrich events with images: {e}")

    return jsonify(events)



@app.route('/leaderboard')
def leaderboard():
    settings = load_settings()
    tournament = settings.get('tournament', 'Kids')
    if settings['data_source'] in ['historical', 'demo']:
        return jsonify(load_historical_data(tournament).get('leaderboard', []))
    return jsonify(scrape_leaderboard(tournament))

from dateutil import parser

from datetime import datetime

@app.route('/hooked')
def hooked():
    settings = load_settings()
    tournament = settings.get('tournament', 'Kids')

    # Load events
    if settings['data_source'] == 'historical':
        events = load_historical_data(tournament).get('events', [])
    elif settings['data_source'] == 'demo':
        events = generate_demo_events(tournament)
    else:
        events = scrape_events(tournament)

    # Build a set of resolved hookup_ids
    resolved_ids = {
        e['hookup_id'] for e in events
        if e.get('hookup_id') and e.get('action', '').lower() in [
            'released', 'boated', 'pulled hook', 'wrong species'
        ]
    }

    # Return only unresolved 'hooked up' events
    hooked = [
        e for e in events
        if e.get('action', '').lower() == 'hooked up'
        and e.get('hookup_id') not in resolved_ids
    ]

    return jsonify(hooked)





@app.route('/scales')
def scales():
    settings = load_settings()
    tournament = settings.get('tournament', 'Kids')

    if settings['data_source'] == 'historical':
        events = load_historical_data(tournament).get('events', [])
    elif settings['data_source'] == 'demo':
        events = generate_demo_events(tournament)
    else:
        events = scrape_events(tournament)

    return jsonify([
        event for event in events
        if event.get('action', '').lower() == 'headed to scales'
    ])


@app.route('/api/events')
def get_events():
    tournament = get_current_tournament()
    print(f"🎯 Loading events for: {tournament}")
    return jsonify(scrape_events(tournament))

@app.route('/gallery')
def gallery():
    return jsonify(scrape_gallery())

@app.route('/check-video-trigger')
def check_video_trigger_endpoint():
    return jsonify(check_video_trigger())

@app.route('/wifi-status')
def wifi_status():
    return jsonify({'connected': check_internet()})


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
        save_settings(settings_data)
        return jsonify({'status': 'success'})
    
    current_settings = load_settings()
    return jsonify(current_settings)

@app.route('/bluetooth-status')
def bluetooth_status():
    try:
        output = subprocess.check_output(['bluetoothctl', 'info']).decode()
        connected = 'Connected: yes' in output
        device_name = 'Unknown'
        if connected:
            for line in output.split('\n'):
                if line.strip().startswith('Name:'):
                    device_name = line.split(':', 1)[1].strip()
                    break
        status = f"Connected to {device_name}" if connected else 'Not Connected'
        return jsonify({'status': status})
    except Exception as e:
        print(f"Bluetooth status error: {e}")
        return jsonify({'status': 'Unknown'})

@app.route('/bluetooth')
def bluetooth():
    action = request.args.get('action')
    if action == 'scan':
        try:
            scan_proc = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            scan_proc.stdin.write('power on\n')
            scan_proc.stdin.write('agent on\n')
            scan_proc.stdin.write('default-agent\n')
            scan_proc.stdin.write('scan on\n')
            scan_proc.stdin.flush()
            time.sleep(5)

            scan_proc.stdin.write('devices\n')
            scan_proc.stdin.flush()
            time.sleep(1)

            scan_proc.stdin.write('exit\n')
            scan_proc.stdin.flush()

            stdout, _ = scan_proc.communicate(timeout=10)

            devices = []
            for line in stdout.split('\n'):
                if line.strip().startswith('Device'):
                    parts = line.split(' ')
                    if len(parts) >= 3:
                        mac = parts[1]
                        name = ' '.join(parts[2:])
                        devices.append({'mac': mac, 'name': name})
            return jsonify(devices)
        except Exception as e:
            print(f"Bluetooth scan error: {e}")
            return jsonify([])
    elif action == 'pair':
        mac = request.args.get('mac')
        try:
            # Run the pairing and trust commands
            commands = f"agent on\ndefault-agent\npair {mac}\ntrust {mac}\nconnect {mac}\n"
            subprocess.check_output(['bluetoothctl'], input=commands.encode(), stderr=subprocess.STDOUT)

            # Set the Bluetooth speaker as default in PipeWire
            subprocess.run(['wpctl', 'set-default', 'bluez_output.F8_DF_15_C2_09_58.1'], check=True)
            subprocess.run(['wpctl', 'set-mute', 'bluez_output.F8_DF_15_C2_09_58.1', '0'], check=True)
            subprocess.run(['wpctl', 'set-volume', 'bluez_output.F8_DF_15_C2_09_58.1', '1.0'], check=True)

            return jsonify({'status': 'success', 'output': 'Paired and audio output set'})
        except subprocess.CalledProcessError as e:
            return jsonify({'status': 'error', 'message': e.output.decode()})
    elif action == 'on':
        try:
            subprocess.run(['bluetoothctl', 'power', 'on'], check=True)
            return jsonify({'status': 'success'})
        except Exception as e:
            print(f"Bluetooth power on error: {e}")
            return jsonify({'status': 'error', 'message': str(e)})
    elif action == 'off':
        try:
            subprocess.run(['bluetoothctl', 'power', 'off'], check=True)
            return jsonify({'status': 'success'})
        except Exception as e:
            print(f"Bluetooth power off error: {e}")
            return jsonify({'status': 'error', 'message': str(e)})
    return jsonify([])

import threading

def refresh_data_loop(interval=600):  # 10 minutes
    def refresh():
        try:
            print("🔁 Background: Refreshing participants and events...")
            settings = load_settings()
            tournament = settings.get("tournament", "Big Rock")

            # Run both participant and event scrapers to update cache
            scrape_participants(tournament)
            scrape_events(tournament)
        except Exception as e:
            print(f"❌ Background refresh failed: {e}")
        finally:
            # Schedule next refresh
            threading.Timer(interval, refresh).start()

    refresh()



# Example run
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')



