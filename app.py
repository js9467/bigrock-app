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
import subprocess
import time
from threading import Thread

app = Flask(__name__)

SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'
CACHE_FILE = 'cache.json'

def normalize_boat_name(name):
    if not name:
        return "unknown"
    return name.lower().replace(' ', '_').replace("'", "").replace("/", "_")

def get_current_tournament():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            return settings.get('tournament', 'Big Rock')
    except Exception as e:
        print(f"⚠️ Failed to load settings: {e}")
        return 'Big Rock'

def get_cache_path(tournament, filename):
    folder = os.path.join("cache", normalize_boat_name(tournament))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)

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

def run_in_thread(target, name):
    def wrapper():
        try:
            print(f"🧵 Starting {name} scrape in thread...")
            target()
            print(f"✅ Finished {name} scrape.")
        except Exception as e:
            print(f"❌ Error in {name} thread: {e}")
    Thread(target=wrapper).start()

@app.route('/')
def homepage():
    return send_from_directory('templates', 'index.html')

@app.route('/participants')
def participants_page():
    return send_from_directory('templates', 'participants.html')

@app.route('/settings-page/')
def settings_page():
    return send_from_directory('static', 'settings.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/participants_data')
def get_participants_data():
    try:
        tournament = get_current_tournament()
        participants_file = get_cache_path(tournament, "participants.json")
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
        return jsonify({"status": "error", "message": str(e)})

@app.route("/hooked")
def get_hooked_up_events():
    settings = load_settings()
    tournament = get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")

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
            old_key = normalize_boat_name(old_tournament)
            for fname in ["events.json", "participants.json"]:
                fpath = os.path.join("cache", old_key, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)
                    print(f"🧹 Cleared {fpath} due to tournament change.")
            run_in_thread(lambda: scrape_events(force=True), "events")
            run_in_thread(lambda: scrape_participants(force=True), "participants")
        return jsonify({'status': 'success'})
    return jsonify(load_settings())

# Placeholder routes (not yet implemented)
@app.route('/scrape/participants')
def scrape_participants_route():
    return jsonify({"status": "error", "message": "Not implemented in this snippet"})

@app.route('/scrape/events')
def scrape_events_route():
    return jsonify({"status": "error", "message": "Not implemented in this snippet"})

@app.route('/generate_demo')
def generate_demo():
    return jsonify({"status": "error", "message": "Not implemented in this snippet"})

@app.route("/scrape/all")
def scrape_all():
    return jsonify({"status": "error", "message": "Not implemented in this snippet"})

@app.route('/wifi/scan')
def wifi_scan():
    return jsonify({'networks': []})

@app.route('/wifi/connect', methods=['POST'])
def wifi_connect():
    return jsonify({'status': 'ok', 'message': 'connected'})

@app.route('/wifi/disconnect', methods=['POST'])
def wifi_disconnect():
    return jsonify({'status': 'ok'})

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
