```python
import json
import os
import time
import random
import threading
import subprocess
import requests
from datetime import datetime, timedelta
from copy import deepcopy
from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError
from dateutil import parser
import re

# Check Playwright availability
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Check D-Bus availability
try:
    import dbus
    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False

print("App starting... PLAYWRIGHT_AVAILABLE:", PLAYWRIGHT_AVAILABLE, "DBUS_AVAILABLE:", DBUS_AVAILABLE)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for API routes

# File paths
SETTINGS_FILE = 'settings.json'
MOCK_DATA_FILE = 'mock_data.json'
HISTORICAL_DATA_FILE = 'historical_data.json'
DEMO_DATA_FILE = 'demo_data.json'
CACHE_FILE = 'cache.json'
PARTICIPANTS_MASTER_FILE = 'participants_master.json'

# Global caches
EVENTS_CACHES = {}  # tournament_key: {"last_time": 0, "data": []}
PARTICIPANTS_CACHES = {}  # tournament_key: {"last_time": 0, "data": []}
REMOTE_SETTINGS_CACHE = {"last_fetch": 0, "data": {}}
REMOTE_SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"
bluetooth_status_cache = {'timestamp': 0, 'status': 'Not Connected'}
known_boat_images = {}

# Initialize default settings if not present
if not os.path.exists(SETTINGS_FILE):
    default_settings = {
        'tournament': 'Big Rock',
        'data_source': 'demo',
        'sounds': {'hooked': True, 'released': True, 'boated': True},
        'followed_boats': [],
        'effects_volume': 0.5,
        'radio_volume': 0.5,
        'wifi_ssid': None,
        'wifi_password': None,
        'disable_sleep_mode': False
    }
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(default_settings, f, indent=4)

def get_version():
    """Read version from version.txt or return 'dev' if not found."""
    try:
        with open("version.txt") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

def normalize_boat_name(name):
    """Normalize boat name for consistent formatting."""
    return name.strip().lower()\
        .replace(',', '')\
        .replace(' ', '_')\
        .replace('-', '_')\
        .replace('__', '_')

def cache_boat_image(name, image_url):
    """Download and cache image to static/images/boats/, return local path."""
    safe_name = normalize_boat_name(name)
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ('_', '-'))
    ext = ".jpg" if ".jpg" in image_url.lower() else ".png"
    filename = f"{safe_name}{ext}"
    local_path = os.path.join("static", "images", "boats", filename)
    relative_path = f"/static/images/boats/{filename}"

    if not os.path.exists(local_path):
        try:
            response = requests.get(image_url, timeout=10, verify=False)
            if response.status_code == 200:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(response.content)
                print(f"📥 Cached image for {name}")
            else:
                print(f"⚠️ Failed to download image for {name}: HTTP {response.status_code}")
                return "/static/images/placeholder.png"
        except Exception as e:
            print(f"⚠️ Error downloading image for {name}: {e}")
            return "/static/images/placeholder.png"
    return relative_path

def load_remote_settings(force=False):
    """Load remote settings from URL, cache for 5 minutes."""
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

def scrape_events(tournament):
    """Scrape events for a tournament using Playwright."""
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
    EVENTS_CACHES.setdefault(cache_key, {"last_time": 0, "data": []})
    cache = EVENTS_CACHES[cache_key]
    now = time.time()
    if cache["data"] and now - cache["last_time"] < 300:
        return cache["data"]

    events = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                ignore_https_errors=True
            )
            page = context.new_page()
            print(f"🔗 Navigating to {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            try:
                page.wait_for_selector("#feed-all article", timeout=60000)
            except TimeoutError:
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
    """Get the current tournament from settings."""
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            return settings.get("tournament", "Big Rock")
    except Exception as e:
        print(f"⚠️ Could not load tournament from settings: {e}")
        return "Big Rock"

def generate_uid(tournament, name):
    """Generate a unique ID for a participant."""
    return f"{tournament.lower().replace(' ', '_')}_{normalize_boat_name(name).replace(' ', '_')}"

def save_participant_to_master(entry):
    """Save participant to master file."""
    data = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️ Corrupt participants master file: {PARTICIPANTS_MASTER_FILE}")
    if not any(p["uid"] == entry["uid"] for p in data):
        data.append(entry)
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving to participants master file: {e}")

def get_mac_address():
    """Get last 4 digits of wlan0 MAC address."""
    try:
        mac = subprocess.check_output(['cat', '/sys/class/net/wlan0/address']).decode().strip().replace(':', '')[-4:].lower()
        return mac
    except Exception as e:
        print(f"Error getting MAC address: {e}")
        return '0000'

def load_settings():
    """Load settings from file or return defaults."""
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
        'tournament': 'Big Rock',
        'wifi_ssid': None,
        'wifi_password': None,
        'data_source': 'demo',
        'disable_sleep_mode': True
    }

def save_settings(settings):
    """Save settings to file and update demo data if needed."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

    if settings.get('data_source') == 'n/a':
        tournament = settings.get('tournament', 'Big Rock')
        demo_data = {}
        if os.path.exists(DEMO_DATA_FILE):
            try:
                with open(DEMO_DATA_FILE, 'r') as f:
                    demo_data = json.load(f)
            except Exception as e:
                print(f"Error loading demo data: {e}")

        demo_data[tournament] = {
            'events': inject_hooked_up_events(scrape_events(tournament), tournament),
            'leaderboard': scrape_leaderboard(tournament)
        }
        try:
            with open(DEMO_DATA_FILE, 'w') as f:
                json.dump(demo_data, f, indent=4)
            print(f"✅ Cached demo data for {tournament}")
        except Exception as e:
            print(f"Error saving demo data: {e}")

def get_events_for_mode():
    """Get events based on the data source mode."""
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")
    data_source = settings.get("data_source", "current")

    if data_source == "demo":
        demo = load_demo_data(tournament)
        return filter_demo_events(demo.get("events", []))
    elif data_source == "historical":
        return load_historical_data(tournament).get("events", [])
    else:
        return scrape_events(tournament)

def inject_hooked_up_events(events, tournament_uid):
    """Inject 'hooked up' events before resolution events."""
    try:
        with open(PARTICIPANTS_MASTER_FILE) as f:
            participants = json.load(f)
    except Exception as e:
        print(f"Error loading participants master: {e}")
        participants = []

    boat_image_map = {p['boat'].strip().upper(): p['image'] for p in participants if 'image' in p}
    resolution_keywords = ['released', 'boated', 'pulled hook', 'wrong species']
    injected = []

    for event in events:
        boat = event.get('boat', '').strip()
        if not boat:
            continue

        action = event.get('action', '').lower()
        if not any(keyword in action for keyword in resolution_keywords):
            injected.append(event)
            continue

        try:
            event_dt = datetime.fromisoformat(event['time'])
        except Exception:
            try:
                event_dt = parser.parse(event['time'].replace("@", " "))
            except:
                event_dt = datetime.now()

        delta = timedelta(minutes=random.randint(10, 30))
        hooked_dt = event_dt - delta
        hooked_time = hooked_dt.isoformat()
        hookup_id = f"{boat.lower().replace(' ', '_')}_{int(hooked_dt.timestamp())}"
        image = boat_image_map.get(boat.upper(), "/static/images/placeholder.png")

        hooked_event = {
            "boat": boat,
            "message": f"{boat} is Hooked Up!",
            "time": hooked_time,
            "action": "hooked up",
            "hookup_id": hookup_id,
            "image": image
        }
        real_event = deepcopy(event)
        real_event['hookup_id'] = hookup_id
        real_event['time'] = event_dt.isoformat()

        injected.append(hooked_event)
        injected.append(real_event)

    return injected

def load_cache(tournament):
    """Load cached data for a tournament."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            print(f"Error loading cache: {e}")
    return load_mock_data(tournament)

def save_cache(tournament, data):
    """Save data to cache file."""
    try:
        cache = {}
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        cache[tournament] = {**cache.get(tournament, {}), **data}
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=4)
    except Exception as e:
        print(f"Error saving cache: {e}")

def load_mock_data(tournament):
    """Load mock data for testing."""
    if os.path.exists(MOCK_DATA_FILE):
        try:
            with open(MOCK_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            print(f"Error loading mock data: {e}")
    participants = [{'name': name, 'image': image} for name, image in known_boat_images.items()]
    return {'events': [], 'participants': participants, 'leaderboard': [], 'gallery': []}

def load_historical_data(tournament):
    """Load historical data for a tournament."""
    if os.path.exists(HISTORICAL_DATA_FILE):
        try:
            with open(HISTORICAL_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            print(f"Error loading historical data: {e}")
    return {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []}

def load_demo_data(tournament):
    """Load demo data for a tournament."""
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                data = json.load(f)
                demo_data = data.get(tournament, {'events': [], 'leaderboard': []})
                print(f"✅ Loaded demo data for {tournament}: {len(demo_data['events'])} events")
                return demo_data
        except Exception as e:
            print(f"❌ Error loading demo data for {tournament}: {e}")
    return {'events': [], 'leaderboard': []}

def check_internet():
    """Check internet connectivity with a ping to 8.8.8.8."""
    try:
        subprocess.check_call(['ping', '-c', '1', '8.8.8.8'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def check_video_trigger():
    """Check if a video trigger event is active."""
    settings = load_settings()
    tournament = settings.get('tournament', 'Big Rock')
    events = get_events_for_mode()
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

def scrape_participants(tournament):
    """Scrape participant data using Playwright."""
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
    PARTICIPANTS_CACHES.setdefault(cache_key, {"last_time": 0, "data": []})
    cache = PARTICIPANTS_CACHES[cache_key]
    now = time.time()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                ignore_https_errors=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=120000)
            except TimeoutError:
                print(f"❌ Timeout while loading URL: {url}")
                return []

            html_content = page.content()
            print(f"Page HTML snippet for {tournament}:\n{html_content[:500]}...")

            try:
                page.wait_for_selector(".participant, .boat, .entry-list", timeout=30000)
            except TimeoutError:
                print("No participant list found or selector timeout.")
                return []

            exclude_patterns = config.get("exclude_patterns", [",", "2025 Edisto Invitational Billfish"])
            name_selector = config.get(
                "name_selector",
                "h1, h2, h3, h4, h5, h6, span.name, div.name, p.name, .participant-name, .title, .boat-name"
            )
            image_selector = config.get("image_selector", "img")

            entries = page.evaluate("""
                (nameSel, imgSel) => {
                    const boats = [];
                    const participantContainers = document.querySelectorAll('div.boat-entry, li.boat, article.boat, section.boat, div, li, article, section');
                    participantContainers.forEach(container => {
                        const nameTag = container.querySelector(nameSel);
                        const imgTag = container.querySelector(imgSel);
                        const name = nameTag?.textContent?.trim();
                        let image = imgTag?.getAttribute('src') || imgTag?.getAttribute('data-src');
                        if (image && !image.startsWith('http')) {
                            image = `https:${image}`;
                        }
                        if (name) {
                            boats.push({ name, image: image || '' });
                        }
                    });
                    return boats;
                }
            """, [name_selector, image_selector])

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

def filter_demo_events(events):
    """Filter demo events to include only past events or resolution events."""
    current_time = datetime.now().time()
    filtered = []
    unparsable_events = []

    for event in events:
        if not isinstance(event, dict) or 'time' not in event or 'action' not in event:
            print(f"⚠️ Invalid event structure: {event}")
            continue
        try:
            event_time_str = event['time'].replace("@", " ")
            event_dt = parser.parse(event_time_str)
            event_time = event_dt.time()

            if event_time <= current_time or (
                event.get("hookup_id") and event.get("action", "").lower() in [
                    "boated", "released", "pulled hook", "wrong species"
                ]
            ):
                filtered.append(event)
        except Exception as e:
            print(f"⚠️ Failed to parse time '{event.get('time', '')}' in event {event}: {e}")
            unparsable_events.append(event)

    try:
        filtered.sort(key=lambda e: parser.parse(e['time'].replace("@", " ")), reverse=True)
    except Exception as e:
        print(f"⚠️ Failed to sort events: {e}")

    filtered.extend(unparsable_events)
    return filtered

def scrape_leaderboard(tournament):
    """Scrape leaderboard data for a tournament."""
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
        rows = soup.select('table.table-striped tr')

        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 3:
                place = cols[0].get_text(strip=True)
                boat_name = cols[1].find('h4')
                boat = boat_name.get_text(strip=True) if boat_name else cols[1].get_text(strip=True)
                points_span = cols[2].select_one('span.label')
                points = points_span.get_text(strip=True) if points_span else cols[2].get_text(strip=True)
                leaderboard.append({
                    'place': place,
                    'boat': boat,
                    'points': points
                })

        if not leaderboard:
            print(f"No leaderboard found for {tournament}, using cache")
            return load_cache(tournament)['leaderboard']

        cache = load_cache(tournament)
        cache['leaderboard'] = leaderboard
        save_cache(tournament, cache)
        return leaderboard
    except Exception as e:
        print(f"Scraping error (leaderboard, {tournament}): {e}")
        return load_cache(tournament)['leaderboard']

def scrape_gallery():
    """Scrape gallery images from a specific URL."""
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

# Routes
@app.route('/')
def index():
    """Render the main index page."""
    try:
        with open(SETTINGS_FILE, "r") as f:
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
    """Serve the settings page."""
    return app.send_static_file('settings.html')

@app.route("/participants")
def participants_page():
    """Serve the participants page."""
    return app.send_static_file("participants.html")

@app.route('/api/participants')
def get_participants():
    """Get participants for the current tournament."""
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except Exception as e:
        print(f"⚠️ Failed to load settings.json: {e}")
        tournament = "Big Rock"

    print(f"🎯 Using tournament: {tournament}")
    prefix = tournament.lower().replace(" ", "_")
    all_participants = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                all_participants = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Master participant file is corrupt or empty.")

    filtered = [p for p in all_participants if p['uid'].startswith(prefix)]
    if not filtered:
        print(f"⚠️ No participants found for '{prefix}', scraping...")
        scrape_participants(tournament)
        if os.path.exists(PARTICIPANTS_MASTER_FILE):
            try:
                with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                    all_participants = json.load(f)
                    filtered = [p for p in all_participants if p['uid'].startswith(prefix)]
            except json.JSONDecodeError:
                print("⚠️ Master file still broken after scrape.")

    return jsonify(filtered)

@app.route('/wifi', methods=['GET', 'POST'])
def wifi():
    """Handle WiFi configuration."""
    if request.method == 'POST':
        ssid = request.form.get('ssid')
        password = request.form.get('password')
        settings = load_settings()
        settings['wifi_ssid'] = ssid
        settings['wifi_password'] = password
        save_settings(settings)
        try:
            connect_args = ['sudo', 'nmcli', 'con', 'add', 'type', 'wifi', 'ifname', 'wlan0', 'con-name', 'bigrock-wifi', 'ssid', ssid]
            if password:
                connect_args += ['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password]
            subprocess.run(connect_args, check=True)
            subprocess.run(['sudo', 'nmcli', 'con', 'up', 'bigrock-wifi'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
            return jsonify({'status': 'success'})
        except subprocess.CalledProcessError as e:
            print(f"Error connecting to WiFi: {e}")
            return jsonify({'status': 'error', 'message': str(e)})
    return render_template('wifi.html')

@app.route('/wifi/scan')
def scan_wifi():
    """Scan available WiFi networks."""
    try:
        subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=False)
        subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=False)
        time.sleep(2)
        subprocess.run(['sudo', 'nmcli', 'device', 'wifi', 'rescan'], check=True)
        output = subprocess.check_output(
            ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list'],
            universal_newlines=True
        )
        networks = []
        for line in output.strip().split('\n'):
            parts = line.strip().split(':')
            if len(parts) >= 3 and parts[0]:
                networks.append({
                    'ssid': parts[0],
                    'signal': int(parts[1]),
                    'security': parts[2]
                })
        current_output = subprocess.check_output(
            ['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi'],
            universal_newlines=True
        )
        current_ssid = next((line.split(':')[1] for line in current_output.strip().split('\n') if line.startswith("yes:")), None)
        response = jsonify({'networks': networks, 'current': current_ssid})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    except Exception as e:
        print(f"Wi-Fi scan error: {e}")
        response = jsonify({'error': str(e)})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/wifi/connect', methods=['POST'])
def connect_wifi_vue():
    """Connect to a WiFi network via JSON request."""
    data = request.get_json()
    ssid = data.get('ssid')
    password = data.get('password', '')
    if not ssid:
        return jsonify({'error': 'SSID is required'}), 400

    try:
        connect_cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]
        if password:
            connect_cmd += ['password', password]
        subprocess.run(connect_cmd, check=True)
        time.sleep(3)
        verify = subprocess.check_output(['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi'], universal_newlines=True)
        current = [line.split(':')[1] for line in verify.strip().split('\n') if line.startswith('yes:')]
        if ssid in current:
            for svc in ['hostapd', 'dnsmasq']:
                try:
                    subprocess.run(['systemctl', 'stop', svc], check=True)
                except subprocess.CalledProcessError:
                    pass
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': f'{ssid} not reported as active'}), 500
    except subprocess.CalledProcessError as e:
        print(f"Wi-Fi connect error: {e}")
        return jsonify({'error': f'nmcli failed: {e}'}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({'error': f'Unexpected error: {e}'}), 500

@app.route('/wifi/disconnect', methods=['POST'])
def wifi_disconnect():
    """Disconnect from the current WiFi network."""
    try:
        subprocess.run(['sudo', 'nmcli', 'con', 'down', 'bigrock-wifi'], check=True)
        subprocess.run(['sudo', 'nmcli', 'con', 'delete', 'bigrock-wifi'], check=False)
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/events')
def events():
    """Get enriched events for the current tournament."""
    try:
        events = get_events_for_mode()
        settings = load_settings()
        tournament = settings.get("tournament", "Big Rock")
        prefix = tournament.lower().replace(" ", "_")

        if os.path.exists(PARTICIPANTS_MASTER_FILE):
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                participants = json.load(f)
            name_to_image = {
                normalize_boat_name(p['boat']): p['image']
                for p in participants
                if p['uid'].startswith(prefix)
            }
            for e in events:
                norm_name = normalize_boat_name(e['boat'])
                e['image'] = name_to_image.get(norm_name, "/static/images/placeholder.png")
        else:
            print(f"⚠️ No participant master file found at {PARTICIPANTS_MASTER_FILE}")

        print(f"✅ Returning {len(events)} enriched events for {tournament}")
        return jsonify(events)
    except Exception as e:
        print(f"❌ Error in /events route: {e}")
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

@app.route('/hooked')
def hooked():
    """Get currently hooked boats, filtering out resolved events."""
    events = get_events_for_mode()
    now = datetime.now()
    current_year = now.year

    def parse_event_time(e):
        try:
            dt = parser.parse(e['time'].replace("@", " "))
            return dt.replace(year=current_year)
        except:
            return None

    resolution_keywords = ['released', 'boated', 'pulled hook', 'wrong species']
    resolved_ids = set()
    for e in events:
        if not e.get("hookup_id"):
            continue
        action = e.get("action", "").lower()
        if not any(keyword in action for keyword in resolution_keywords):
            continue
        event_time = parse_event_time(e)
        if not event_time:
            print(f"⚠️ Unparsable time: {e['time']}")
            continue
        if event_time <= now:
            resolved_ids.add(e['hookup_id'])
            print(f"✅ Resolved: {e['hookup_id']} via {e['action']}")

    hooked = []
    for e in events:
        if e.get('action', '').lower() != 'hooked up':
            continue
        if e.get('hookup_id') in resolved_ids:
            print(f"❌ Removing resolved hookup: {e['hookup_id']}")
            continue
        event_time = parse_event_time(e)
        if event_time and event_time <= now:
            hooked.append(e)

    print(f"🎣 Hooked boats count: {len(hooked)}")
    return jsonify(hooked)

@app.route('/scales')
def scales():
    """Get events related to boats headed to scales."""
    try:
        events = get_events_for_mode()
        scales_events = [
            event for event in events
            if isinstance(event, dict) and event.get('action', '').lower() == 'headed to scales'
        ]
        print(f"✅ Returning {len(scales_events)} scales events for {get_current_tournament()}")
        return jsonify(scales_events)
    except Exception as e:
        print(f"❌ Error in /scales endpoint: {e}")
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

@app.route('/api/events')
def get_events():
    """Get events for the current mode."""
    return jsonify(get_events_for_mode())

@app.route('/gallery')
def gallery():
    """Get gallery images."""
    return jsonify(scrape_gallery())

@app.route('/check-video-trigger')
def check_video_trigger_endpoint():
    """Check for video trigger events."""
    return jsonify(check_video_trigger())

@app.route('/wifi-status')
def wifi_status():
    """Check internet connectivity status."""
    return jsonify({'connected': check_internet()})

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Handle settings GET and POST requests."""
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
        old_settings = load_settings()
        save_settings(settings_data)
        if old_settings.get('tournament') != settings_data.get('tournament') or old_settings.get('data_source') != settings_data.get('data_source'):
            tournament = settings_data.get('tournament', 'Big Rock')
            demo_data = {}
            if os.path.exists(DEMO_DATA_FILE):
                try:
                    with open(DEMO_DATA_FILE, 'r') as f:
                        demo_data = json.load(f)
                except Exception as e:
                    print(f"Error loading demo data: {e}")
            demo_data[tournament] = {
                'events': inject_hooked_up_events(scrape_events(tournament), tournament),
                'leaderboard': scrape_leaderboard(tournament)
            }
            try:
                with open(DEMO_DATA_FILE, 'w') as f:
                    json.dump(demo_data, f, indent=4)
                print(f"✅ Cached demo data for {tournament}")
            except Exception as e:
                print(f"Error saving demo data: {e}")
        return jsonify({'status': 'success'})
    return jsonify(load_settings())

@app.route('/bluetooth-status')
def bluetooth_status():
    """Check Bluetooth connection status."""
    now = time.time()
    if now - bluetooth_status_cache['timestamp'] < 10:
        return jsonify({'status': bluetooth_status_cache['status']})

    status = 'Not Connected'
    if DBUS_AVAILABLE:
        try:
            bus = dbus.SystemBus()
            bluez = bus.get_object('org.bluez', '/')
            manager = dbus.Interface(bluez, 'org.freedesktop.DBus.ObjectManager')
            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    props = interfaces['org.bluez.Device1']
                    if props.get('Connected', False):
                        name = props.get('Name', 'Bluetooth Device')
                        status = f"Connected to {name}"
                        break
        except Exception as e:
            print(f"Bluetooth status error (D-Bus): {e}")
            status = 'Not Connected'
    else:
        try:
            devices_output = subprocess.check_output(['bluetoothctl', 'devices'], stderr=subprocess.DEVNULL, text=True).strip()
            if not devices_output:
                status = 'Not Connected'
            else:
                device_lines = devices_output.split('\n')
                first_device = None
                for line in device_lines:
                    parts = line.split(' ', 2)
                    if len(parts) >= 2 and parts[0] == 'Device':
                        first_device = parts[1]
                        break
                if first_device:
                    info_output = subprocess.check_output(['bluetoothctl', 'info', first_device], stderr=subprocess.DEVNULL, text=True)
                    if 'Connected: yes' in info_output:
                        name = 'Bluetooth Device'
                        for line in info_output.split('\n'):
                            if line.strip().startswith('Name:'):
                                name = line.split(':', 1)[1].strip()
                                break
                        status = f"Connected to {name}"
        except subprocess.CalledProcessError as e:
            print(f"Bluetooth command failed: {e}")
            status = 'Not Connected'
        except Exception as e:
            print(f"Bluetooth status error (subprocess): {e}")
            status = 'Not Connected'

    bluetooth_status_cache['status'] = status
    bluetooth_status_cache['timestamp'] = now
    return jsonify({'status': status})

@app.route('/bluetooth')
def bluetooth():
    """Handle Bluetooth operations: scan, pair, power on/off."""
    action = request.args.get('action')
    if action == 'scan':
        try:
            scan_proc = subprocess.Popen(
                ['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            commands = ['power on', 'agent on', 'default-agent', 'scan on']
            for cmd in commands:
                scan_proc.stdin.write(f"{cmd}\n")
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
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        devices.append({'mac': parts[1], 'name': parts[2]})
            return jsonify(devices)
        except Exception as e:
            print(f"Bluetooth scan error: {e}")
            return jsonify({'status': 'error', 'message': str(e)})
    elif action == 'pair':
        mac = request.args.get('mac')
        if not mac or not re.match(r'^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$', mac):
            return jsonify({'status': 'error', 'message': 'Invalid or missing MAC address'})
        try:
            commands = f"agent on\ndefault-agent\npair {mac}\ntrust {mac}\nconnect {mac}\n"
            subprocess.check_output(['bluetoothctl'], input=commands, stderr=subprocess.STDOUT, text=True)
            mac_underscore = mac.upper().replace(':', '_')
            sinks_output = subprocess.check_output(['wpctl', 'list-sinks'], text=True)
            sink_name = None
            for line in sinks_output.split('\n'):
                if 'bluez' in line and mac_underscore in line:
                    parts = line.split()
                    for part in parts:
                        if mac_underscore in part:
                            sink_name = part
                            break
                    if sink_name:
                        break
            if sink_name:
                subprocess.run(['wpctl', 'set-default', sink_name], check=True)
                subprocess.run(['wpctl', 'set-mute', sink_name, '0'], check=True)
                subprocess.run(['wpctl', 'set-volume', sink_name, '1.0'], check=True)
                return jsonify({'status': 'success', 'output': f'Paired and audio output set to {sink_name}'})
            return jsonify({'status': 'error', 'message': 'Bluetooth sink not found'})
        except subprocess.CalledProcessError as e:
            return jsonify({'status': 'error', 'message': e.output})
        except Exception as e:
            print(f"Bluetooth pair error: {e}")
            return jsonify({'status': 'error', 'message': str(e)})
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
    return jsonify({'status': 'error', 'message': 'Invalid action'})

@app.route('/leaderboard')
def leaderboard():
    """Get leaderboard data for the current tournament."""
    settings = load_settings()
    tournament = settings.get('tournament', 'Big Rock')
    data_source = settings.get('data_source', 'current')
    if data_source == 'historical':
        return jsonify(load_historical_data(tournament).get('leaderboard', []))
    elif data_source == 'demo':
        return jsonify(load_demo_data(tournament).get('leaderboard', []))
    else:
        return jsonify(scrape_leaderboard(tournament))

@app.route('/leaderboard-page')
def leaderboard_page():
    """Serve the leaderboard page."""
    return app.send_static_file('leaderboard.html')

def refresh_data_loop(interval=600):
    """Periodically refresh participants and events."""
    def refresh():
        try:
            print("🔁 Background: Refreshing participants and events...")
            settings = load_settings()
            tournament = settings.get("tournament", "Big Rock")
            scrape_participants(tournament)
            scrape_events(tournament)
        except Exception as e:
            print(f"❌ Background refresh failed: {e}")
        finally:
            threading.Timer(interval, refresh).start()
    refresh()

if __name__ == '__main__':
    refresh_data_loop()  # Start background refresh
    app.run(debug=True, host='0.0.0.0')
```
