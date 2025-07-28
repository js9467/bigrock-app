import os
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template
from playwright.sync_api import sync_playwright

app = Flask(__name__)

DATA_FOLDER = 'data'
IMAGE_FOLDER = 'static/images/boats'
PARTICIPANT_CACHE_FILE = os.path.join(DATA_FOLDER, 'participants_master.json')
DEMO_CACHE_FILE = os.path.join(DATA_FOLDER, 'demo_data.json')
SETTINGS_FILE = os.path.join(DATA_FOLDER, 'settings.json')

os.makedirs(DATA_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)


def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"tournament": "Big Rock", "data_source": "live"}


def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)


def get_uid(name):
    return name.lower().replace(' ', '_').replace("'", "").replace('"', '')


def cache_participant_image(boat, url):
    # Stub for downloading image if needed
    return f"{IMAGE_FOLDER}/{get_uid(boat)}.jpg"


def scrape_participants(force=False):
    settings = load_settings()
    tournament = settings.get("tournament")
    url = f"https://www.reeltimeapps.com/live/tournaments/67th-annual-{tournament.lower().replace(' ', '-')}-tournament/participants"
    now = time.time()
    if not force and os.path.exists(PARTICIPANT_CACHE_FILE):
        if now - os.path.getmtime(PARTICIPANT_CACHE_FILE) < 86400:
            with open(PARTICIPANT_CACHE_FILE, 'r') as f:
                return json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_selector(".participant")
        html = page.content()
        browser.close()

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    participants = []
    for card in soup.select('.participant'):
        boat = card.select_one('h3').text.strip()
        boat_type = card.select_one('p').text.strip()
        uid = get_uid(boat)
        participants.append({
            "boat": boat,
            "type": boat_type,
            "uid": uid,
            "image_path": f"{IMAGE_FOLDER}/{uid}.jpg"
        })

    with open(PARTICIPANT_CACHE_FILE, 'w') as f:
        json.dump(participants, f)
    return participants


def scrape_events(force=False):
    settings = load_settings()
    tournament = settings.get("tournament")
    url = f"https://www.reeltimeapps.com/live/tournaments/67th-annual-{tournament.lower().replace(' ', '-')}-tournament/activities"
    now = time.time()
    cache_file = f"{DATA_FOLDER}/events_{get_uid(tournament)}.json"
    last_events = []

    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            last_events = json.load(f)
        last_time = datetime.fromisoformat(last_events[-1]['timestamp']) if last_events else None
    else:
        last_time = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_selector("article.entry")
        html = page.content()
        browser.close()

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    new_events = []
    for article in soup.select("article.entry"):
        text = article.get_text()
        ts = article.select_one(".timestamp").text.strip()
        timestamp = datetime.strptime(ts, "%b %d, %Y %I:%M %p").isoformat()
        if last_time and datetime.fromisoformat(timestamp) <= last_time:
            continue
        for keyword in ['boated', 'released', 'lost']:
            if keyword in text.lower():
                boat = text.split(' ')[0].strip()
                event = 'Released' if 'released' in text else 'Boated' if 'boated' in text else 'Other'
                new_events.append({
                    "timestamp": timestamp,
                    "boat": boat,
                    "uid": get_uid(boat),
                    "event": event,
                    "details": text.strip()
                })
    all_events = last_events + new_events
    all_events.sort(key=lambda e: e['timestamp'])
    with open(cache_file, 'w') as f:
        json.dump(all_events, f)

    if settings['data_source'] == 'demo':
        inject_hooked_up_events(all_events)

    return all_events


def inject_hooked_up_events(events):
    synthetic = []
    for e in events:
        if e['event'] in ['Boated', 'Released', 'Other'] and 'hookup_id' not in e:
            minutes_back = 3 + hash(e['uid']) % 27
            hook_time = datetime.fromisoformat(e['timestamp']) - timedelta(minutes=minutes_back)
            synthetic.append({
                "timestamp": hook_time.isoformat(),
                "event": "Hooked Up",
                "boat": e['boat'],
                "uid": e['uid'],
                "hookup_id": f"{e['uid']}_{e['timestamp']}",
                "details": "Hooked up!"
            })
    full = sorted(events + synthetic, key=lambda e: e['timestamp'])
    tournament = load_settings()['tournament']
    with open(DEMO_CACHE_FILE, 'w') as f:
        json.dump({tournament: {"events": full}}, f)


@app.route('/')
def homepage():
    return render_template('index.html')


@app.route('/participants')
def participants():
    try:
        with open(PARTICIPANT_CACHE_FILE, 'r') as f:
            participants = json.load(f)
        return jsonify({"count": len(participants), "participants": participants, "status": "ok"})
    except Exception as e:
        return jsonify({"count": 0, "participants": [], "status": "error", "message": str(e)})


@app.route('/events')
def events():
    settings = load_settings()
    tournament = settings.get("tournament")
    source = settings.get("data_source")
    if source == 'demo':
        try:
            with open(DEMO_CACHE_FILE, 'r') as f:
                demo_data = json.load(f)
            events = demo_data.get(tournament, {}).get("events", [])
            return jsonify({"count": len(events), "events": events, "status": "ok"})
        except:
            return jsonify({"count": 0, "events": [], "status": "error"})
    else:
        events = scrape_events(force=True)
        return jsonify({"count": len(events), "events": events, "status": "ok"})


@app.route('/hooked')
def hooked():
    try:
        with open(DEMO_CACHE_FILE, 'r') as f:
            demo_data = json.load(f)
        events = demo_data.get(load_settings().get("tournament"), {}).get("events", [])
        hooked = [e for e in events if e.get("event") == "Hooked Up"]
        return jsonify({"count": len(hooked), "events": hooked, "status": "ok"})
    except:
        return jsonify({"count": 0, "events": [], "status": "error"})


@app.route('/settings', methods=['GET', 'POST'])
def update_settings():
    if request.method == 'POST':
        new_settings = request.json
        save_settings(new_settings)
        return jsonify({"status": "updated", "settings": new_settings})
    else:
        return jsonify(load_settings())


@app.route('/scrape/participants')
def scrape_participants_route():
    participants = scrape_participants(force=True)
    return jsonify({"count": len(participants), "participants": participants, "status": "ok"})


@app.route('/scrape/events')
def scrape_events_route():
    events = scrape_events(force=True)
    return jsonify({"count": len(events), "events": events, "status": "ok"})


@app.route('/participants.html')
def participants_page():
    return render_template('participants.html')


@app.route('/settings.html')
def settings_page():
    return render_template('settings.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)