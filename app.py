from flask import Flask, jsonify, request, send_from_directory
from dateutil import parser as date_parser
from datetime import datetime, timedelta
import json
import os
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import random
import re
from concurrent.futures import ThreadPoolExecutor
import time

app = Flask(__name__)
CACHE_FILE = 'cache.json'
EVENTS_FILE = 'events.json'
SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'

def get_cache_path(file_type):
    tournament = get_current_tournament()
    safe = tournament.lower().replace(" ", "_")
    os.makedirs(f"cache/{safe}", exist_ok=True)
    return f"cache/{safe}/{file_type}.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {}

def load_demo_data(tournament):
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'leaderboard': []})
        except Exception as e:
            print(f"⚠️ Error loading demo data: {e}")
    return {'events': [], 'leaderboard': []}

def get_data_source():
    settings = load_settings()
    return settings.get("mode", "live")

def is_cache_fresh(cache, key, max_age_minutes):
    try:
        last_scraped = cache.get(key, {}).get("last_scraped")
        if not last_scraped:
            return False
        last_time = datetime.fromisoformat(last_scraped)
        return (datetime.now() - last_time) < timedelta(minutes=max_age_minutes)
    except Exception:
        return False

def get_current_tournament():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            return settings.get('tournament', 'Big Rock')
    except Exception as e:
        print(f"⚠️ Failed to load settings: {e}")
        return 'Big Rock'

def normalize_boat_name(name):
    if not name:
        return "unknown"
    return name.lower().replace(' ', '_').replace("'", "").replace("/", "_")

def cache_boat_image(boat_name, image_url):
    folder = 'static/images/boats'
    os.makedirs(folder, exist_ok=True)
    safe_name = normalize_boat_name(boat_name)
    ext = os.path.splitext(image_url.split('?')[0])[-1] or ".jpg"
    file_path = os.path.join(folder, f"{safe_name}{ext}")

    # Check if image already exists and is valid
    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                if len(f.read()) > 0:  # Ensure file is not empty
                    return f"/{file_path}"  # Return relative path for frontend
        except Exception as e:
            print(f"⚠️ Invalid image file for {boat_name}: {e}")
            os.remove(file_path)  # Remove corrupted file

    # Download image if it doesn't exist
    try:
        if not image_url:
            print(f"⚠️ No image URL for {boat_name}")
            return "/static/images/boats/default.jpg"  # Fallback to default image
        response = requests.get(image_url, timeout=10)
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                f.write(response.content)
            print(f"✅ Downloaded image for {boat_name}: {file_path}")
            return f"/{file_path}"  # Return relative path
        else:
            print(f"⚠️ Failed to download image for {boat_name}: HTTP {response.status_code}")
            return "/static/images/boats/default.jpg"
    except Exception as e:
        print(f"⚠️ Error downloading image for {boat_name}: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)  # Clean up failed download
        return "/static/images/boats/default.jpg"  # Fallback to default image

def fetch_page_html(url, wait_selector=None, timeout=30000):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="load", timeout=60000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    print(f"⚠️ Timeout waiting for selector '{wait_selector}'")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"❌ Playwright error for {url}: {e}")
        return ""

def inject_hooked_up_events(events, tournament=None):
    print(f"🔍 inject_hooked_up_events() called with {len(events)} events")
    demo_events = []
    inserted_keys = set()

    for event in events:
        event_type = event.get("event", "")
        details = event.get("details", "").lower()
        boat = event.get("boat", "Unknown")
        is_resolution = (
            event_type == "Boated" or
            (event_type == "Released" and not re.search(r"\b\w+\s+\w+\s+released\b", details)) or
            ("pulled hook" in details) or
            ("wrong species" in details)
        )
        print(f"🔄 Checking event: {event['timestamp']} | {event_type} | {details} | Boat: {boat}")
        if not is_resolution:
            continue
        try:
            timestamp = date_parser.parse(event["timestamp"])
            delta = timedelta(minutes=random.randint(3, 30))
            demo_time = timestamp - delta
            key = f"{event['uid']}_{event['timestamp']}"
            if key in inserted_keys:
                print(f"⏩ Skipping duplicate: {key}")
                continue
            demo_event = {
                "timestamp": demo_time.isoformat(),
                "event": "Hooked Up",
                "boat": event["boat"],
                "uid": event["uid"],
                "details": "Hooked up!",
                "hookup_id": key
            }
            demo_events.append(demo_event)
            inserted_keys.add(key)
        except Exception as e:
            print(f"⚠️ Demo injection failed for {boat}: {e}")

    all_events = sorted(demo_events + events, key=lambda e: e["timestamp"])
    print(f"📦 Returning {len(all_events)} total events (including {len(demo_events)} injected)")
    return all_events

def save_demo_data_if_needed(settings, old_settings):
    if settings.get("data_source") == "demo":
        print("📦 [DEMO] Saving demo data...")
        tournament = settings.get("tournament", "Big Rock")
        try:
            events = scrape_events(force=True)
            leaderboard = scrape_leaderboard(force=True)
            demo_data = {}
            if os.path.exists(DEMO_DATA_FILE):
                with open(DEMO_DATA_FILE, 'r') as f:
                    demo_data = json.load(f)
            injected = inject_hooked_up_events(events, tournament)
            demo_data[tournament] = {
                "events": injected,
                "leaderboard": leaderboard
            }
            with open(DEMO_DATA_FILE, 'w') as f:
                json.dump(demo_data, f, indent=4)
            print(f"✅ [DEMO] Saved demo_data.json for {tournament}")
        except Exception as e:
            print(f"❌ [DEMO] Failed to cache demo data: {e}")

def run_in_thread(target, name):
    def wrapper():
        try:
            print(f"🧵 Starting {name} scrape in thread...")
            target()
            print(f"✅ Finished {name} scrape.")
        except Exception as e:
            print(f"❌ Error in {name} thread: {e}")
    Thread(target=wrapper).start()

def scrape_participants(force=False):
    cache = load_cache()
    tournament = get_current_tournament()
    participants_file = get_cache_path("participants.json")

    if not force and is_cache_fresh(cache, f"{tournament}_participants", 1440):
        print("✅ Participant cache is fresh — skipping scrape.")
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                return json.load(f)
        return []

    try:
        # Load tournament-specific participant URL from central settings
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        settings = requests.get(settings_url, timeout=30).json()
        matching_key = next((k for k in settings if k.lower() == tournament.lower()), None)
        if not matching_key:
            raise Exception(f"Tournament '{tournament}' not found in settings.json")

        participants_url = settings[matching_key].get("participants")
        if not participants_url:
            raise Exception(f"No participants URL found for {matching_key}")

        print(f"📡 Scraping participants from: {participants_url}")

        # Load existing participants for this tournament (if any)
        existing_participants = {}
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                for p in json.load(f):
                    existing_participants[p["uid"]] = p

        html = fetch_page_html(participants_url, "article.post.format-image")
        with open("debug_participants.html", "w", encoding="utf-8") as f:
            f.write(html)

        soup = BeautifulSoup(html, 'html.parser')
        updated_participants = {}
        seen_boats = set()
        download_tasks = []

        for article in soup.select("article.post.format-image"):
            name_tag = article.select_one("h2.post-title")
            type_tag = article.select_one("ul.post-meta li")
            img_tag = article.select_one("img")

            if not name_tag:
                continue

            boat_name = name_tag.get_text(strip=True)
            if ',' in boat_name or boat_name.lower() in seen_boats:
                continue

            boat_type = type_tag.get_text(strip=True) if type_tag else ""
            uid = normalize_boat_name(boat_name)
            seen_boats.add(boat_name.lower())

            image_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
            image_path = existing_participants.get(uid, {}).get("image_path", "")

            if not image_path or not os.path.exists(image_path[1:] if image_path.startswith('/') else image_path):
                if image_url:
                    download_tasks.append((uid, boat_name, image_url))
                else:
                    image_path = "/static/images/boats/default.jpg"

            updated_participants[uid] = {
                "uid": uid,
                "boat": boat_name,
                "type": boat_type,
                "image_path": image_path
            }

        # Download images in parallel
        if download_tasks:
            print(f"📸 Downloading {len(download_tasks)} new boat images...")
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    executor.submit(cache_boat_image, bname, url): uid
                    for uid, bname, url in download_tasks
                }
                for future in futures:
                    uid = futures[future]
                    try:
                        result_path = future.result()
                        updated_participants[uid]["image_path"] = result_path
                    except Exception as e:
                        print(f"❌ Error downloading image for {uid}: {e}")
                        updated_participants[uid]["image_path"] = "/static/images/boats/default.jpg"

        updated_list = list(updated_participants.values())
        if updated_list != list(existing_participants.values()):
            with open(participants_file, "w") as f:
                json.dump(updated_list, f, indent=2)
            print(f"✅ Updated and saved {len(updated_list)} participants")
        else:
            print(f"✅ No changes detected — {len(updated_list)} participants up-to-date")

        cache[f"{tournament}_participants"] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        return updated_list

    except Exception as e:
        print(f"⚠️ Error scraping participants: {e}")
        return []


def scrape_events(force=False, skip_timestamp_check=False):
    cache = load_cache()
    settings = load_settings()
    tournament = get_current_tournament()
    events_file = get_cache_path("events.json")
    participants_file = get_cache_path("participants.json")

    if not force and is_cache_fresh(cache, f"{tournament}_events", 2):
        print("✅ Event cache is fresh — skipping scrape.")
        if os.path.exists(events_file):
            with open(events_file, "r") as f:
                return json.load(f)
        return []

    try:
        # Load tournament settings and events URL
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        remote_settings = requests.get(settings_url, timeout=30).json()
        matching_key = next((k for k in remote_settings if k.lower() == tournament.lower()), None)
        if not matching_key:
            raise Exception(f"Tournament '{tournament}' not found in settings.json")
        events_url = remote_settings[matching_key].get("events")
        if not events_url:
            raise Exception(f"No events URL found for {matching_key}")

        print(f"➡️ Events URL: {events_url}")

        # Load participants from per-tournament cache
        participants_dict = {}
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                participants = json.load(f)
                participants_dict = {p["uid"]: p for p in participants}
        else:
            print("⚠️ Participants cache missing — regenerating...")
            scrape_participants(force=True)
            if os.path.exists(participants_file):
                with open(participants_file, "r") as f:
                    participants = json.load(f)
                    participants_dict = {p["uid"]: p for p in participants}
            else:
                raise Exception("Failed to regenerate participants cache.")

        # Load existing events
        existing = []
        last_known_ts = None
        if os.path.exists(events_file):
            with open(events_file, "r") as f:
                existing = json.load(f)
                try:
                    last_known_ts = max(
                        date_parser.parse(e["timestamp"]) for e in existing if e.get("timestamp")
                    )
                except Exception as e:
                    print(f"⚠️ Failed to determine last known timestamp: {e}")

        html = fetch_page_html(events_url, "article.m-b-20, article.entry, div.activity, li.event, div.feed-item")
        with open("debug_events.html", "w", encoding="utf-8") as f:
            f.write(html or "<!-- No HTML returned -->")

        soup = BeautifulSoup(html, 'html.parser')
        new_events = []

        for article in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
            time_tag = article.select_one("p.pull-right")
            name_tag = article.select_one("h4.montserrat")
            desc_tag = article.select_one("p > strong")

            if not time_tag or not name_tag or not desc_tag:
                continue

            raw = time_tag.get_text(strip=True)
            timestamp_str = raw.replace("@", "").strip()

            try:
                dt = date_parser.parse(timestamp_str)
                timestamp = dt.replace(year=datetime.now().year)
                if (
                    last_known_ts and
                    timestamp <= last_known_ts and
                    not skip_timestamp_check and
                    settings.get("data_source") != "demo"
                ):
                    continue
                timestamp_iso = timestamp.isoformat()
            except Exception as e:
                print(f"⚠️ Failed to parse '{timestamp_str}': {e}")
                continue

            boat_name = name_tag.get_text(strip=True)
            description = desc_tag.get_text(strip=True)

            # Determine event type
            if "released" in description.lower():
                event_type = "Released"
            elif "boated" in description.lower():
                event_type = "Boated"
            elif "pulled hook" in description.lower():
                event_type = "Pulled Hook"
            elif "wrong species" in description.lower():
                event_type = "Wrong Species"
            else:
                event_type = "Other"

            # Skip named releases
            if event_type == "Released" and re.search(r"\b\w+\s+\w+\s+released\b", description.lower()):
                continue

            uid = normalize_boat_name(boat_name)
            if uid in participants_dict:
                boat_name = participants_dict[uid]["boat"]  # Restore original formatting
            else:
                print(f"⚠️ Boat {boat_name} (uid: {uid}) not found in participants cache")

            new_events.append({
                "timestamp": timestamp_iso,
                "event": event_type,
                "boat": boat_name,
                "uid": uid,
                "details": description,
                "image_path": participants_dict.get(uid, {}).get("image_path", "/static/images/boats/default.jpg")
            })

        all_events = existing + new_events
        all_events.sort(key=lambda e: e["timestamp"])

        with open(events_file, "w") as f:
            json.dump(all_events, f, indent=2)

        cache[f"{tournament}_events"] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)

        print(f"✅ Appended {len(new_events)} new events (total now {len(all_events)})")
        return all_events

    except Exception as e:
        print(f"❌ Error in scrape_events: {e}")
        return []


def scrape_leaderboard(force=False):
    print("⚠️ scrape_leaderboard not implemented yet.")
    return []

def scrape_gallery(force=False):
    print("⚠️ scrape_gallery not implemented yet.")
    return []

# Routes
@app.route('/')
def homepage():
    return send_from_directory('templates', 'index.html')

@app.route('/participants')
def participants_page():
    return send_from_directory('templates', 'participants.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/scrape/participants')
def scrape_participants_route():
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))
    participants = scrape_participants(force=True)
    sliced = participants[offset:offset + limit]
    return jsonify({
        "count": len(participants),
        "participants": sliced,
        "status": "ok"
    })

@app.route('/participants_data')
def get_participants_data():
    try:
        participants_file = get_cache_path("participants.json")
        if not os.path.exists(participants_file):
            return jsonify({"status": "error", "message": "Participants cache not found"}), 404

        with open(participants_file, "r") as f:
            data = json.load(f)

        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        sliced = data[offset:offset + limit]

        return jsonify({
            "count": len(data),
            "participants": sliced,
            "status": "ok"
        })

    except Exception as e:
        print(f"⚠️ Error in /participants_data: {e}")
        return jsonify({"status": "error", "message": str(e)})


@app.route("/scrape/events")
def get_events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")
    events_file = get_cache_path("events.json")

    if settings.get("data_source") == "demo":
        data = load_demo_data(tournament)
        all_events = data.get("events", [])
        now = datetime.now()
        filtered = [
            e for e in all_events
            if date_parser.parse(e["timestamp"]).time() <= now.time()
        ]
        filtered = sorted(filtered, key=lambda e: e["timestamp"], reverse=True)
        return jsonify({
            "status": "ok",
            "count": len(filtered),
            "events": filtered[:10]
        })

    force = request.args.get("force", "false").lower() == "true"
    events = scrape_events(force=force)
    if not events and os.path.exists(events_file):
        with open(events_file, "r") as f:
            events = json.load(f)

    events = sorted(events, key=lambda e: e["timestamp"], reverse=True)
    return jsonify({
        "status": "ok" if events else "error",
        "count": len(events),
        "events": events[:10]
    })


@app.route("/scrape/all")
def scrape_all():
    tournament = get_current_tournament()
    print(f"🔁 Starting full scrape for tournament: {tournament}")

    events = scrape_events(force=True)
    participants = scrape_participants(force=True)
    run_in_thread(scrape_leaderboard, "leaderboard")
    run_in_thread(scrape_gallery, "gallery")

    return jsonify({
        "status": "ok",
        "tournament": tournament,
        "events": len(events),
        "participants": len(participants),
        "message": "Scraped events & participants. Leaderboard & gallery running in background."
    })


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
        old_settings = load_settings()
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_data, f, indent=4)
        old_tournament = old_settings.get("tournament")
        new_tournament = settings_data.get("tournament")
        new_mode = settings_data.get("data_source")
        if new_tournament != old_tournament and new_mode == "live":
            for f in ["events.json", "participants_master.json"]:
                if os.path.exists(f):
                    os.remove(f)
                    print(f"🧹 Cleared {f} due to tournament change in live mode.")
            run_in_thread(lambda: scrape_events(force=True), "events")
            run_in_thread(lambda: scrape_participants(force=True), "participants")
        save_demo_data_if_needed(settings_data, old_settings)
        return jsonify({'status': 'success'})
    return jsonify(load_settings())

@app.route('/settings-page/')
def settings_page():
    return send_from_directory('static', 'settings.html')

@app.route("/generate_demo")
def generate_demo():
    try:
        tournament = get_current_tournament()
        events = scrape_events(force=True, skip_timestamp_check=True)
        leaderboard = scrape_leaderboard(force=True)
        injected = inject_hooked_up_events(events, tournament)
        demo_data = {}
        if os.path.exists(DEMO_DATA_FILE):
            with open(DEMO_DATA_FILE, 'r') as f:
                demo_data = json.load(f)
        demo_data[tournament] = {
            "events": injected,
            "leaderboard": leaderboard
        }
        with open(DEMO_DATA_FILE, 'w') as f:
            json.dump(demo_data, f, indent=4)
        print(f"✅ [DEMO] demo_data.json written with {len(injected)} events")
        return jsonify({"status": "ok", "events": len(injected)})
    except Exception as e:
        print(f"❌ Error generating demo data: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route("/hooked")
def get_hooked_up_events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")
    events_file = get_cache_path("events.json")

    if settings.get("data_source") == "demo":
        data = load_demo_data(tournament)
        events = data.get("events", [])
    else:
        if not os.path.exists(events_file):
            return jsonify({"status": "ok", "events": [], "count": 0})
        with open(events_file, "r") as f:
            events = json.load(f)

    now = datetime.now()
    resolution_lookup = set()
    for e in events:
        if e["event"] in ["Released", "Boated"] or \
           "pulled hook" in e.get("details", "").lower() or \
           "wrong species" in e.get("details", "").lower():
            try:
                ts = date_parser.parse(e["timestamp"]).replace(microsecond=0)
                if settings.get("data_source") == "demo" and ts.time() > now.time():
                    continue
                resolution_lookup.add((e["uid"], ts.isoformat()))
            except:
                continue

    unresolved = []
    for e in events:
        if e["event"] != "Hooked Up":
            continue
        try:
            hookup_ts = date_parser.parse(e["timestamp"]).replace(microsecond=0)
            if settings.get("data_source") == "demo" and hookup_ts.time() > now.time():
                continue
        except Exception as ex:
            print(f"⚠️ Failed to parse hookup timestamp: {ex}")
            continue
        try:
            uid, ts_str = e.get("hookup_id", "").rsplit("_", 1)
            target_ts = date_parser.parse(ts_str).replace(microsecond=0).isoformat()
        except:
            unresolved.append(e)
            continue
        if (uid, target_ts) not in resolution_lookup:
            unresolved.append(e)

    return jsonify({
        "status": "ok",
        "count": len(unresolved),
        "events": unresolved
    })

@app.route('/bluetooth/status')
def bluetooth_status():
    return jsonify({"enabled": True})

@app.route('/bluetooth/scan')
def bluetooth_scan():
    return jsonify({"devices": [{"name": "Test Device", "mac": "00:11:22:33:44:55", "connected": False}]})

@app.route('/bluetooth/connect', methods=['POST'])
def bluetooth_connect():
    data = request.get_json()
    print(f"Connecting to: {data['mac']}")
    return jsonify({"status": "ok"})

@app.route('/bluetooth/disconnect', methods=['POST'])
def bluetooth_disconnect():
    data = request.get_json()
    print(f"Disconnecting from: {data['mac']}")
    return jsonify({"status": "ok"})

@app.route('/wifi/scan')
def wifi_scan():
    try:
        subprocess.run(['sudo', 'nmcli', 'dev', 'wifi', 'rescan'], check=True)
        output = subprocess.check_output(
            ['sudo', 'nmcli', '-t', '-f', 'SSID,SIGNAL,IN-USE', 'dev', 'wifi'],
            text=True
        )
        network_map = {}
        for line in output.strip().split('\n'):
            if not line:
                continue
            parts = line.strip().split(':')
            if len(parts) < 3:
                continue
            ssid, signal, in_use = parts
            ssid = ssid.strip()
            signal = int(signal) if signal.isdigit() else 0
            connected = in_use.strip() == '*'
            if not ssid:
                continue
            if ssid not in network_map or signal > network_map[ssid]['signal']:
                network_map[ssid] = {
                    'ssid': ssid,
                    'signal': signal,
                    'connected': connected
                }
        return jsonify({'networks': list(network_map.values())})
    except Exception as e:
        print(f"⚠️ Error during Wi-Fi scan: {e}")
        return jsonify({'networks': [], 'error': str(e)}), 500

@app.route('/wifi/connect', methods=['POST'])
def wifi_connect():
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        password = data.get('password')
        if not ssid:
            return jsonify({'status': 'error', 'message': 'Missing SSID'}), 400
        cmd = ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid]
        if password:
            cmd.extend(['password', password])
        print(f"🔌 Connecting to {ssid}")
        result = subprocess.check_output(cmd, text=True)
        print(f"✅ Wi-Fi connected: {result}")
        return jsonify({'status': 'ok', 'message': result})
    except subprocess.CalledProcessError as e:
        print(f"❌ Wi-Fi connect error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/wifi/disconnect', methods=['POST'])
def wifi_disconnect():
    try:
        print("🚫 Disconnecting Wi-Fi")
        subprocess.run(['nmcli', 'networking', 'off'], check=True)
        time.sleep(1)
        subprocess.run(['nmcli', 'networking', 'on'], check=True)
        return jsonify({'status': 'ok'})
    except subprocess.CalledProcessError as e:
        print(f"❌ Wi-Fi disconnect error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
