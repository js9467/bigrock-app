
from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
import json
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta
import random
import subprocess
import time
import threading
import re
from dateutil import parser
from copy import deepcopy
import logging

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

logger.info(f"App starting... PLAYWRIGHT_AVAILABLE: {PLAYWRIGHT_AVAILABLE}")

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# File paths
SETTINGS_FILE = 'settings.json'
MOCK_DATA_FILE = 'mock_data.json'
HISTORICAL_DATA_FILE = 'historical_data.json'
DEMO_DATA_FILE = 'demo_data.json'
CACHE_FILE = 'cache.json'
PARTICIPANTS_MASTER_FILE = 'participants_master.json'

# Global caches
REMOTE_SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"
REMOTE_SETTINGS_CACHE = {"last_fetch": 0, "data": {}}
EVENTS_CACHES = {}  # tournament_key: {"last_time": 0, "data": []}
PARTICIPANTS_CACHES = {}  # tournament_key: {"last_time": 0, "data": []}
bluetooth_status_cache = {'timestamp': 0, 'status': 'Not Connected'}
scraping_status = {"progress": 0, "message": "Initializing...", "done": False, "error": None}
status_lock = threading.Lock()

def initialize_default_settings():
    """Initialize default settings if settings.json does not exist."""
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
        save_settings(default_settings)
        logger.info("Created default settings file")

def get_version():
    """Retrieve the application version from version.txt."""
    try:
        with open("version.txt", 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

def normalize_boat_name(name):
    if not name:
        return ""
    return name.strip().lower().replace('\u00a0', ' ').replace(' ', ' ') \
        .replace(',', '').replace(' ', '_').replace('-', '_').replace('__', '_')

    if not name:
        return ""
    return name.strip().lower()\
        .replace(',', '')\
        .replace(' ', '_')\
        .replace('-', '_')\
        .replace('__', '_')

def cache_boat_image(name, image_url):
    """Download and cache boat image to static/images/boats/, return local path."""
    safe_name = normalize_boat_name(name)
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ('_', '-'))
    ext = ".jpg" if image_url and ".jpg" in image_url.lower() else ".png"
    filename = f"{safe_name}{ext}"
    local_path = os.path.join("static", "images", "boats", filename)
    relative_path = f"/static/images/boats/{filename}"

    logger.info(f"Caching image for {name}: {image_url}")
    if not image_url or not image_url.startswith(('http://', 'https://')):
        logger.warning(f"Invalid or empty image URL for {name}: '{image_url}'")
        return "/static/images/placeholder.png"

    if not os.path.exists(local_path):
        try:
            response = requests.get(image_url, timeout=10, verify=True)
            logger.info(f"Download response for {name}: HTTP {response.status_code}")
            if response.status_code == 200:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"Cached image for {name} at {local_path}")
            else:
                logger.warning(f"Failed to download image for {name}: HTTP {response.status_code}")
                return "/static/images/placeholder.png"
        except Exception as e:
            logger.error(f"Error downloading image for {name}: {e}", exc_info=True)
            return "/static/images/placeholder.png"
    else:
        logger.info(f"Image already cached for {name}: {local_path}")
    return relative_path

def load_remote_settings(force=False):
    """Load remote settings with caching."""
    now = time.time()
    if not force and now - REMOTE_SETTINGS_CACHE["last_fetch"] < 300:
        return REMOTE_SETTINGS_CACHE["data"]
    try:
        response = requests.get(REMOTE_SETTINGS_URL, timeout=5, verify=True)
        response.raise_for_status()
        data = response.json()
        REMOTE_SETTINGS_CACHE["data"] = data
        REMOTE_SETTINGS_CACHE["last_fetch"] = now
        logger.info("Loaded remote tournament settings")
        return data
    except Exception as e:
        logger.error(f"Failed to load remote settings: {e}", exc_info=True)
        return REMOTE_SETTINGS_CACHE["data"]

def scrape_events(tournament):
    if \"edisto\" in tournament.lower():
        return scrape_edisto_events()
    """Scrape event data for a tournament and cache it."""
    remote = load_remote_settings()
    config = remote.get(tournament, {})
    if not config:
        logger.error(f"No config for tournament: {tournament}")
        return []

    url = config.get("events")
    if not url:
        logger.error(f"No events URL for {tournament} in remote settings")
        return []

    cache_key = tournament.replace(" ", "_").lower()
    if cache_key not in EVENTS_CACHES:
        EVENTS_CACHES[cache_key] = {"last_time": 0, "data": []}

    cache = EVENTS_CACHES[cache_key]
    now = time.time()
    if cache["data"] and now - cache["last_time"] < 300:
        logger.info(f"Using cached events for {tournament}")
        return cache["data"]

    events = []
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available, cannot scrape events")
        return events

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                ignore_https_errors=True
            )
            page = context.new_page()

            logger.info(f"Navigating to {url}")
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                logger.error(f"Failed to load events page: HTTP {response.status}")
                content = page.content()
                with open("events_page_content.html", "w") as f:
                    f.write(content)
                logger.info("Saved events page content to events_page_content.html")
                return events

            logger.info(f"Page loaded with status: {response.status if response else 'unknown'}")

            try:
                page.wait_for_selector("article.entry, div.activity, li.event, div.feed-item", timeout=30000)
                page.wait_for_timeout(5000)
                logger.info("Event selectors found")
            except Exception as e:
                logger.warning(f"No activities found or selector timeout: {e}", exc_info=True)
                content = page.content()
                with open("events_page_content.html", "w") as f:
                    f.write(content)
                logger.info("Saved events page content to events_page_content.html")

            feed_items = page.query_selector_all("article.entry, div.activity, li.event, div.feed-item")
            logger.info(f"Found {len(feed_items)} activity items for {tournament}")

            for item in feed_items:
                try:
                    boat = item.query_selector("h4, span.name, .boat-name, .entry-name") or item
                    boat_text = boat.inner_text().strip() if boat else ""
                    description = item.query_selector("p strong, .description, p.event-text") or item
                    desc_text = description.inner_text().strip() if description else ""
                    timestamp = item.query_selector("p.time, .timestamp, span.time") or item
                    time_text = timestamp.inner_text().strip() if timestamp else ""

                    if boat_text and desc_text:
                        events.append({
                            "boat": boat_text,
                            "message": desc_text,
                            "time": time_text or datetime.now().isoformat(),
                            "action": desc_text.lower(),
                            "image": get_boat_image(tournament, boat_text)
                        })
                except Exception as e:
                    logger.error(f"Failed to parse feed item: {e}", exc_info=True)

            context.close()
            browser.close()
    except Exception as e:
        logger.error(f"Scrape failed for {tournament}: {e}", exc_info=True)
        content = page.content() if 'page' in locals() else ""
        with open("events_page_content.html", "w") as f:
            f.write(content)
        logger.info("Saved events page content to events_page_content.html")

    cache["data"] = events
    cache["last_time"] = now
    logger.info(f"Cached {len(events)} events for {tournament}")
    return events

def get_current_tournament():
    """Get the current tournament from settings."""
    settings = load_settings()
    return settings.get("tournament", "Big Rock")

def generate_uid(tournament, name):
    """Generate a unique ID for a participant."""
    return f"{tournament.lower().replace(' ', '_')}_{normalize_boat_name(name)}"

def save_participant_to_master(participant):
    """Save a participant to participants_master.json if not already present."""
    data = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {PARTICIPANTS_MASTER_FILE}: {e}", exc_info=True)
            data = []

    if not any(p["uid"] == participant["uid"] for p in data):
        data.append(participant)
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved participant {participant['boat']} to {PARTICIPANTS_MASTER_FILE}")
        except Exception as e:
            logger.error(f"Failed to save to {PARTICIPANTS_MASTER_FILE}: {e}", exc_info=True)

def get_boat_image(tournament, boat_name):
    """Retrieve the cached image path for a boat from participants_master.json."""
    prefix = tournament.lower().replace(" ", "_")
    try:
        with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
            participants = json.load(f)
        for participant in participants:
            if participant['uid'].startswith(prefix) and normalize_boat_name(participant['boat']) == normalize_boat_name(boat_name):
                return participant['image']
    except Exception as e:
        logger.warning(f"Error retrieving image for {boat_name}: {e}", exc_info=True)
    return "/static/images/placeholder.png"

def background_init(tournament):
    """Background function to scrape participants and update status."""
    with status_lock:
        scraping_status['message'] = "Starting scraping..."
        scraping_status['progress'] = 0
        scraping_status['done'] = False
        scraping_status['error'] = None
    try:
        initialize_participants(tournament)
        with status_lock:
            scraping_status['done'] = True
            scraping_status['message'] = "Scraping complete"
            scraping_status['progress'] = 100
    except Exception as e:
        logger.error(f"Background scraping failed: {e}", exc_info=True)
        with status_lock:
            scraping_status['done'] = True
            scraping_status['error'] = str(e)
            scraping_status['message'] = "Scraping failed"

def initialize_participants(tournament):
    """Scrape participants and cache images, updating progress."""
    logger.info(f"Initializing participants for {tournament}")
    boats = scrape_participants(tournament)
    logger.info(f"Initialized {len(boats)} participants for {tournament}")
    return boats

def get_mac_address():
    """Get the last 4 characters of the WLAN MAC address."""
    try:
        mac = subprocess.check_output(['cat', '/sys/class/net/wlan0/address']).decode().strip().replace(':', '')[-4:].lower()
        return mac
    except Exception as e:
        logger.error(f"Error getting MAC address: {e}", exc_info=True)
        return '0000'

def load_settings():
    """Load settings from settings.json or return defaults."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading settings: {e}", exc_info=True)
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
    """Save settings to settings.json and update demo data if needed."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        logger.info("Saved settings")
    except Exception as e:
        logger.error(f"Error saving settings: {e}", exc_info=True)

    if settings.get('data_source') == 'demo':
        tournament = settings.get('tournament', 'Big Rock')
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                demo_data = json.load(f)
        except:
            demo_data = {}

        demo_data[tournament] = {
            'events': inject_hooked_up_events(scrape_events(tournament), tournament),
            'leaderboard': scrape_leaderboard(tournament)
        }

        try:
            with open(DEMO_DATA_FILE, 'w') as f:
                json.dump(demo_data, f, indent=4)
            logger.info(f"Cached demo data for {tournament}")
        except Exception as e:
            logger.error(f"Error writing demo data file: {e}", exc_info=True)

def inject_hooked_up_events(events, tournament_uid):
    """Inject synthetic 'hooked up' events for resolution events."""
    if not os.path.exists(PARTICIPANTS_MASTER_FILE):
        logger.warning(f"{PARTICIPANTS_MASTER_FILE} not found — skipping hook injections")
        return events

    try:
        with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
            participants = json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse {PARTICIPANTS_MASTER_FILE}")
        return events

    boat_image_map = {
        p['boat'].strip().upper(): p['image']
        for p in participants
        if p.get("tournament_uid") == tournament_uid and 'image' in p
    }

    resolution_keywords = ['released', 'boated', 'pulled hook', 'wrong species']
    injected = []

    for event in events:
        boat = event.get('boat', '').strip()
        if not boat:
            continue

        action = event.get('action', '').lower()
        event['image'] = boat_image_map.get(boat.upper(), "/static/images/placeholder.png")
        if not any(keyword in action for keyword in resolution_keywords):
            injected.append(event)
            continue

        try:
            event_dt = datetime.fromisoformat(event['time'])
        except Exception:
            try:
                event_dt = parser.parse(event['time'].replace("@", " "))
            except Exception:
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
            logger.error(f"Error loading cache: {e}", exc_info=True)
    return load_mock_data(tournament)

def save_cache(tournament, data):
    """Save data to cache file."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        else:
            cache = {}
        cache[tournament] = {**cache.get(tournament, {}), **data}
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=4)
        logger.info(f"Saved cache for {tournament}")
    except Exception as e:
        logger.error(f"Error saving cache: {e}", exc_info=True)

def load_mock_data(tournament):
    """Load mock data for a tournament."""
    if os.path.exists(MOCK_DATA_FILE):
        try:
            with open(MOCK_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            logger.error(f"Error loading mock data: {e}", exc_info=True)
    return {
        'events': [],
        'participants': [
            {
                "uid": generate_uid(tournament, "Mock Boat 1"),
                "boat": "Mock Boat 1",
                "image": "/static/images/placeholder.png",
                "tournament_uid": tournament.lower().replace(' ', '_')
            },
            {
                "uid": generate_uid(tournament, "Mock Boat 2"),
                "boat": "Mock Boat 2",
                "image": "/static/images/placeholder.png",
                "tournament_uid": tournament.lower().replace(' ', '_')
            }
        ],
        'leaderboard': [],
        'gallery': []
    }

def load_historical_data(tournament):
    """Load historical data for a tournament."""
    if os.path.exists(HISTORICAL_DATA_FILE):
        try:
            with open(HISTORICAL_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []})
        except Exception as e:
            logger.error(f"Error loading historical data: {e}", exc_info=True)
    return {'events': [], 'participants': [], 'leaderboard': [], 'gallery': []}

def load_demo_data(tournament):
    """Load demo data for a tournament."""
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                data = json.load(f)
                demo_data = data.get(tournament, {'events': [], 'leaderboard': []})
                logger.info(f"Loaded demo data for {tournament}: {len(demo_data['events'])} events")
                return demo_data
        except Exception as e:
            logger.error(f"Error loading demo data for {tournament}: {e}", exc_info=True)
    return {'events': [], 'leaderboard': []}

def check_internet():
    """Check if the internet is available."""
    try:
        subprocess.check_call(['ping', '-c', '1', '8.8.8.8'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def check_video_trigger():
    """Check if a video trigger condition is met."""
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

# scrape dynamic participants 

def scrape_participants(tournament):
    if \"edisto\" in tournament.lower():
        return scrape_edisto_participants()
    current_time = time.time()
    if current_time - PARTICIPANTS_CACHE['last_time'] < 60 and PARTICIPANTS_CACHE['data']:
        return PARTICIPANTS_CACHE['data']
    if not PLAYWRIGHT_AVAILABLE:
        print("Playwright not available, using fallback known boats")
        boats = [{'name': name, 'image': image} for name, image in known_boat_images.items()]
        PARTICIPANTS_CACHE['data'] = boats
        PARTICIPANTS_CACHE['last_time'] = current_time
        with open(PARTICIPANTS_CACHE_FILE, 'w') as f:
            json.dump(boats, f)
        return boats
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto('https://thebigrock.com/participants', wait_until='networkidle')
            boats = page.evaluate("""
            () => {
                const boats = [];
                document.querySelectorAll('img').forEach(img => {
                  const src = img.getAttribute('src');
                  const parent = img.closest('div');
                  const nameTag = parent?.querySelector('h2, h3, h4, .name, .title');
                  const name = nameTag?.textContent?.trim();

                  if (src && name) {
                    boats.push({ name, image: src.startsWith('http') ? src : `https:${src}` });
                  }
                });
                return boats;
            }
            """)
            browser.close()
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
        return [{'name': name, 'image': image} for name, image in known_boat_images.items()]

def filter_demo_events(events):
    """Filter demo events based on current time."""
    current_time = datetime.now().time()
    filtered = []
    unparsable_events = []

    for event in events:
        if not isinstance(event, dict) or 'time' not in event or 'action' not in event:
            logger.warning(f"Invalid event structure: {event}")
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
            logger.warning(f"Failed to parse time '{event.get('time', '')}' in event: {e}")
            unparsable_events.append(event)

    try:
        filtered.sort(key=lambda e: parser.parse(e['time'].replace("@", " ")), reverse=True)
    except Exception as e:
        logger.warning(f"Failed to sort events: {e}")

    filtered.extend(unparsable_events)
    return filtered

def get_events_for_mode():
    """Get events based on the current data source."""
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

def scrape_leaderboard(tournament):
    """Scrape leaderboard data for a tournament."""
    if not check_internet():
        logger.warning(f"No internet, using cached leaderboard for {tournament}")
        return load_cache(tournament)['leaderboard']

    remote = load_remote_settings()
    url = remote.get(tournament, {}).get("leaderboard")
    if not url:
        logger.error(f"No leaderboard URL for {tournament}")
        return load_cache(tournament)['leaderboard']

    try:
        response = requests.get(url, timeout=5, verify=True)
        response.raise_for_status()
        logger.info(f"Leaderboard response status ({tournament}): {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        leaderboard = []
        for item in soup.select('.leaderboard-item, .entry-content p, .leaderboard-table tr'):
            text = item.get_text(strip=True)
            if 'Place' in text or 'Winner' in text or text.startswith(('1.', '2.', '3.')):
                parts = text.split(',')
                if len(parts) >= 2:
                    boat = parts[0].replace('1.', '').replace('2.', '').replace('3.', '').strip()
                    points = parts[-1].strip() if 'Points' in parts[-1] or 'lb' in parts[-1] else text.split(' ')[-1].strip()
                    leaderboard.append({
                        'boat': boat,
                        'points': points,
                        'image': get_boat_image(tournament, boat)
                    })
        if not leaderboard:
            logger.warning(f"No leaderboard found for {tournament}, using cache")
            leaderboard = load_cache(tournament)['leaderboard']
        else:
            cache = load_cache(tournament)
            cache['leaderboard'] = leaderboard
            save_cache(tournament, cache)
        return leaderboard[:3]
    except Exception as e:
        logger.error(f"Scraping error (leaderboard, {tournament}): {e}", exc_info=True)
        return load_cache(tournament)['leaderboard']

def scrape_gallery():
    """Scrape gallery images."""
    if not check_internet():
        settings = load_settings()
        logger.warning("No internet, using cached gallery")
        return load_cache(settings['tournament'])['gallery']
    try:
        url = 'https://thebigrock.smugmug.com/2025-GALLERY'
        response = requests.get(url, timeout=5, verify=True)
        response.raise_for_status()
        logger.info(f"Gallery response status: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        images = []
        for img in soup.select('img.sm-gallery-image, img.sm-image'):
            src = img.get('src')
            if src and src.startswith('https://'):
                images.append(src)
        if not images:
            logger.warning("No gallery images found, using cache")
            settings = load_settings()
            images = load_cache(settings['tournament'])['gallery']
        else:
            settings = load_settings()
            cache = load_cache(settings['tournament'])
            cache['gallery'] = images
            save_cache(settings['tournament'], cache)
        return images[:5]
    except Exception as e:
        logger.error(f"Scraping error (gallery): {e}", exc_info=True)
        settings = load_settings()
        return load_cache(settings['tournament'])['gallery']


def scrape_edisto_participants():
    """Scrape participants from Edisto site."""
    now = time.time()
    if "edisto" not in PARTICIPANTS_CACHES:
        PARTICIPANTS_CACHES["edisto"] = {"last_time": 0, "data": []}
    cache = PARTICIPANTS_CACHES["edisto"]
    if cache["data"] and now - cache["last_time"] < 600:
        return cache["data"]

    boats = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://www.reeltimeapps.com/live/tournaments/2025-edisto-invitational-billfish/participants", wait_until="domcontentloaded", timeout=30000)
            soup = BeautifulSoup(page.content(), "html.parser")
            for card in soup.select("div.col-sm-3.col-md-3.col-lg-3"):
                name_tag = card.select_one("h2.post-title")
                img_tag = card.select_one("img.img-responsive")
                if name_tag and img_tag:
                    name = name_tag.text.strip()
                    img_url = img_tag["src"].strip()
                    if "avatar_placeholders" in img_url:
                        continue  # Skip default avatars
                    local_image = cache_boat_image(name, img_url)
                    boats.append({"name": name, "image": local_image})
            browser.close()
    except Exception as e:
        logger.error(f"Edisto participant scrape failed: {e}", exc_info=True)

    cache["data"] = boats
    cache["last_time"] = now
    return boats


def scrape_edisto_events():
    """Scrape events for Edisto Invitational."""
    url = "https://www.reeltimeapps.com/live/tournaments/2025-edisto-invitational-billfish/activities"
    now = time.time()

    if "edisto" not in EVENTS_CACHES:
        EVENTS_CACHES["edisto"] = {"last_time": 0, "data": []}
    cache = EVENTS_CACHES["edisto"]
    if cache["data"] and now - cache["last_time"] < 300:
        return cache["data"]

    events = []
    try:
        participants = scrape_edisto_participants()
        name_to_image = {
            normalize_boat_name(p['name']): p['image']
            for p in participants if p.get('name') and p.get('image')
        }
    except Exception as e:
        logger.warning(f"Failed to load Edisto participants: {e}")
        name_to_image = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            logger.info(f"Navigating to Edisto event page: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#feed-all article", timeout=15000)
            feed_items = page.query_selector_all("#feed-all article")
            logger.info(f"Found {len(feed_items)} Edisto event items")
            for item in feed_items:
                try:
                    boat = item.query_selector("h4").inner_text().strip()
                    description = item.query_selector("p strong").inner_text().strip()
                    timestamp = item.query_selector("p.pull-right").inner_text().strip()
                    image = name_to_image.get(normalize_boat_name(boat), "/static/images/placeholder.png")
                    events.append({
                        "boat": boat,
                        "message": description,
                        "time": timestamp,
                        "action": description.lower(),
                        "image": image
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse Edisto event item: {e}")
            context.close()
            browser.close()
    except Exception as e:
        logger.error(f"Edisto event scrape failed: {e}", exc_info=True)

    cache["data"] = events
    cache["last_time"] = now
    return events

# Routes
@app.route('/')
def index():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except Exception as e:
        logger.error(f"Error loading settings for index: {e}", exc_info=True)
        settings = {"tournament": "Big Rock"}
        tournament = "Big Rock"

    theme_class = f"theme-{tournament.lower().replace(' ', '-')}"
    version = get_version()
    return render_template("index.html", theme_class=theme_class, version=version, settings=settings)

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

@app.route('/leaderboard-page')
def leaderboard_page():
    try:
        return app.send_static_file('leaderboard.html')
    except Exception as e:
        logger.error(f"Error serving leaderboard.html: {e}", exc_info=True)
        return render_template_string("<h1>Error</h1><p>Leaderboard page not found</p>"), 404

@app.route('/settings-page')
def settings_page():
    try:
        return app.send_static_file('settings.html')
    except Exception as e:
        logger.error(f"Error serving settings.html: {e}", exc_info=True)
        return render_template_string("<h1>Error</h1><p>Settings page not found</p>"), 404

@app.route('/participants')
def participants_page():
    try:
        return app.send_static_file('participants.html')
    except Exception as e:
        logger.error(f"Error serving participants.html: {e}", exc_info=True)
        return render_template_string("<h1>Error</h1><p>Participants page not found</p>"), 404

@app.route('/api/participants')
def get_participants():
    with status_lock:
        if not scraping_status['done']:
            return jsonify({
                'status': 'scraping',
                'progress': scraping_status['progress'],
                'message': scraping_status['message']
            }), 202
        if scraping_status['error']:
            return jsonify({'error': scraping_status['error']}), 500

    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except Exception as e:
        logger.error(f"Failed to load {SETTINGS_FILE}: {e}", exc_info=True)
        tournament = "Big Rock"

    logger.info(f"Fetching participants for tournament: {tournament}")
    prefix = tournament.lower().replace(" ", "_")

    all_participants = []
    if os.path.exists(PARTICIPANTS_MASTER_FILE):
        try:
            with open(PARTICIPANTS_MASTER_FILE, 'r') as f:
                all_participants = json.load(f)
            logger.info(f"Loaded {len(all_participants)} total participants from {PARTICIPANTS_MASTER_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Corrupt {PARTICIPANTS_MASTER_FILE}: {e}", exc_info=True)

    filtered = [p for p in all_participants if p['uid'].startswith(prefix)]
    if not filtered:
        logger.warning(f"No participants found for '{prefix}', scraping...")
        filtered = scrape_participants(tournament)
        logger.info(f"Scraped {len(filtered)} participants")

    return jsonify(filtered)

@app.route('/api/scrape-participants', methods=['POST'])
def force_scrape_participants():
    """Force a fresh scrape of participants."""
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except Exception as e:
        logger.error(f"Failed to load {SETTINGS_FILE}: {e}", exc_info=True)
        tournament = "Big Rock"
    
    cache_key = tournament.replace(" ", "_").lower()
    PARTICIPANTS_CACHES[cache_key] = {"last_time": 0, "data": []}
    logger.info(f"Cleared participant cache for {tournament}")
    
    threading.Thread(target=background_init, args=(tournament,), daemon=True).start()
    return jsonify({'status': 'scraping_started'})

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
            subprocess.run(
                ['sudo', 'nmcli', 'con', 'add', 'type', 'wifi', 'ifname', 'wlan0', 'con-name', 'bigrock-wifi', 'ssid', ssid] +
                (['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password] if password else []),
                check=True
            )
            subprocess.run(['sudo', 'nmcli', 'con', 'up', 'bigrock-wifi'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
            logger.info(f"Connected to WiFi: {ssid}")
            return jsonify({'status': 'success'})
        except subprocess.CalledProcessError as e:
            logger.error(f"Error connecting to WiFi: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)}), 500
    return render_template('wifi.html')

@app.route('/wifi/scan')
def scan_wifi():
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
            if len(parts) >= 3:
                ssid, signal, security = parts[:3]
                if ssid:
                    networks.append({
                        'ssid': ssid,
                        'signal': int(signal),
                        'security': security
                    })
        current_output = subprocess.check_output(
            ['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi'],
            universal_newlines=True
        )
        current_ssid = next((line.split(':')[1] for line in current_output.strip().split('\n') if line.startswith("yes:")), None)
        logger.info(f"WiFi scan found {len(networks)} networks, current: {current_ssid}")
        return jsonify({'networks': networks, 'current': current_ssid})
    except Exception as e:
        logger.error(f"WiFi scan error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/wifi/connect', methods=['POST'])
def connect_wifi_vue():
    data = request.get_json()
    ssid = data.get('ssid')
    password = data.get('password', '')
    if not ssid:
        return jsonify({'error': 'SSID is required'}), 400

    try:
        subprocess.run(
            ['sudo', 'nmcli', 'con', 'add', 'type', 'wifi', 'ifname', 'wlan0', 'con-name', 'bigrock-wifi', 'ssid', ssid] +
            (['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password] if password else []),
            check=True
        )
        subprocess.run(['sudo', 'nmcli', 'con', 'up', 'bigrock-wifi'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'hostapd'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'dnsmasq'], check=True)
        logger.info(f"Connected to WiFi: {ssid}")
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        logger.error(f"WiFi connect error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/wifi/disconnect', methods=['POST'])
def wifi_disconnect():
    try:
        subprocess.run(['sudo', 'nmcli', 'con', 'down', 'bigrock-wifi'], check=True)
        subprocess.run(['sudo', 'nmcli', 'con', 'delete', 'bigrock-wifi'], check=False)
        logger.info("Disconnected from WiFi")
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        logger.error(f"WiFi disconnect error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/events')
def events():
    try:
        events = get_events_for_mode()
        settings = load_settings()
        tournament = settings.get("tournament", "Big Rock")
        logger.info(f"Returning {len(events)} events for {tournament}")
        return jsonify(events)
    except Exception as e:
        logger.error(f"Error in /events route: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

@app.route('/hooked')
def hooked():
    events = get_events_for_mode()
    now = datetime.now()
    current_year = now.year

    def parse_event_time(e):
        try:
            dt = parser.parse(e['time'].replace("@", " "))
            return dt.replace(year=current_year)
        except Exception:
            logger.warning(f"Unparsable time: {e.get('time', 'unknown')}")
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
            continue
        if event_time <= now:
            resolved_ids.add(e['hookup_id'])
            logger.info(f"Resolved: {e['hookup_id']} via {e['action']}")

    hooked = []
    for e in events:
        if e.get('action', '').lower() != 'hooked up':
            continue
        if e.get('hookup_id') in resolved_ids:
            logger.info(f"Removing resolved hookup: {e['hookup_id']}")
            continue
        event_time = parse_event_time(e)
        if event_time and event_time <= now:
            hooked.append(e)

    logger.info(f"Hooked boats count: {len(hooked)}")
    return jsonify(hooked)

@app.route('/scales')
def scales():
    try:
        events = get_events_for_mode()
        scales_events = [
            event for event in events
            if isinstance(event, dict) and event.get('action', '').lower() == 'headed to scales'
        ]
        logger.info(f"Returning {len(scales_events)} scales events for {get_current_tournament()}")
        return jsonify(scales_events)
    except Exception as e:
        logger.error(f"Error in /scales endpoint: {e}", exc_info=True)
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

        if old_settings.get('tournament') != settings_data.get('tournament') or old_settings.get('data_source') != settings_data.get('data_source'):
            tournament = settings_data.get('tournament', 'Big Rock')
            logger.info(f"Tournament or data source changed, updating demo data for {tournament}")
            demo_data = {}
            if os.path.exists(DEMO_DATA_FILE):
                try:
                    with open(DEMO_DATA_FILE, 'r') as f:
                        demo_data = json.load(f)
                except Exception as e:
                    logger.error(f"Error loading demo data: {e}", exc_info=True)

            demo_data[tournament] = {
                'events': inject_hooked_up_events(scrape_events(tournament), tournament),
                'leaderboard': scrape_leaderboard(tournament)
            }

            try:
                with open(DEMO_DATA_FILE, 'w') as f:
                    json.dump(demo_data, f, indent=4)
                logger.info(f"Cached demo data for {tournament}")
            except Exception as e:
                logger.error(f"Error saving demo data: {e}", exc_info=True)

        return jsonify({'status': 'success'})
    
    current_settings = load_settings()
    return jsonify(current_settings)

@app.route('/bluetooth-status')
def bluetooth_status():
    now = time.time()
    if now - bluetooth_status_cache['timestamp'] < 10:
        return jsonify({'status': bluetooth_status_cache['status']})

    status = 'Not Connected'
    try:
        subprocess.check_output(['bluetoothctl', 'show'], stderr=subprocess.DEVNULL, text=True)
        devices_output = subprocess.check_output(['bluetoothctl', 'devices'], stderr=subprocess.DEVNULL, text=True).strip()
        if not devices_output:
            raise ValueError("No devices found")

        device_lines = devices_output.split('\n')
        first_device = None
        for line in device_lines:
            parts = line.split(' ', 2)
            if len(parts) >= 2 and parts[0] == 'Device':
                first_device = parts[1]
                break

        if not first_device:
            raise ValueError("No valid device MAC found")

        info_output = subprocess.check_output(['bluetoothctl', 'info', first_device], stderr=subprocess.DEVNULL, text=True)
        if 'Connected: yes' in info_output:
            name = 'Bluetooth Device'
            for line in info_output.split('\n'):
                if line.strip().startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                    break
            status = f"Connected to {name}"
    except Exception as e:
        logger.error(f"Bluetooth status error: {e}", exc_info=True)
        status = 'Not Connected'

    bluetooth_status_cache['status'] = status
    bluetooth_status_cache['timestamp'] = now
    return jsonify({'status': status})

def validate_mac(mac):
    """Validate Bluetooth MAC address format."""
    pattern = r'^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$'
    return bool(re.match(pattern, mac))

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
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        devices.append({'mac': parts[1], 'name': parts[2]})
            logger.info(f"Bluetooth scan found {len(devices)} devices")
            return jsonify(devices)
        except Exception as e:
            logger.error(f"Bluetooth scan error: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)})
    elif action == 'pair':
        mac = request.args.get('mac')
        if not mac or not validate_mac(mac):
            return jsonify({'status': 'error', 'message': 'Invalid or missing MAC address'})
        try:
            commands = f"agent on\ndefault-agent\npair {mac}\ntrust {mac}\nconnect {mac}\n"
            subprocess.check_output(['bluetoothctl'], input=commands.encode(), stderr=subprocess.STDOUT, timeout=15)
            time.sleep(2)
            mac_underscore = mac.upper().replace(':', '_')
            sinks_output = subprocess.check_output(['wpctl', 'list-sinks'], timeout=5).decode()
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
                subprocess.run(['wpctl', 'set-default', sink_name], check=True, timeout=5)
                subprocess.run(['wpctl', 'set-mute', sink_name, '0'], check=True, timeout=5)
                subprocess.run(['wpctl', 'set-volume', sink_name, '1.0'], check=True, timeout=5)
                logger.info(f"Paired Bluetooth device {mac} and set audio to {sink_name}")
                return jsonify({'status': 'success', 'output': f'Paired and audio output set to {sink_name}'})
            else:
                logger.error("Bluetooth sink not found in PipeWire")
                return jsonify({'status': 'error', 'message': 'Bluetooth sink not found in PipeWire'})
        except subprocess.CalledProcessError as e:
            logger.error(f"Bluetooth pair error: {e.output.decode()}")
            return jsonify({'status': 'error', 'message': e.output.decode()})
        except subprocess.TimeoutExpired:
            logger.error("Bluetooth pairing operation timed out")
            return jsonify({'status': 'error', 'message': 'Pairing operation timed out'})
        except Exception as e:
            logger.error(f"Bluetooth pair error: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)})
    elif action == 'on':
        try:
            subprocess.run(['bluetoothctl', 'power', 'on'], check=True, timeout=5)
            logger.info("Bluetooth powered on")
            return jsonify({'status': 'success'})
        except Exception as e:
            logger.error(f"Bluetooth power on error: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)})
    elif action == 'off':
        try:
            subprocess.run(['bluetoothctl', 'power', 'off'], check=True, timeout=5)
            logger.info("Bluetooth powered off")
            return jsonify({'status': 'success'})
        except Exception as e:
            logger.error(f"Bluetooth power off error: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': str(e)})
    return jsonify({'status': 'error', 'message': 'Invalid action'})

def refresh_data_loop(interval=600):
    """Periodically refresh participants and events."""
    def refresh():
        try:
            logger.info("Background: Refreshing participants and events...")
            settings = load_settings()
            tournament = settings.get("tournament", "Big Rock")
            scrape_participants(tournament)
            scrape_events(tournament)
        except Exception as e:
            logger.error(f"Background refresh failed: {e}", exc_info=True)
        finally:
            threading.Timer(interval, refresh).start()
    refresh()

if __name__ == '__main__':
    initialize_default_settings()
    tournament = get_current_tournament()

    def initial_setup():
        with status_lock:
            scraping_status['message'] = "Initializing participants and events..."
            scraping_status['progress'] = 0
            scraping_status['done'] = False

        try:
            if not os.path.exists(PARTICIPANTS_MASTER_FILE):
                logger.info("participants_master.json not found — starting scrape...")
                initialize_participants(tournament)
                logger.info("Participant scrape complete.")
            else:
                logger.info("participants_master.json found — skipping participant scrape.")
            scrape_events(tournament)
            with status_lock:
                scraping_status['done'] = True
                scraping_status['progress'] = 100
                scraping_status['message'] = "Initialization complete."
        except Exception as e:
            logger.error(f"Initialization failed: {e}", exc_info=True)
            with status_lock:
                scraping_status['error'] = str(e)
                scraping_status['done'] = True
                scraping_status['message'] = "Error during initialization"

    threading.Thread(target=initial_setup, daemon=True).start()
    refresh_data_loop()
    app.run(debug=True, host='0.0.0.0', port=5000)
