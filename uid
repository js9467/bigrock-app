from flask import Flask, jsonify, request, send_from_directory
from dateutil import parser as date_parser
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os, json, re, requests, subprocess, hashlib, random, time
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Files and constants
CACHE_FILE = 'cache.json'
SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'
EVENTS_FILE = 'events.json'
PARTICIPANTS_FILE = 'participants_master.json'
IMAGE_DIR = 'static/images/boats'

# Utilities
def normalize_boat_name(name):
    return re.sub(r'\W+', '_', name.strip().lower())

def load_json(file, default={}):
    try:
        if os.path.exists(file):
            with open(file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Failed to load {file}: {e}")
    return default

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

def get_current_tournament():
    return load_json(SETTINGS_FILE).get('tournament', 'Big Rock')

def is_cache_fresh(cache, key, max_age_minutes):
    try:
        last_scraped = cache.get(key, {}).get("last_scraped")
        if not last_scraped:
            return False
        last_time = datetime.fromisoformat(last_scraped)
        return (datetime.now() - last_time) < timedelta(minutes=max_age_minutes)
    except:
        return False

def fetch_page_html(url, wait_selector=None):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=60000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=30000)
                except:
                    print(f"⚠️ Selector {wait_selector} timeout")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"❌ Playwright error: {e}")
        return ""

def cache_boat_image(boat_name, image_url):
    uid = normalize_boat_name(boat_name)
    ext = os.path.splitext(image_url.split('?')[0])[-1] or ".jpg"
    path = os.path.join(IMAGE_DIR, f"{uid}{ext}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        try:
            r = requests.get(image_url, timeout=10)
            if r.status_code == 200:
                with open(path, 'wb') as f:
                    f.write(r.content)
        except Exception as e:
            print(f"⚠️ Failed to cache image for {boat_name}: {e}")
    return path

@app.route("/scrape/participants")
def scrape_participants():
    settings = load_json(SETTINGS_FILE)
    tournament = settings.get("tournament", "Big Rock")
    url = settings.get("participants")
    if not url:
        return jsonify({"status": "error", "message": "Missing URL"})

    html = fetch_page_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select(".participant-card")

    participants = []
    for card in cards:
        name_el = card.select_one(".participant-name")
        type_el = card.select_one(".participant-boat-type")
        img_el = card.select_one("img")
        if not name_el:
            continue

        boat = name_el.text.strip()
        boat_type = type_el.text.strip() if type_el else ""
        img_url = img_el['src'] if img_el and img_el.has_attr('src') else ""
        uid = normalize_boat_name(boat)
        image_path = cache_boat_image(boat, img_url) if img_url else ""

        participants.append({
            "boat": boat,
            "type": boat_type,
            "uid": uid,
            "image_path": image_path
        })

    save_json(PARTICIPANTS_FILE, participants)
    return jsonify({"status": "ok", "participants": participants})

@app.route("/hooked")
def get_hooked_up_events():
    settings = load_json(SETTINGS_FILE)
    tournament = settings.get("tournament", "Big Rock")
    mode = settings.get("data_source", "live")
    now = datetime.now()

    events = []
    if mode == "demo":
        demo = load_json(DEMO_DATA_FILE)
        events = demo.get(tournament, {}).get("events", [])
    elif os.path.exists(EVENTS_FILE):
        events = load_json(EVENTS_FILE)

    resolution_lookup = set()
    for e in events:
        if e["event"] in ["Released", "Boated"] or \
           "pulled hook" in e.get("details", "").lower() or \
           "wrong species" in e.get("details", "").lower():
            try:
                ts = date_parser.parse(e["timestamp"]).replace(microsecond=0)
                if mode == "demo" and ts.time() > now.time():
                    continue
                resolution_lookup.add((normalize_boat_name(e["boat"]), ts.isoformat()))
            except:
                continue

    unresolved = []
    for e in events:
        if e["event"] != "Hooked Up":
            continue
        try:
            ts = date_parser.parse(e["timestamp"]).replace(microsecond=0)
            if mode == "demo" and ts.time() > now.time():
                continue
        except:
            continue

        try:
            uid, ts_str = e.get("hookup_id", "").rsplit("_", 1)
            uid = normalize_boat_name(uid)
            resolved_ts = date_parser.parse(ts_str).replace(microsecond=0).isoformat()
        except:
            unresolved.append(e)
            continue

        if (uid, resolved_ts) not in resolution_lookup:
            unresolved.append(e)

    return jsonify({"status": "ok", "count": len(unresolved), "events": unresolved})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
