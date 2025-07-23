
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

app = Flask(__name__) 
SETTINGS_FILE = 'settings.json'
MOCK_DATA_FILE = 'mock_data.json'
HISTORICAL_DATA_FILE = 'historical_data.json'
DEMO_DATA_FILE = 'demo_data.json'
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
# Force default settings on startup
if not os.path.exists(SETTINGS_FILE):
    save_settings({
        'tournament': 'Big Rock',
        'data_source': 'demo',
        'sounds': {'hooked': True, 'released': True, 'boated': True},
        'followed_boats': [],
        'effects_volume': 0.5,
        'radio_volume': 0.5,
        'wifi_ssid': None,
        'wifi_password': None,
        'disable_sleep_mode': False
    })

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
        'tournament': 'Big Rock',
        'wifi_ssid': None,
        'wifi_password': None,
        'data_source': 'demo',
        'disable_sleep_mode': True
    }

def get_events_for_mode():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")
    data_source = settings.get("data_source", "current")

    if data_source == "demo":
        demo = load_demo_data(tournament)
        return filter_demo_events(demo.get("events", []))

    elif data_source == "historical":
        return load_historical_data(tournament).get("events", [])

    else:  # 'current' or default
        return scrape_events(tournament)

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

    if settings.get('data_source') == 'demo':
        tournament = settings.get('tournament')  # <-- ✅ Define it here
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                demo_data = json.load(f)
        except:
            demo_data = {}

        demo_data[tournament] = {
            'events': inject_hooked_up_events(scrape_events(tournament), tournament),
            'leaderboard': scrape_leaderboard(tournament)
        }

        with open(DEMO_DATA_FILE, 'w') as f:
            json.dump(demo_data, f, indent=4)

    

        demo_data[tournament] = {
            'events': inject_hooked_up_events(scrape_events(tournament), tournament),
            'leaderboard': scrape_leaderboard(tournament)
        }

        try:
            with open(DEMO_DATA_FILE, 'w') as f:
                json.dump(demo_data, f, indent=4)
            print(f"✅ Cached demo data for {tournament}")
        except Exception as e:
            print(f"Error writing demo data file: {e}")


    demo_data[tournament] = {
        'events': inject_hooked_up_events(scrape_events(tournament), tournament),
        'leaderboard': scrape_leaderboard(tournament)
    }

    try:
        with open(DEMO_DATA_FILE, 'w') as f:
            json.dump(demo_data, f, indent=4)
        print(f"✅ Cached demo data for {tournament}")
    except Exception as e:
        print(f"Error writing demo data file: {e}")



from copy import deepcopy

import json
import random
from datetime import datetime, timedelta
from copy import deepcopy

from copy import deepcopy
from datetime import datetime, timedelta
import random
import json

def inject_hooked_up_events(events, tournament_uid):
    # Load participants master data
    with open('participants_master.json') as f:
        participants = json.load(f)

    # Map for quick lookup
    boat_image_map = {p['boat'].strip().upper(): p['image'] for p in participants if 'image' in p}

    resolution_keywords = ['released', 'boated', 'pulled hook', 'wrong species']
    injected = []

    for event in events:
        boat = event.get('boat', '').strip()
        if not boat:
            continue

        # ✅ Only inject "hooked up" if this is a known resolution event
        action = event.get('action', '').lower()
        if not any(keyword in action for keyword in resolution_keywords):
            injected.append(event)  # include it, but don't prepend a hookup
            continue

        # Parse event time safely
        try:
            event_dt = datetime.fromisoformat(event['time'])
        except Exception:
            try:
                from dateutil import parser
                event_dt = parser.parse(event['time'].replace("@", " "))
            except:
                event_dt = datetime.now()

        delta = timedelta(minutes=random.randint(10, 30))
        hooked_dt = event_dt - delta
        hooked_time = hooked_dt.isoformat()
        hookup_id = f"{boat.lower().replace(' ', '_')}_{int(hooked_dt.timestamp())}"
        image = boat_image_map.get(boat.upper(), "/static/images/placeholder.png")

        # Inject "hooked up" event
        hooked_event = {
            "boat": boat,
            "message": f"{boat} is Hooked Up!",
            "time": hooked_time,
            "action": "hooked up",
            "hookup_id": hookup_id,
            "image": image
        }

        # Patch original event with hookup_id and ISO time
        real_event = deepcopy(event)
        real_event['hookup_id'] = hookup_id
        real_event['time'] = event_dt.isoformat()

        injected.append(hooked_event)
        injected.append(real_event)

    return injected




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
        # Load existing cache if it exists
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        else:
            cache = {}

        # Merge new data with existing data for the tournament
        cache[tournament] = {**cache.get(tournament, {}), **data}

        # Write full updated cache
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=4)
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

def load_demo_data(tournament):
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'leaderboard': []})
        except Exception as e:
            print(f"Error loading demo data: {e}")
    return {'events': [], 'leaderboard': []}

def check_internet():
    try:
        subprocess.check_call(['ping', '-c', '1', '8.8.8.8'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def check_video_trigger():
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
                        const nameTag = container.query_selector('{name_selector}');
                        const imgTag = container.query_selector('{image_selector}');
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


from dateutil import parser

from dateutil import parser
from datetime import datetime

def filter_demo_events(events):
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

            # ✅ Allow future events if they're resolving a hookup
            if event_time <= current_time or (
                event.get("hookup_id") and event.get("action", "").lower() in [
                    "boated", "released", "pulled hook", "wrong species"
                ]
            ):
                filtered.append(event)
        except Exception as e:
            print(f"⚠️ Failed to parse time '{event.get('time', '')}' in event {event}: {e}")
            unparsable_events.append(event)

    # Sort the parsable ones by time
    try:
        filtered.sort(key=lambda e: parser.parse(e['time'].replace("@", " ")), reverse=True)
    except Exception as e:
        print(f"⚠️ Failed to sort events: {e}")

    # Add unparsable events to the end
    filtered.extend(unparsable_events)
    return filtered


def load_demo_data(tournament):
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                data = json.load(f)
                demo_data = data.get(tournament, {'events': [], 'leaderboard': []})
                print(f"✅ Loaded demo data for {tournament}: {len(demo_data['events'])} events")
                return demo_data
        except Exception as e:
            print(f"❌ Error loading demo data for {tournament}: {e}")
    else:
        print(f"⚠️ Demo data file {DEMO_DATA_FILE} does not exist")
    return {'events': [], 'leaderboard': []}


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

import subprocess
from flask import jsonify

import time

@app.route('/wifi/connect', methods=['POST'])
def connect_wifi_vue():
    data = request.get_json()
    ssid = data.get('ssid')
    password = data.get('password', '')

    if not ssid:
        return jsonify({'error': 'SSID is required'}), 400

    try:
        # Check if connection already exists
        existing_connections = subprocess.check_output(['nmcli', '-t', '-f', 'NAME', 'con', 'show'], universal_newlines=True)
        if ssid not in existing_connections:
            args = ['sudo', 'nmcli', 'con', 'add', 'type', 'wifi', 'ifname', 'wlan0', 'con-name', ssid, 'ssid', ssid]
            if password:
                args += ['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password]
            subprocess.run(args, check=True)

        subprocess.run(['sudo', 'nmcli', 'con', 'up', ssid], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': str(e)}), 500




@app.route('/wifi/connect', methods=['POST'])
def connect_wifi_vue():
    data = request.get_json()
    ssid = data.get('ssid')
    password = data.get('password', '')
    if not ssid:
        return jsonify({'error': 'SSID is required'}), 400

    try:
        # Reuse the same connection name to avoid clutter
        subprocess.run(['sudo', 'nmcli', 'con', 'add', 'type', 'wifi', 'ifname', 'wlan0', 'con-name', 'bigrock-wifi', 'ssid', ssid] + 
                       (['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password] if password else []),
                       check=True)
        subprocess.run(['sudo', 'nmcli', 'con', 'up', 'bigrock-wifi'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        return jsonify
@app.route('/events')
def events():
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

@app.route('/leaderboard')
def leaderboard():
    settings = load_settings()
    tournament = settings.get('tournament', 'Big Rock')
    data_source = settings.get('data_source', 'current')
    if data_source == 'historical':
        return jsonify(load_historical_data(tournament).get('leaderboard', []))
    elif data_source == 'demo':
        return jsonify(load_demo_data(tournament).get('leaderboard', []))
    else:
        return jsonify(scrape_leaderboard(tournament))

from dateutil import parser

from datetime import datetime

@app.route('/hooked')
def hooked():
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

    # Show remaining hooked events
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
    return jsonify(get_events_for_mode())

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

        old_settings = load_settings()
        save_settings(settings_data)

               # ✅ Always write demo data when tournament or data source changes
        if old_settings.get('tournament') != settings_data.get('tournament') or old_settings.get('data_source') != settings_data.get('data_source'):
            tournament = settings_data.get('tournament', 'Big Rock')
            demo_data = {}

            # Load existing demo data if it exists
            if os.path.exists(DEMO_DATA_FILE):
                try:
                    with open(DEMO_DATA_FILE, 'r') as f:
                        demo_data = json.load(f)
                except Exception as e:
                    print(f"Error loading demo data: {e}")

            # ✅ Generate new events and leaderboard for demo
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


            # ✅ Generate new events and leaderboard for demo
            demo_data[tournament] = {
                'events': inject_hooked_up_events(scrape_events(tournament)),
                'leaderboard': scrape_leaderboard(tournament)
            }

            try:
                with open(DEMO_DATA_FILE, 'w') as f:
                    json.dump(demo_data, f, indent=4)
                print(f"✅ Cached demo data for {tournament}")
            except Exception as e:
                print(f"Error saving demo data: {e}")

        return jsonify({'status': 'success'})
    
    # GET: return current settings
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
            return jupytext({'status': 'success'})
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
