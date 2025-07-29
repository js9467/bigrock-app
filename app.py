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
from threading import Thread
import subprocess
import time

app = Flask(__name__)
SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'
CACHE_FILE = 'cache.json'

def normalize_boat_name(name):
    if not name:
        return "unknown"
    return name.lower().replace(' ', '_').replace("'", "").replace("/", "_")

def get_cache_path(tournament, filename):
    folder = os.path.join("cache", normalize_boat_name(tournament))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)

def get_current_tournament():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            return settings.get('tournament', 'Big Rock')
    except:
        return 'Big Rock'

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {}

def is_cache_fresh(cache, key, max_age_minutes):
    try:
        last_scraped = cache.get(key, {}).get("last_scraped")
        if not last_scraped:
            return False
        last_time = datetime.fromisoformat(last_scraped)
        return (datetime.now() - last_time) < timedelta(minutes=max_age_minutes)
    except:
        return False

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def fetch_page_html(url, wait_selector=None, timeout=30000):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="load", timeout=60000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout)
                except:
                    print(f"⚠️ Timeout waiting for selector: {wait_selector}")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"❌ Playwright error: {e}")
        return ""

def cache_boat_image(boat_name, image_url):
    folder = 'static/images/boats'
    os.makedirs(folder, exist_ok=True)
    safe_name = normalize_boat_name(boat_name)
    ext = os.path.splitext(image_url.split('?')[0])[-1] or ".jpg"
    file_path = os.path.join(folder, f"{safe_name}{ext}")

    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                if len(f.read()) > 0:
                    return f"/{file_path}"
        except:
            os.remove(file_path)

    try:
        if not image_url:
            return "/static/images/boats/default.jpg"
        response = requests.get(image_url, timeout=10)
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                f.write(response.content)
            return f"/{file_path}"
        else:
            return "/static/images/boats/default.jpg"
    except:
        if os.path.exists(file_path):
            os.remove(file_path)
        return "/static/images/boats/default.jpg"

def load_demo_data(tournament):
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, 'r') as f:
                data = json.load(f)
                return data.get(tournament, {'events': [], 'leaderboard': []})
        except:
            pass
    return {'events': [], 'leaderboard': []}
    def scrape_participants(force=False, tournament=None):
    cache = load_cache()
    tournament = tournament or get_current_tournament()
    cache_key = f"participants_{normalize_boat_name(tournament)}"
    if not force and is_cache_fresh(cache, cache_key, 1440):
        print("✅ Participant cache is fresh — skipping scrape.")
        return []

    try:
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        remote = requests.get(settings_url).json()
        key = next((k for k in remote if normalize_boat_name(k) == normalize_boat_name(tournament)), None)
        if not key:
            raise Exception("Tournament not found")
        participants_url = remote[key].get("participants")
        if not participants_url:
            raise Exception("No participants URL found")

        html = fetch_page_html(participants_url, "article.post.format-image")
        soup = BeautifulSoup(html, 'html.parser')
        participants = []
        seen = set()
        download_tasks = []

        participants_file = get_cache_path(tournament, "participants.json")
        existing = {}
        if os.path.exists(participants_file):
            with open(participants_file) as f:
                for p in json.load(f):
                    existing[p["uid"]] = p

        for article in soup.select("article.post.format-image"):
            name_tag = article.select_one("h2.post-title")
            type_tag = article.select_one("ul.post-meta li")
            img_tag = article.select_one("img")
            if not name_tag:
                continue
            boat = name_tag.get_text(strip=True)
            if ',' in boat or boat.lower() in seen:
                continue
            seen.add(boat.lower())
            uid = normalize_boat_name(boat)
            image_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
            image_path = existing.get(uid, {}).get("image_path", "")
            if not image_path or not os.path.exists(image_path[1:] if image_path.startswith('/') else image_path):
                if image_url:
                    download_tasks.append((uid, boat, image_url))
                else:
                    image_path = "/static/images/boats/default.jpg"
            participants.append({
                "uid": uid,
                "boat": boat,
                "type": type_tag.get_text(strip=True) if type_tag else "",
                "image_path": image_path
            })

        if download_tasks:
            print(f"📸 Downloading {len(download_tasks)} images...")
            with ThreadPoolExecutor(max_workers=6) as exec:
                futures = {exec.submit(cache_boat_image, b, url): u for u, b, url in download_tasks}
                for f in futures:
                    uid = futures[f]
                    try:
                        participants = [p if p["uid"] != uid else {**p, "image_path": f.result()} for p in participants]
                    except:
                        pass

        with open(participants_file, "w") as f:
            json.dump(participants, f, indent=2)
        cache[cache_key] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        return participants
    except Exception as e:
        print(f"⚠️ scrape_participants failed: {e}")
        return []

def scrape_events(force=False, tournament=None):
    cache = load_cache()
    tournament = tournament or get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")
    cache_key = f"events_{normalize_boat_name(tournament)}"

    if not force and is_cache_fresh(cache, cache_key, 2):
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
            events.append({
                "timestamp": ts,
                "event": event_type,
                "boat": boat,
                "uid": uid,
                "details": desc,
                "image_path": participants.get(uid, {}).get("image_path", "/static/images/boats/default.jpg")
            })

        events.sort(key=lambda e: e["timestamp"])
        with open(events_file, "w") as f:
            json.dump(events, f, indent=2)
        cache[cache_key] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        return events
    except Exception as e:
        print(f"❌ Error in scrape_events: {e}")
        return []

def inject_hooked_up_events(events, tournament):
    demo_events = []
    inserted = set()
    for event in events:
        event_type = event.get("event", "")
        details = event.get("details", "").lower()
        is_resolution = (
            event_type == "Boated" or
            (event_type == "Released" and not re.search(r"\b\w+\s+\w+\s+released\b", details)) or
            ("pulled hook" in details) or
            ("wrong species" in details)
        )
        if not is_resolution:
            continue
        try:
            ts = date_parser.parse(event["timestamp"])
            delta = timedelta(minutes=random.randint(3, 30))
            demo_ts = ts - delta
            key = f"{event['uid']}_{event['timestamp']}"
            if key in inserted:
                continue
            demo_events.append({
                "timestamp": demo_ts.isoformat(),
                "event": "Hooked Up",
                "boat": event["boat"],
                "uid": event["uid"],
                "details": "Hooked up!",
                "hookup_id": key
            })
            inserted.add(key)
        except:
            continue
    all_events = sorted(demo_events + events, key=lambda e: e["timestamp"])
    return all_events
@app.route('/events')
def events():
    mode = load_settings().get("data_source", "live")
    tournament = get_current_tournament()
    if mode == "demo":
        data = load_demo_data(tournament)
        return jsonify(data.get("events", []))
    return jsonify(scrape_events())

@app.route('/hooked')
def hooked():
    mode = load_settings().get("data_source", "live")
    tournament = get_current_tournament()
    now = datetime.now().time()

    if mode == "demo":
        demo = load_demo_data(tournament).get("events", [])
        hooked = []
        resolved = set()
        for e in demo:
            if e["event"] in ["Boated", "Released", "Pulled Hook", "Wrong Species"]:
                resolved.add(e.get("hookup_id"))
        for e in demo:
            if e["event"] == "Hooked Up":
                hookup_time = date_parser.parse(e["timestamp"]).time()
                if e.get("hookup_id") not in resolved and hookup_time <= now:
                    hooked.append(e)
        return jsonify(hooked)
    return jsonify([])

@app.route('/generate_demo')
def generate_demo():
    tournament = get_current_tournament()
    print(f"📦 [DEMO] Generating demo data for {tournament}")
    events = scrape_events(force=True)
    injected = inject_hooked_up_events(events, tournament)
    demo_data = {}
    if os.path.exists(DEMO_DATA_FILE):
        with open(DEMO_DATA_FILE, 'r') as f:
            demo_data = json.load(f)
    demo_data[tournament] = {
        "events": injected,
        "leaderboard": []
    }
    with open(DEMO_DATA_FILE, 'w') as f:
        json.dump(demo_data, f, indent=2)
    print(f"✅ [DEMO] Injected {len(injected)} demo events")
    return jsonify({"status": "ok", "events": len(injected)})

@app.route('/scrape/participants')
def scrape_participants_route():
    participants = scrape_participants(force=True)
    return jsonify({"status": "ok", "count": len(participants)})

@app.route('/scrape/events')
def scrape_events_route():
    events = scrape_events(force=True)
    return jsonify({"status": "ok", "count": len(events)})

@app.route('/participants_data')
def participants_data():
    tournament = get_current_tournament()
    path = get_cache_path(tournament, "participants.json")
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_data, f, indent=2)
        return jsonify({'status': 'ok'})
    return jsonify(load_settings())

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    print("🚀 App starting...")
    app.run(host='0.0.0.0', port=5000)

