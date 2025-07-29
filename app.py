 
 
from flask import Flask, jsonify, request
from flask import send_from_directory
from dateutil import parser as date_parser
from datetime import datetime
import json
import os
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import hashlib
import subprocess
from datetime import datetime, timedelta
from threading import Thread
import random
import re


CACHE_FILE = 'cache.json'

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)
app = Flask(__name__)

EVENTS_FILE = 'events.json'
SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'

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
    return name.lower().replace(' ', '_').replace("'", "").replace("/", "_")

def cache_boat_image(boat_name, image_url):
    folder = 'static/images/boats'
    os.makedirs(folder, exist_ok=True)
    safe_name = normalize_boat_name(boat_name)
    ext = os.path.splitext(image_url.split('?')[0])[-1] or ".jpg"
    file_path = os.path.join(folder, f"{safe_name}{ext}")

    if not os.path.exists(file_path):
        try:
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
        except Exception as e:
            print(f"⚠️ Error downloading image for {boat_name}: {e}")
    return file_path

def fetch_page_html(url, wait_selector=None, timeout=30000):
    """Load a page with Playwright and return the final HTML."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="load", timeout=60000)

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    print(f"⚠️ Timeout waiting for selector '{wait_selector}' — continuing anyway.")

            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"❌ Playwright error for {url}: {e}")
        return ""


def inject_hooked_up_events(events, tournament=None):
    print("🔍 inject_hooked_up_events() called with", len(events), "events")
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
        print("→ Is resolution:", is_resolution)

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
            print(f"✅ Injecting demo event: {demo_event}")
            demo_events.append(demo_event)
            inserted_keys.add(key)
        except Exception as e:
            print(f"⚠️ Demo injection failed for {event.get('boat')}: {e}")

    all_events = sorted(demo_events + events, key=lambda e: e["timestamp"])
    print(f"📦 Returning {len(all_events)} total events (including {len(demo_events)} injected)")
    return all_events

def save_demo_data_if_needed(settings, old_settings):
    if settings.get("data_source") == "demo":
        print("📦 [DEMO] Saving demo data...")
        tournament = settings.get("tournament", "Big Rock")

        try:
            events = scrape_events(force=True)
            print(f"✅ [DEMO] Scraped {len(events)} live events")

            leaderboard = scrape_leaderboard(force=True)

            demo_data = {}
            if os.path.exists(DEMO_DATA_FILE):
                with open(DEMO_DATA_FILE, 'r') as f:
                    demo_data = json.load(f)

            injected = inject_hooked_up_events(events, tournament)
            print(f"✅ [DEMO] Injected {len(injected) - len(events)} Hooked Up events")

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

from concurrent.futures import ThreadPoolExecutor

from concurrent.futures import ThreadPoolExecutor

def scrape_participants(force=False):
    cache = load_cache()
    if not force and is_cache_fresh(cache, "participants", 1440):
        print("✅ Participant cache is fresh — skipping scrape.")
        return

    try:
        tournament = get_current_tournament()
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        settings = requests.get(settings_url, timeout=10).json()

        matching_key = next((k for k in settings if k.lower() == tournament.lower()), None)
        if not matching_key:
            raise Exception(f"Tournament '{tournament}' not found in settings.json")

        tournament_settings = settings[matching_key]
        participants_url = tournament_settings.get("participants")
        if not participants_url:
            raise Exception(f"No participants URL found for {matching_key}")

        print(f"📡 Scraping participants from: {participants_url}")

        existing_participants = {}
        if os.path.exists("participants_master.json"):
            with open("participants_master.json", "r") as f:
                for p in json.load(f):
                    existing_participants[p["uid"]] = p

        html = fetch_page_html(participants_url, "article.post.format-image")
        with open("debug_participants.html", "w", encoding="utf-8") as f:
            f.write(html)

        soup = BeautifulSoup(html, 'html.parser')
        updated_participants = {}
        seen_boats = set()
        download_tasks = []

        def cache_boat_image(boat_name, image_url):
            folder = 'static/images/boats'
            os.makedirs(folder, exist_ok=True)
            safe_name = normalize_boat_name(boat_name)
            file_path = os.path.join(folder, f"{safe_name}.jpg")

            if not os.path.exists(file_path):
                try:
                    if not image_url:
                        print(f"⚠️ No image URL for {boat_name}")
                        return ""
                    response = requests.get(image_url, timeout=10)
                    if response.status_code == 200:
                        with open(file_path, 'wb') as f:
                            f.write(response.content)
                        return file_path
                    else:
                        print(f"⚠️ Failed to download image for {boat_name}: HTTP {response.status_code}")
                        return ""
                except Exception as e:
                    print(f"⚠️ Exception downloading image for {boat_name}: {e}")
                    return ""
            return file_path

        def download_and_store_image(boat_name, url):
            return cache_boat_image(boat_name, url)

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

            existing = existing_participants.get(uid)
            existing_image = existing["image_path"] if existing else ""
            image_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
            image_path = ""

            # Use existing image if it still exists
            if existing_image and os.path.exists(existing_image):
                image_path = existing_image
            elif image_url:
                download_tasks.append((uid, boat_name, image_url))
                image_path = os.path.join('static/images/boats', f"{uid}.jpg")
            else:
                print(f"🚫 No image URL found for: {boat_name}")
                image_path = ""

            updated_participants[uid] = {
                "uid": uid,
                "boat": boat_name,
                "type": boat_type,
                "image_path": image_path
            }

        # Download all missing images in parallel
        if download_tasks:
            print(f"📸 Downloading {len(download_tasks)} new boat images in parallel...")
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    executor.submit(cache_boat_image, bname, url): (uid, bname)
                    for uid, bname, url in download_tasks
                }
                for future in futures:
                    uid, bname = futures[future]
                    try:
                        result_path = future.result()
                        if not result_path or not os.path.exists(result_path):
                            print(f"❌ Image for {bname} failed to download.")
                            updated_participants[uid]["image_path"] = ""
                    except Exception as e:
                        print(f"❌ Error downloading image for {bname}: {e}")
                        updated_participants[uid]["image_path"] = ""

        updated_list = list(updated_participants.values())
        if updated_list != list(existing_participants.values()):
            with open("participants_master.json", "w") as f:
                json.dump(updated_list, f, indent=2)
            print(f"✅ Updated and saved {len(updated_list)} participants")
        else:
            print(f"✅ No changes detected — {len(updated_list)} participants already up-to-date")

    except Exception as e:
        print(f"⚠️ Error scraping participants: {e}")
        updated_list = []

    cache["participants"] = {"last_scraped": datetime.now().isoformat()}
    save_cache(cache)
    return updated_list

def scrape_events(force=False, skip_timestamp_check=False):
    cache = load_cache()
    settings = load_settings()

    if not force and is_cache_fresh(cache, "events", 2):
        print("✅ Event cache is fresh — skipping scrape.")
        if os.path.exists("events.json"):
            with open("events.json", "r") as f:
                return json.load(f)
        else:
            return []

    try:
        # Load tournament settings
        tournament = get_current_tournament()
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        remote_settings = requests.get(settings_url, timeout=30).json()

        matching_key = next((k for k in remote_settings if k.lower() == tournament.lower()), None)
        if not matching_key:
            raise Exception(f"Tournament '{tournament}' not found in settings.json")

        tournament_settings = remote_settings[matching_key]
        events_url = tournament_settings.get("events")
        if not events_url:
            raise Exception(f"No events URL found for {matching_key}")

        print(f"➡️ Events URL: {events_url}")

        # Ensure participant data is available
        if not os.path.exists("participants_master.json"):
            print("⚠️ participants_master.json missing — regenerating...")
            scrape_participants(force=True)

        try:
            with open("participants_master.json", "r") as f:
                participants = json.load(f)
            uid_lookup = {p["boat"].split(" ")[0].lower(): p["uid"] for p in participants}
        except Exception as e:
            print(f"❌ Failed to load participants: {e}")
            participants = []
            uid_lookup = {}

        # Load previous events
        existing = []
        last_known_ts = None
        if os.path.exists("events.json"):
            with open("events.json", "r") as f:
                existing = json.load(f)
                try:
                    last_known_ts = max(
                        date_parser.parse(e["timestamp"]) for e in existing if e.get("timestamp")
                    )
                except Exception as e:
                    print(f"⚠️ Failed to determine last known timestamp: {e}")

        # Scrape and parse new events
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

                # Timestamp filtering
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

            new_events.append({
                "timestamp": timestamp_iso,
                "event": event_type,
                "boat": boat_name,
                "uid": uid,
                "details": description
            })

        # Combine, sort, and save events
        all_events = existing + new_events
        all_events.sort(key=lambda e: e["timestamp"])

        with open("events.json", "w") as f:
            json.dump(all_events, f, indent=2)

        cache["events"] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)

        if new_events:
            print(f"✅ Appended {len(new_events)} new events (total now {len(all_events)})")
        else:
            print("✅ No new events to append.")

        return new_events

    except Exception as e:
        print(f"❌ Error in scrape_events: {e}")
        return []


def scrape_leaderboard(force=False):
    print("⚠️ scrape_leaderboard not implemented yet.")
    return []

def scrape_gallery(force=False):
    print("⚠️ scrape_gallery not implemented yet.")
    return []






@app.route('/')
def homepage():
    return send_from_directory('templates', 'index.html')

@app.route('/participants')
def participants_page():
    return send_from_directory('templates', 'participants.html')



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
        with open("participants_master.json", "r") as f:
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
        return jsonify({"status": "error", "message": str(e)})


@app.route("/scrape/events")
def get_events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")

    # 🟡 DEMO MODE
    if settings.get("data_source") == "demo":
        data = load_demo_data(tournament)
        all_events = data.get("events", [])

        now = datetime.now()
        filtered = []

        for e in all_events:
            try:
                ts = date_parser.parse(e["timestamp"])
                if ts.time() <= now.time():  # Only show events up to the current time of day
                    filtered.append(e)
            except Exception as ex:
                print(f"⚠️ Failed to parse timestamp in demo mode: {e.get('timestamp')}")
                continue

        filtered = sorted(filtered, key=lambda e: e["timestamp"], reverse=True)

        return jsonify({
            "status": "ok",
            "count": len(filtered),
            "events": filtered[:10]
        })

    # 🟢 LIVE MODE
    force = request.args.get("force", "false").lower() == "true"
    events = scrape_events(force=force)

    if not events and os.path.exists("events.json"):
        with open("events.json", "r") as f:
            events = json.load(f)

    events = sorted(events, key=lambda e: e["timestamp"], reverse=True)

    return jsonify({
        "status": "ok" if events else "error",
        "count": len(events),
        "events": events[:10]
    })






@app.route("/scrape/all")
def scrape_all():
    # Priority scrapes (blocking)
    events = scrape_events(force=True)
    participants = scrape_participants(force=True)

    # Background scrapes (non-blocking)
    run_in_thread(scrape_leaderboard, "leaderboard")
    run_in_thread(scrape_gallery, "gallery")

    return jsonify({
        "status": "ok",
        "events": len(events),
        "participants": len(participants),
        "message": "Scraped events & participants. Leaderboard & gallery running in background."
    })

from flask import render_template, request, jsonify

# JSON API endpoint
@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

        old_settings = load_settings()

        print("🧪 Checking if demo data needs saving...")
        print(f"Old settings: {old_settings}")
        print(f"New settings: {settings_data}")

        # Save new settings to disk
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_data, f, indent=4)

        old_tournament = old_settings.get("tournament")
        new_tournament = settings_data.get("tournament")
        new_mode = settings_data.get("data_source")

        if new_tournament != old_tournament:
            print(f"🔁 Tournament changed: {old_tournament} → {new_tournament}")
            if new_mode == "live":
                for f in ["events.json", "participants_master.json"]:
                    if os.path.exists(f):
                        os.remove(f)
                        print(f"🧹 Cleared {f} due to tournament change in live mode.")

                # Immediately warm cache in background
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
        print(f"📦 [DEMO] Manually generating demo data for {tournament}")

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

from dateutil import parser as date_parser

from dateutil import parser as date_parser

from datetime import datetime
from flask import jsonify

from flask import jsonify
from datetime import datetime
import json
import os

from flask import jsonify
from dateutil import parser as date_parser
from datetime import datetime

@app.route("/hooked")
def get_hooked_up_events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")

    if settings.get("data_source") == "demo":
        data = load_demo_data(tournament)
        events = data.get("events", [])
    else:
        if not os.path.exists(EVENTS_FILE):
            return jsonify({"status": "ok", "events": [], "count": 0})
        with open(EVENTS_FILE, "r") as f:
            events = json.load(f)

    now = datetime.now()
    current_time = now.time()

    # Build set of resolution times
    resolution_times = set()
    for event in events:
        if event["event"] in ["Released", "Boated"] or \
           "pulled hook" in event["details"].lower() or \
           "wrong species" in event["details"].lower():
            try:
                ts = date_parser.parse(event["timestamp"])
                resolution_times.add(ts.time() if settings.get("data_source") == "demo" else ts.isoformat())
            except:
                continue

    unresolved = []
    for event in events:
        if event["event"] != "Hooked Up":
            continue

        hookup_id = event.get("hookup_id", "")
        if "_" not in hookup_id:
            continue

        try:
            ts_str = hookup_id.rsplit("_", 1)[-1]
            ts = date_parser.parse(ts_str)
            key = ts.time() if settings.get("data_source") == "demo" else ts.isoformat()
            if key > current_time if settings.get("data_source") == "demo" else key not in resolution_times:
                unresolved.append(event)
        except Exception as e:
            print(f"⚠️ Failed to parse hookup_id timestamp: {hookup_id}")
            continue

    unresolved = sorted(unresolved, key=lambda e: e["timestamp"], reverse=True)

    print(f"📊 Hooked Up Unresolved Count: {len(unresolved)}")
    return jsonify({
        "status": "ok",
        "count": len(unresolved),
        "events": unresolved
    })





@app.route('/bluetooth/status')
def bluetooth_status():
    return jsonify({ "enabled": True })  # even as a stub for now

@app.route('/bluetooth/scan')
def bluetooth_scan():
    return jsonify({ "devices": [
        { "name": "Test Device", "mac": "00:11:22:33:44:55", "connected": False }
    ]})  # test mock

@app.route('/bluetooth/connect', methods=['POST'])
def bluetooth_connect():
    data = request.get_json()
    print("Connecting to:", data['mac'])
    return jsonify({ "status": "ok" })

@app.route('/bluetooth/disconnect', methods=['POST'])
def bluetooth_disconnect():
    data = request.get_json()
    print("Disconnecting from:", data['mac'])
    return jsonify({ "status": "ok" })

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
        print("⚠️ Error during Wi-Fi scan:", e)
        return jsonify({'networks': [], 'error': str(e)}), 500

@app.route('/wifi/connect', methods=['POST'])
def wifi_connect():
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        password = data.get('password')

        if not ssid:
            return jsonify({'status': 'error', 'message': 'Missing SSID'}), 400

        if password:
            cmd = ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password]
        else:
            cmd = ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid]

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
        return jsonify({ 'status': 'ok' })
    except subprocess.CalledProcessError as e:
        print(f"❌ Wi-Fi disconnect error: {e}")
        return jsonify({ 'status': 'error', 'message': str(e) }), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
