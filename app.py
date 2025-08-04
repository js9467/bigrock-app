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
import subprocess
from threading import Thread
import smtplib
from email.mime.text import MI/METext
NOTIFIED_FILE = 'notified.json'

def load_notified_events():
    if os.path.exists(NOTIFIED_FILE):
        with open(NOTIFIED_FILE) as f:
            return set(json.load(f))
    return set()

def save_notified_events(notified_set):
    with open(NOTIFIED_FILE, 'w') as f:
        json.dump(list(notified_set), f)


SMTP_USER = "bigrockapp@gmail.com"        # Use Gmail or other SMTP
SMTP_PASS = "gie5Dieg!"          # Gmail app password
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def send_sms_email(phone_email, message):
    msg = MIMEText(message)
    msg['From'] = SMTP_USER
    msg['To'] = phone_email
    msg['Subject'] = "Boat Alert"

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [phone_email], msg.as_string())
        print(f"✅ Alert sent to {phone_email}")
    except Exception as e:
        print(f"⚠️ Failed to send to {phone_email}: {e}")



app = Flask(__name__)
CACHE_FILE = 'cache.json'
EVENTS_FILE = 'events.json'
SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'

def fetch_with_scraperapi(url):
    api_key = "e6f354c9c073ceba04c0fe82e4243ebd"
    full_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    try:
        response = requests.get(full_url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.text
        else:
            print(f"⚠️ ScraperAPI failed: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Error fetching via ScraperAPI: {e}")
    return ""

def get_cache_path(tournament, filename):
    folder = os.path.join("cache", normalize_boat_name(tournament))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)


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

def fetch_page_html(url, wait_selector=None, timeout=60000):
    proxy_url = f"http://api.scraperapi.com?api_key=e6f354c9c073ceba04c0fe82e4243ebd&url={url}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36")
            page.goto(proxy_url, wait_until="load", timeout=timeout)
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
    participants_file = get_cache_path(tournament, "participants.json")

    if not force and is_cache_fresh(cache, f"{tournament}_participants", 1440):
        print("✅ Participant cache is fresh — skipping scrape.")
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                return json.load(f)
        return []

    try:
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        settings = requests.get(settings_url, timeout=30).json()
        matching_key = next((k for k in settings if k.lower() == tournament.lower()), None)
        if not matching_key:
            raise Exception(f"Tournament '{tournament}' not found in settings.json")

        participants_url = settings[matching_key].get("participants")
        if not participants_url:
            raise Exception(f"No participants URL found for {matching_key}")

        print(f"📡 Scraping participants from: {participants_url}")

        existing_participants = {}
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                for p in json.load(f):
                    existing_participants[p["uid"]] = p

        html = fetch_with_scraperapi(participants_url)
        if not html:
            raise Exception("No HTML returned from ScraperAPI")

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
            local_path = image_path[1:] if image_path.startswith('/') else image_path

            force_download = (
                uid not in existing_participants or
                not image_path or
                not os.path.exists(local_path)
            )

            if force_download:
                if image_url:
                    download_tasks.append((uid, boat_name, image_url))
                    image_path = ""
                else:
                    image_path = "/static/images/boats/default.jpg"

            updated_participants[uid] = {
                "uid": uid,
                "boat": boat_name,
                "type": boat_type,
                "image_path": image_path
            }

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


def scrape_events(force=False, tournament=None):
    cache = load_cache()
    settings = load_settings()
    tournament = tournament or get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")

    if not force and is_cache_fresh(cache, f"events_{tournament}", 2):
        if os.path.exists(events_file):
            with open(events_file) as f:
                return json.load(f)
        return []

    try:
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        remote = requests.get(settings_url).json()
        key = next((k for k in remote if normalize_boat_name(k) == normalize_boat_name(tournament)), None)
        events_url = remote[key]["events"]

        html = fetch_page_html(events_url, "article.m-b-20, article.entry, div.activity, li.event, div.feed-item")
        soup = BeautifulSoup(html, 'html.parser')
        events = []
        seen = set()

        participants_file = get_cache_path(tournament, "participants.json")
        participants = {}
        if os.path.exists(participants_file):
            with open(participants_file) as f:
                participants = {p["uid"]: p for p in json.load(f)}

        for article in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
            time_tag = article.select_one("p.pull-right")
            name_tag = article.select_one("h4.montserrat")
            desc_tag = article.select_one("p > strong")
            if not time_tag or not name_tag or not desc_tag:
                continue

            raw = time_tag.get_text(strip=True).replace("@", "").strip()
            try:
                ts = date_parser.parse(raw).replace(year=datetime.now().year).isoformat()
            except:
                continue

            boat = name_tag.get_text(strip=True)
            desc = desc_tag.get_text(strip=True)
            uid = normalize_boat_name(boat)

            # Use participant boat name if found
            if uid in participants:
                boat = participants[uid]["boat"]

            if "released" in desc.lower():
                event_type = "Released"
            elif "boated" in desc.lower():
                event_type = "Boated"
            elif "pulled hook" in desc.lower():
                event_type = "Pulled Hook"
            elif "wrong species" in desc.lower():
                event_type = "Wrong Species"
            else:
                event_type = "Other"

            # Deduplication check
            key = f"{uid}_{event_type}_{ts}"
            if key in seen:
                continue
            seen.add(key)

            events.append({
                "timestamp": ts,
                "event": event_type,
                "boat": boat,
                "uid": uid,
                "details": desc
            })

        events.sort(key=lambda e: e["timestamp"])
        with open(events_file, "w") as f:
            json.dump(events, f, indent=2)

        cache[f"events_{tournament}"] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        return events

    except Exception as e:
        print(f"❌ Error in scrape_events: {e}")
        return []


import requests, os, json
from bs4 import BeautifulSoup

CACHE_DIR = "cache"

def scrape_leaderboard(tournament):
    # Load settings.json from your GitHub
    settings_url = "https://js9467.github.io/Brtourney/settings.json"
    try:
        settings = requests.get(settings_url, timeout=10).json()
    except:
        print("⚠️ Could not fetch settings.json")
        return []

    t_info = settings.get(tournament)
    if not t_info or not t_info.get("leaderboard"):
        print(f"⚠️ No leaderboard URL for {tournament}")
        return []

    url = t_info["leaderboard"]
    print(f"🔄 Scraping leaderboard for {tournament}: {url}")
    try:
        r = requests.get(url, timeout=10, verify=False)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        print(f"❌ Failed to fetch leaderboard: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Example parsing: adapt to actual HTML
    leaderboard = []
    for row in soup.select("article.m-b-20")[:10]:  # Top 10
        name = row.select_one("h4.montserrat")
        if not name:
            continue
        boat_name = name.get_text(strip=True)
        # Optional: weight or points
        points_tag = row.select_one("p.pull-right")
        points = points_tag.get_text(strip=True) if points_tag else ""
        
        uid = boat_name.lower().replace(" ", "_").replace("'", "")
        image_path = f"/static/images/boats/{uid}.jpg"
        leaderboard.append({
            "boat": boat_name,
            "uid": uid,
            "points": points,
            "image": image_path
        })

    # Cache results
    t_dir = os.path.join(CACHE_DIR, tournament)
    os.makedirs(t_dir, exist_ok=True)
    lb_file = os.path.join(t_dir, "leaderboard.json")
    with open(lb_file, "w") as f:
        json.dump(leaderboard, f, indent=2)

    print(f"✅ Saved {len(leaderboard)} leaderboard entries for {tournament}")
    return leaderboard


# Routes
@app.route('/')
def homepage():
    return send_from_directory('templates', 'index.html')

@app.route('/participants')
def participants_page():
    return send_from_directory('static', 'participants.html')

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

@app.route("/participants_data")
def participants_data():
    print("📥 /participants_data requested")
    tournament = get_current_tournament()
    participants_file = get_cache_path(tournament, "participants.json")

    participants = []

    try:
        if not os.path.exists(participants_file):
            raise FileNotFoundError("🚫 No participants cache found")

        with open(participants_file) as f:
            participants = json.load(f)

        # Check if image paths are missing or broken
        missing_images = 0
        for p in participants:
            path = p.get("image_path", "")
            local_path = path[1:] if path.startswith("/") else path
            if not path or not os.path.exists(local_path):
                missing_images += 1

        if missing_images > 0:
            print(f"🚨 Detected {missing_images} missing or broken images — rescraping...")
            participants = scrape_participants(force=True)

    except Exception as e:
        print(f"⚠️ Error loading participants, rescraping: {e}")
        participants = scrape_participants(force=True)

    return jsonify({
        "status": "ok",
        "participants": participants,
        "count": len(participants)
    })





# Keep track of events we already alerted on
notified_events = set()

# Load notified events on startup
notified_events = load_notified_events()

@app.route('/events')
def get_events():
    events = load_events()  # your existing scrape or cache function
    followed_boats = load_followed_boats()  # list of uids like ["palmer_lou", "double_b"]

    alerts = load_alerts()
    global notified_events  # use the persisted set

    new_alerts_sent = 0
    for event in events:
        event_id = f"{event['uid']}_{event['timestamp']}"
        
        # Only alert if: followed boat + not already notified
        if event['uid'] in followed_boats and event_id not in notified_events:
            notified_events.add(event_id)

            message = f"{event['boat']} just {event['event']}! {event['details']}"
            for recipient in alerts:
                send_sms_email(recipient, message)
                new_alerts_sent += 1

    # Save notified events to persist across restarts
    if new_alerts_sent > 0:
        save_notified_events(notified_events)

    return jsonify(events)




@app.route("/scrape/events")
def get_events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")
    tournament = get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")
    participants_file = get_cache_path(tournament, "participants.json")

    # ✅ Ensure participants cache exists before scraping events
    if not os.path.exists(participants_file):
        print("⏳ No participants yet — scraping them first...")
        scrape_participants(force=True)

        # Optional: wait up to 5s (10 × 0.5s) for file creation
        for _ in range(10):
            if os.path.exists(participants_file):
                break
            time.sleep(0.5)

    # Demo mode logic
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
            "events": filtered 
        })

    force = request.args.get("force", "false").lower() == "true"
    events = scrape_events(force=force, tournament=tournament)

    if not events and os.path.exists(events_file):
        with open(events_file, "r") as f:
            events = json.load(f)

    events = sorted(events, key=lambda e: e["timestamp"], reverse=True)
    return jsonify({
        "status": "ok" if events else "error",
        "count": len(events),
        "events": events[:100]
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


@app.route("/status")
def get_status():
    try:
        cache = load_cache()
        tournament = get_current_tournament()
        data_source = load_settings().get("data_source", "live")
        status = {
            "mode": data_source,
            "tournament": tournament,
            "participants_last_scraped": None,
            "events_last_scraped": None,
            "participants_cache_fresh": False,
            "events_cache_fresh": False,
        }

        # Build dynamic keys
        part_key = f"{tournament}_participants"
        event_key = f"{tournament}_events"

        # Check and format timestamps
        if part_key in cache:
            ts = cache[part_key].get("last_scraped")
            status["participants_last_scraped"] = ts
            status["participants_cache_fresh"] = is_cache_fresh(cache, part_key, 1440)

        if event_key in cache:
            ts = cache[event_key].get("last_scraped")
            status["events_last_scraped"] = ts
            status["events_cache_fresh"] = is_cache_fresh(cache, event_key, 2)

        return jsonify(status)

    except Exception as e:
        print(f"❌ Error in /status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

        old_settings = load_settings()
        old_tournament = old_settings.get("tournament")
        new_tournament = settings_data.get("tournament")
        new_mode = settings_data.get("data_source")

        # Ensure sound fields exist in the saved file
        settings_data.setdefault("followed_sound", old_settings.get("followed_sound", "1904_champagne-cork-pop-02"))
        settings_data.setdefault("boated_sound", old_settings.get("boated_sound", "1804_doorbell-02"))

        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_data, f, indent=4)

        if new_tournament != old_tournament and new_mode == "live":
            print(f"🔄 Tournament changed: {old_tournament} → {new_tournament}")
            run_in_thread(lambda: scrape_events(force=True, tournament=new_tournament), "events")
            run_in_thread(lambda: scrape_participants(force=True), "participants")

        save_demo_data_if_needed(settings_data, old_settings)

        return jsonify({'status': 'success'})

    # GET: ensure sound fields exist
    settings = load_settings()
    settings.setdefault("followed_sound", "1904_champagne-cork-pop-02")
    settings.setdefault("boated_sound", "1804_doorbell-02")
    return jsonify(settings)



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


from flask import render_template

from flask import send_from_directory

@app.route("/leaderboard")
def leaderboard_page():
    return send_from_directory('static', 'leaderboard.html')

# Serve JSON data
@app.route("/api/leaderboard/<tournament>")
def get_leaderboard(tournament):
    t_dir = os.path.join(CACHE_DIR, tournament)
    lb_file = os.path.join(t_dir, "leaderboard.json")

    # Serve cache if available
    if os.path.exists(lb_file):
        with open(lb_file) as f:
            leaderboard = json.load(f)
    else:
        leaderboard = scrape_leaderboard(tournament)

    return jsonify({"status": "ok", "leaderboard": leaderboard})
    
    
@app.route("/hooked")
def get_hooked_up_events():
    settings = load_settings()
    tournament = settings.get("tournament", "Big Rock")
    data_source = settings.get("data_source", "live")
    now = datetime.now()

    # Load events
    if data_source == "demo":
        data = load_demo_data(tournament)
        events = data.get("events", [])
    else:
        events_file = get_cache_path(tournament, "events.json")
        if not os.path.exists(events_file):
            return jsonify({"status": "ok", "events": [], "count": 0})
        with open(events_file, "r") as f:
            events = json.load(f)

    # Sort by timestamp ascending to process sequentially
    try:
        events.sort(key=lambda e: date_parser.parse(e["timestamp"]))
    except:
        pass

    unresolved = []

    if data_source == "demo":
        # Existing demo logic (hookup_id based)
        resolution_lookup = set()
        for e in events:
            if e["event"] in ["Released", "Boated"] or \
               "pulled hook" in e.get("details", "").lower() or \
               "wrong species" in e.get("details", "").lower():
                try:
                    ts = date_parser.parse(e["timestamp"]).replace(microsecond=0)
                    if ts.time() > now.time():  # future events in demo mode are ignored
                        continue
                    resolution_lookup.add((e["uid"], ts.isoformat()))
                except:
                    continue

        for e in events:
            if e["event"] != "Hooked Up":
                continue
            try:
                ts = date_parser.parse(e["timestamp"]).replace(microsecond=0)
                if ts.time() > now.time():
                    continue
            except:
                continue

            try:
                uid, ts_str = e.get("hookup_id", "").rsplit("_", 1)
                target_ts = date_parser.parse(ts_str).replace(microsecond=0).isoformat()
            except:
                unresolved.append(e)
                continue

            if (uid, target_ts) not in resolution_lookup:
                unresolved.append(e)

    else:
        # 🔹 Live mode: sequential clearing logic
        boat_hooks = {}  # uid -> list of unresolved hooked events

        for e in events:
            uid = e.get("uid")
            if not uid:
                continue

            if e["event"] == "Hooked Up":
                # Add this hooked event to unresolved list for that boat
                boat_hooks.setdefault(uid, []).append(e)

            else:
                # This is a resolution event: Boated / Released / Pulled Hook / Wrong Species
                if uid in boat_hooks and boat_hooks[uid]:
                    # Remove oldest unresolved hooked event for that boat
                    boat_hooks[uid].pop(0)

        # Collect all unresolved events in chronological order
        for hooks in boat_hooks.values():
            unresolved.extend(hooks)

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

@app.route('/wifi/scan')
def wifi_scan():
    try:
        scan_result = subprocess.check_output(['nmcli', '-t', '-f', 'SSID,SIGNAL,IN-USE', 'dev', 'wifi'], text=True)
        seen = {}
        connected_ssid = None

        for line in scan_result.strip().split('\n'):
            parts = line.strip().split(':')
            if len(parts) >= 3:
                ssid, signal, in_use = parts
                if not ssid.strip():
                    continue  # Skip empty SSIDs

                try:
                    signal = int(signal)
                except ValueError:
                    continue  # Skip invalid signal entries

                is_connected = in_use.strip() == '*'

                # Keep only the strongest signal or the connected one
                if ssid not in seen or is_connected or signal > seen[ssid]['signal']:
                    seen[ssid] = {
                        'ssid': ssid,
                        'signal': signal,
                        'connected': is_connected
                    }

                if is_connected:
                    connected_ssid = ssid

        networks = list(seen.values())
        return jsonify({'networks': networks, 'connected': connected_ssid})
    except Exception as e:
        print(f"❌ Wi-Fi scan error: {e}")
        return jsonify({'networks': [], 'connected': None})



@app.route('/wifi/connect', methods=['POST'])
def wifi_connect():
    data = request.get_json()
    ssid = data.get('ssid')
    password = data.get('password', '')

    if not ssid:
        return jsonify({'status': 'error', 'message': 'Missing SSID'}), 400

    try:
        print(f"🔌 Attempting connection to: {ssid}")

        # Attempt to connect (without disconnecting current Wi-Fi)
        cmd = ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]

        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        print(f"✅ Connected: {result}")

        # Optional: delete old connections if you only want one active profile
        # subprocess.run(['sudo', 'nmcli', 'connection', 'delete', 'OldSSID'], check=False)

        return jsonify({'status': 'ok', 'message': result})

    except subprocess.CalledProcessError as e:
        # If connection fails, we do NOT disconnect the current Wi-Fi
        print(f"❌ nmcli error: {e.output}")
        if "Secrets were required" in e.output:
            return jsonify({
                'status': 'error',
                'message': 'Password required for new network',
                'code': 'password_required'
            }), 400
        return jsonify({'status': 'error', 'message': e.output.strip()}), 500




@app.route('/wifi/disconnect', methods=['POST'])
def wifi_disconnect():
    try:
        result = subprocess.check_output(['nmcli', '-t', '-f', 'NAME,TYPE,DEVICE', 'con', 'show', '--active'], text=True)
        lines = result.strip().split('\n')

        for line in lines:
            parts = line.strip().split(':')
            if len(parts) < 3:
                continue
            name, ctype, device = parts
            if ctype == 'wifi':
                print(f"🚫 Disconnecting Wi-Fi connection: {name}")
                subprocess.check_call(['nmcli', 'con', 'down', name])
                return jsonify({'status': 'ok', 'message': f'Disconnected from {name}'})

        # Fallback: try to disconnect wlan0 directly if no connection name found
        print("⚠️ No connection name found — disconnecting wlan0 directly...")
        subprocess.check_call(['nmcli', 'device', 'disconnect', 'wlan0'])
        return jsonify({'status': 'ok', 'message': 'Disconnected wlan0'})

    except subprocess.CalledProcessError as e:
        print(f"❌ Wi-Fi disconnect error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500



@app.route('/launch_keyboard', methods=['POST'])
def launch_keyboard():
    try:
        env = os.environ.copy()
        env['DISPLAY'] = ':0'
        env['XAUTHORITY'] = '/home/pi/.Xauthority'
        subprocess.Popen(['onboard'], env=env)
        return jsonify({"status": "launched"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/hide_keyboard', methods=['POST'])
def hide_keyboard():
    try:
        subprocess.call(['pkill', '-f', 'onboard'])
        return jsonify({"status": "hidden"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/sounds')
def list_sounds():
    import os
    sound_dir = os.path.join('static', 'sounds')
    try:
        files = [f for f in os.listdir(sound_dir) if f.lower().endswith('.mp3')]
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'files': [], 'error': str(e)}), 500

@app.route('/alerts/test', methods=['GET'])
def test_alerts():
    alerts = load_alerts()
    if not alerts:
        return jsonify({"status": "no_subscribers"}), 404

    test_message = "🚤 Test Alert: Your Big Rock alerts are working!"
    success = []
    failures = []

    for recipient in alerts:
        try:
            send_sms_email(recipient, test_message)
            success.append(recipient)
        except Exception as e:
            print(f"⚠️ Failed to send to {recipient}: {e}")
            failures.append(recipient)

    return jsonify({
        "status": "sent",
        "success_count": len(success),
        "failures": failures
    })

@app.route('/api/version')
def api_version():
    try:
        with open("version.txt") as f:
            return jsonify({"version": f.read().strip()})
    except:
        return jsonify({"version": "Unknown"})

from collections import defaultdict

@app.route("/release-summary")
def release_summary_page():
    return send_from_directory('static', 'release-summary.html')

@app.route("/release-summary-data")
def release_summary_data():
    """Return per-day release counts for Blue, White, and Sailfish, supports demo mode."""
    try:
        tournament = get_current_tournament()
        settings = load_settings()
        demo_mode = settings.get("data_source") == "demo"

        # Load events from demo or cache
        if demo_mode:
            data = load_demo_data(tournament)
            all_events = data.get("events", [])
            now = datetime.now()
            # Filter out future events in demo mode
            events = [
                e for e in all_events
                if date_parser.parse(e["timestamp"]).time() <= now.time()
            ]
        else:
            events_file = get_cache_path(tournament, "events.json")
            if not os.path.exists(events_file):
                return jsonify({"status": "ok", "summary": []})
            with open(events_file, "r") as f:
                events = json.load(f)

        # Group by date
        from collections import defaultdict
        summary = defaultdict(lambda: {
            "blue_marlins": 0,
            "white_marlins": 0,
            "sailfish": 0,
            "total_releases": 0
        })

        for e in events:
            if e["event"].lower() != "released":
                continue

            try:
                dt = date_parser.parse(e["timestamp"])
                day = dt.strftime("%Y-%m-%d")
            except:
                continue

            details = e.get("details", "").lower()
            if "blue marlin" in details:
                summary[day]["blue_marlins"] += 1
            elif "white marlin" in details:
                summary[day]["white_marlins"] += 1
            elif "sailfish" in details:
                summary[day]["sailfish"] += 1

            summary[day]["total_releases"] += 1

        # Convert to sorted list
        result = [
            {"date": k, **v}
            for k, v in sorted(summary.items(), key=lambda x: x[0], reverse=True)
        ]

        return jsonify({"status": "ok", "demo_mode": demo_mode, "summary": result})

    except Exception as e:
        print(f"❌ Error generating release summary: {e}")
        return jsonify({"status": "error", "message": str(e)})






if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
