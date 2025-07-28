from flask import Flask, jsonify, request, render_template
import json
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta
import random
import subprocess
import time
from urllib.parse import urlparse

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
PARTICIPANTS_CACHE = {'last_time': 0, 'data': []}  # In-memory cache for participants
EDISTO_EVENTS_CACHE = {"last_time": 0, "data": []}
EDISTO_PARTICIPANT_CACHE = {"last_time": 0, "data": []}

def normalize_boat_name(name):
    return name.strip().lower().replace(' ', ' ').replace('\u00a0', ' ')

def cache_boat_image(name, image_url):
    """Download and cache image to static/images/boats/, return local path."""
    safe_name = name.replace(" ", "_").replace(",", "").replace("/", "_")
    ext = ".jpg" if ".jpg" in image_url.lower() else ".png"
    filename = f"{safe_name}{ext}"
    local_path = os.path.join("static", "images", "boats", filename)
    relative_path = f"/static/images/boats/{filename}"

    if not os.path.exists(local_path):
        try:
            response = requests.get(image_url, timeout=10)
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

def get_current_tournament():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            return settings.get("tournament", "Big Rock").lower()
    except Exception as e:
        print("⚠️ Could not load tournament from settings:", e)
        return "bigrock"

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
    return {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []}

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

def scrape_edisto_events():
    url = "https://www.reeltimeapps.com/live/tournaments/2025-edisto-invitational-billfish/activities"
    now = time.time()

    if EDISTO_EVENTS_CACHE["data"] and now - EDISTO_EVENTS_CACHE["last_time"] < 60:
        return EDISTO_EVENTS_CACHE["data"]

    events = []

    try:
        participants = scrape_edisto_participants()
        name_to_image = {
            normalize_boat_name(p['name']): p['image']
            for p in participants if p.get('name') and p.get('image')
        }
    except Exception as e:
        print(f"❌ Failed to load Edisto participants: {e}")
        name_to_image = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            print(f"🔗 Navigating to {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#feed-all article", timeout=15000)
            feed_items = page.query_selector_all("#feed-all article")

            print(f"✅ Found {len(feed_items)} Edisto activity items")

            for item in feed_items:
                try:
                    boat = item.query_selector("h4").inner_text().strip()
                    description = item.query_selector("p strong").inner_text().strip()
                    timestamp = item.query_selector("p.pull-right").inner_text().strip()

                    norm_name = normalize_boat_name(boat)
                    image = name_to_image.get(norm_name, "/static/images/placeholder.png")

                    if image == "/static/images/placeholder.png":
                        print(f"⚠️ No image match for: '{boat}' (normalized: '{norm_name}')")

                    events.append({
                        "boat": boat,
                        "message": description,
                        "time": timestamp,
                        "action": description.lower(),
                        "image": image
                    })
                except Exception as e:
                    print(f"⚠️ Failed to parse one item: {e}")

        except Exception as e:
            print(f"❌ Edisto scrape failed: {e}")
        finally:
            context.close()
            browser.close()

    EDISTO_EVENTS_CACHE["data"] = events
    EDISTO_EVENTS_CACHE["last_time"] = now
    return events

def scrape_events(tournament):
    if not check_internet():
        return load_cache(tournament)['events']

    if "edisto" in tournament.lower():
        print(f"🔁 Using Edisto-specific scraper")
        try:
            events = scrape_edisto_events()
            if not events:
                print("No Edisto events found, using cache")
                return load_cache(tournament)['events']
            else:
                cache = load_cache(tournament)
                cache['events'] = events
                save_cache(tournament, cache)
                return events
        except Exception as e:
            print(f"❌ Edisto scrape failed: {e}")
            return load_cache(tournament)['events']

    try:
        url = 'https://tournament.thebigrock.com'
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        print(f"Events response status ({tournament}): {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        boat_hookups = {}
        for item in soup.select('.event-item, .entry-content p, .activity-feed, .recap, .hookups'):
            text = item.get_text(strip=True)
            if 'released' in text.lower() or 'boated' in text.lower() or 'hooked' in text.lower() or 'pulled hook' in text.lower() or 'wrong species' in text.lower():
                if tournament == 'KWLA' and 'KWLA' not in text:
                    continue
                if tournament == 'Big Rock' and 'KWLA' in text:
                    continue
                if tournament == 'Kids' in text.lower():
                    continue
                parts = text.split(' ')
                time_str = parts[0] if parts[0].startswith('07/') else '2025-07-14'
                participants = scrape_bigrock_participants()
                boat_names = [p['name'] for p in participants if p.get('name')]
                boat = next((part for part in parts if part in boat_names), '')
                action = next((part for part in parts if part.lower() in ['hooked', 'boated', 'released', 'pulled hook', 'wrong species']), 'Unknown').replace('hooked', 'Hooked Up')
                species = '' if action.lower() in ['hooked up', 'pulled hook', 'wrong species'] else next((part for part in parts if part.lower() in ['marlin', 'dolphin', 'wahoo', 'sailfish']), '')
                eta = '3:30 PM' if action.lower() == 'boated' else ''
                if boat and action:
                    hookup_id = f"{time_str}_{boat}_{len(boat_hookups.get(boat, []))}"
                    if action.lower() == 'hooked up':
                        if boat not in boat_hookups:
                            boat_hookups[boat] = []
                        boat_hookups[boat].append(hookup_id)
                        events.append({'time': time_str, 'boat': boat, 'action': action, 'species': species, 'eta': eta, 'hookup_id': hookup_id})
                    elif action.lower() in ['released', 'boated', 'pulled hook', 'wrong species'] and boat in boat_hookups and boat_hookups[boat]:
                        hookup_id = boat_hookups[boat].pop(0)
                        events.append({'time': time_str, 'boat': boat, 'action': action, 'species': species, 'eta': eta, 'hookup_id': hookup_id})
                        if not boat_hookups[boat]:
                            del boat_hookups[boat]
        if not events:
            print(f"No events found for {tournament}, using cache")
            events = load_cache(tournament)['events']
        else:
            cache = load_cache(tournament)
            cache['events'] = events
            save_cache(tournament, cache)
        return sorted(events, key=lambda x: x['time'])
    except Exception as e:
        print(f"Scraping error (events, {tournament}): {e}")
        settings = load_settings()
        return load_cache(settings['tournament'])['events']

def scrape_bigrock_participants():
    print("🔍 Launching Playwright to scrape Big Rock participants...")
    boats = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://thebigrock.com/participants", wait_until="networkidle", timeout=30000)
            page.wait_for_selector("img", timeout=15000)

            entries = page.evaluate("""
                () => {
                    const entries = [];
                    document.querySelectorAll('img').forEach(img => {
                        const src = img.getAttribute('src');
                        const parent = img.closest('div');
                        const nameTag = parent?.querySelector('h2, h3, h4, .name, .title');
                        const name = nameTag?.textContent?.trim();
                        if (src && name) {
                            entries.push({ name, image: src.startsWith('http') ? src : 'https:' + src });
                        }
                    });
                    return entries;
                }
            """)
            browser.close()

            for entry in entries:
                local_image = cache_boat_image(entry['name'], entry['image'])
                boats.append({"name": entry['name'], "image": local_image})

            print(f"✅ Scraped and cached {len(boats)} Big Rock participants")
            return boats

    except Exception as e:
        print(f"❌ Playwright error for Big Rock: {e}")
        return []

def scrape_edisto_participants():
    now = time.time()
    if EDISTO_PARTICIPANT_CACHE["data"] and now - EDISTO_PARTICIPANT_CACHE["last_time"] < 600:
        return EDISTO_PARTICIPANT_CACHE["data"]

    with sync_playwright() as p:
        print("🌐 Navigating to Edisto participants page...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.reeltimeapps.com/live/tournaments/2025-edisto-invitational-billfish/participants",
                  wait_until="domcontentloaded", timeout=30000)

        html = page.content()
        browser.close()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.col-sm-3.col-md-3.col-lg-3")
        print(f"✅ Found {len(cards)} cards")

        boats = []
        for card in cards:
            name_tag = card.select_one("h2.post-title")
            img_tag = card.select_one("img.img-responsive")

            if name_tag and img_tag:
                name = name_tag.text.strip()
                img_url = img_tag["src"].strip()

                if "avatar_placeholders" in img_url:
                    continue  # skip default avatars

                local_image = cache_boat_image(name, img_url)
                boats.append({"name": name, "image": local_image})

        print(f"📋 Finalized Edisto Boat List ({len(boats)})")

        EDISTO_PARTICIPANT_CACHE["data"] = boats
        EDISTO_PARTICIPANT_CACHE["last_time"] = now
        return boats

def scrape_participants_dynamic(tournament):
    current_time = time.time()
    if current_time - PARTICIPANTS_CACHE['last_time'] < 60 and PARTICIPANTS_CACHE['data']:
        return PARTICIPANTS_CACHE['data']
    if not PLAYWRIGHT_AVAILABLE:
        print("Playwright not available, using cached participants")
        if os.path.exists(PARTICIPANTS_CACHE_FILE):
            with open(PARTICIPANTS_CACHE_FILE, 'r') as f:
                return json.load(f)
        return []
    try:
        if "edisto" in tournament.lower():
            boats = scrape_edisto_participants()
        else:
            boats = scrape_bigrock_participants()
        PARTICIPANTS_CACHE['data'] = boats
        PARTICIPANTS_CACHE['last_time'] = current_time
        with open(PARTICIPANTS_CACHE_FILE, 'w') as f:
            json.dump(boats, f)
        return boats
    except Exception as e:
        print(f"Error scraping participants dynamically: {e}")
        if os.path.exists(PARTICIPANTS_CACHE_FILE):
            with open(PARTICIPANTS_CACHE_FILE, 'r') as f:
                return json.load(f)
        return []

def generate_demo_events(tournament):
    participants = load_mock_data(tournament)['participants']
    boats = [p['name'] for p in participants if p['name']] if participants else [
        "Demo Boat A", "Demo Boat B", "Demo Boat C", "Demo Boat D"
    ]
    if not boats:
        print("No participants for demo, using fallback boats")
        boats = ["Demo Boat A", "Demo Boat B", "Demo Boat C", "Demo Boat D"]
    actions = ['Released', 'Boated', 'Pulled Hook', 'Wrong Species']
    action_weights = [0.5, 0.167, 0.25, 0.083]
    species = ['Blue Marlin', 'White Marlin', 'Sailfish', 'Dolphin', 'Wahoo']
    events = []
    boat_hookups = {}
    for boat in boats:
        num_hookups = random.randint(1, 3)
        for i in range(num_hookups):
            hour = random.randint(9, 14)
            minute = random.randint(0, 59)
            time_str = f"2025-07-14 {hour:02d}:{minute:02d}"
            hookup_id = f"{time_str}_{boat}_{i}"
            if boat not in boat_hookups:
                boat_hookups[boat] = []
            boat_hookups[boat].append(hookup_id)
            events.append({'time': time_str, 'boat': boat, 'action': 'Hooked Up', 'species': '', 'eta': '', 'hookup_id': hookup_id})
            follow_up_hour = hour + random.randint(0, 1)
            follow_up_minute = random.randint(0, 59)
            follow_up_time = f"2025-07-14 {follow_up_hour:02d}:{follow_up_minute:02d}"
            follow_up_action = random.choices(actions, weights=action_weights, k=1)[0]
            species_choice = '' if follow_up_action in ['Pulled Hook', 'Wrong Species'] else random.choice(species)
            eta = f"{follow_up_hour + 1}:{random.randint(0, 59):02d} PM" if follow_up_action == 'Boated' else ''
            boat_hookups[boat].remove(hookup_id)
            events.append({'time': follow_up_time, 'boat': boat, 'action': follow_up_action, 'species': species_choice, 'eta': eta, 'hookup_id': hookup_id})
    for boat in boats[0:2]:
        hour = random.randint(9, 14)
        minute = random.randint(0, 59)
        time_str = f"2025-07-14 {hour:02d}:{minute:02d}"
        hookup_id = f"{time_str}_{boat}_extra"
        boat_hookups[boat].append(hookup_id)
        events.append({'time': time_str, 'boat': boat, 'action': 'Hooked Up', 'species': '', 'eta': '', 'hookup_id': hookup_id})
    print(f"Generated demo events for {tournament}: {len(events)} events")
    return sorted(events, key=lambda x: x['time'])

def scrape_leaderboard(tournament):
    if not check_internet():
        return load_cache(tournament)['leaderboard']
    try:
        url_map = {
            'Big Rock': 'https://thebigrock.com/leaderboards/',
            'Kids': 'https://thebigrock.com/big-rock-kids-leaderboards/',
            'KWLA': 'https://thebigrock.com/kwla-leaderboards/'
        }
        url = url_map.get(tournament, 'https://thebigrock.com/big-rock-kids-leaderboards/')
        response = requests.get(url, timeout=5)
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

def scrape_gallery():
    if not check_internet():
        settings = load_settings()
        return load_cache(settings['tournament'])['gallery']
    try:
        url = 'https://thebigrock.smugmug.com/2025-GALLERY'
        response = requests.get(url, timeout=5)
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

@app.route('/')
def index():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock").lower().replace(" ", "-")
            logo_url = settings.get("logo_url", "")
    except:
        tournament = "big-rock"
        logo_url = ""

    theme_class = f"theme-{tournament}"
    return render_template("index.html", theme_class=theme_class, logo_url=logo_url)

@app.route('/settings-page')
def settings_page():
    return app.send_static_file('settings.html')

@app.route("/participants")
def participants_page():
    return app.send_static_file("participants.html")

@app.route('/api/participants')
def get_participants():
    now = time.time()
    if PARTICIPANTS_CACHE['data'] and now - PARTICIPANTS_CACHE['last_time'] < 300:
        return jsonify(PARTICIPANTS_CACHE['data'])

    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock").lower()
    except Exception as e:
        print(f"⚠️ Failed to load settings.json: {e}")
        tournament = "big rock"

    print(f"🎯 Using tournament: {tournament}")

    if "edisto" in tournament:
        print("🔁 Running Edisto participant scraper...")
        data = scrape_edisto_participants()
    else:
        print("🔁 Running Big Rock participant scraper...")
        data = scrape_bigrock_participants()

    PARTICIPANTS_CACHE['data'] = data
    PARTICIPANTS_CACHE['last_time'] = now
    return jsonify(data)

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
    tournament = settings.get('tournament', 'Kids')
    if settings['data_source'] == 'historical':
        return jsonify(load_historical_data(tournament).get('events', []))
    elif settings['data_source'] == 'demo':
        return jsonify(generate_demo_events(tournament))
    return jsonify(scrape_events(tournament))

@app.route('/leaderboard')
def leaderboard():
    settings = load_settings()
    tournament = settings.get('tournament', 'Kids')
    if settings['data_source'] in ['historical', 'demo']:
        return jsonify(load_historical_data(tournament).get('leaderboard', []))
    return jsonify(scrape_leaderboard(tournament))

@app.route('/hooked')
def hooked():
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
        if event['action'].lower() == 'hooked up'
        and event['hookup_id'] not in [
            e['hookup_id'] for e in events
            if e['action'].lower() in ['released', 'boated', 'pulled hook', 'wrong species']
        ]
    ])

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
    return jsonify([event for event in events if event['action'].lower() == 'boated' and event.get('eta')])

@app.route('/api/events')
def get_events():
    tournament = get_current_tournament()
    print(f"🎯 Loading events for: {tournament}")

    if "edisto" in tournament:
        return jsonify(scrape_edisto_events())

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
        settings = request.get_json()
        save_settings(settings)
        return jsonify({'status': 'success'})
    return jsonify(load_settings())

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
            commands = f"agent on\ndefault-agent\npair {mac}\ntrust {mac}\nconnect {mac}\n"
            subprocess.check_output(['bluetoothctl'], input=commands.encode(), stderr=subprocess.STDOUT)
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

if __name__ == "__main__":
    scrape_edisto_participants()
    import os
    if os.environ.get("FLASK_RUN_FROM_CLI") != "false":
        app.run(host='0.0.0.0', port=5000)
