from flask import Flask, jsonify, request, render_template
import json
import os
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import time

app = Flask(__name__, template_folder='static')

# Constants
REMOTE_SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"
SETTINGS_FILE = "settings.json"
PARTICIPANTS_MASTER_FILE = "participants_master.json"

# Load settings

def load_remote_settings():
    try:
        return requests.get(REMOTE_SETTINGS_URL, verify=False, timeout=5).json()
    except Exception as e:
        print(f"⚠️ Failed to load remote settings: {e}")
        return {}

def get_current_tournament_settings():
    with open(SETTINGS_FILE) as f:
        local_settings = json.load(f)
    tournament_name = local_settings.get("tournament")
    remote_settings = load_remote_settings()
    return remote_settings.get(tournament_name)

def normalize_boat_name(name):
    return name.strip().lower().replace(' ', '_').replace('-', '_')

# Scrape participants
def scrape_participants():
    tournament_settings = get_current_tournament_settings()
    if not tournament_settings:
        return []
    url = tournament_settings.get("participants")
    uid_prefix = tournament_settings.get("uid", "default")

    if not url:
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=60000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, 'html.parser')
    participants = []

    for card in soup.select(".participant"):
        name = card.select_one(".name").get_text(strip=True)
        uid = f"{uid_prefix}_{normalize_boat_name(name)}"
        participants.append({
            "uid": uid,
            "boat": name,
            "angler": name,
            "image": f"/static/images/boats/{normalize_boat_name(name)}.jpg"
        })

    return participants

# Scrape events
def scrape_events():
    tournament_settings = get_current_tournament_settings()
    if not tournament_settings:
        return []
    url = tournament_settings.get("events")
    uid_prefix = tournament_settings.get("uid", "default")

    if not url:
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=60000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, 'html.parser')
    events = []

    for item in soup.select(".activity"):
        try:
            timestamp = item.select_one(".timestamp").get_text(strip=True)
            boat = item.select_one(".participant-name").get_text(strip=True)
            action = item.select_one(".action").get_text(strip=True)
            events.append({
                "time": timestamp,
                "boat": boat,
                "action": action,
                "hookup_id": item.get("data-hookup-id", None),
                "uid": f"{uid_prefix}_{normalize_boat_name(boat)}"
            })
        except:
            continue

    return events

# Scrape leaderboard
def scrape_leaderboard():
    tournament_settings = get_current_tournament_settings()
    if not tournament_settings:
        return []
    url = tournament_settings.get("leaderboard")

    if not url:
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=60000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, 'html.parser')
    leaderboard = []

    for row in soup.select(".leaderboard-row"):
        try:
            rank = row.select_one(".rank").get_text(strip=True)
            name = row.select_one(".team").get_text(strip=True)
            points = row.select_one(".points").get_text(strip=True)
            leaderboard.append({
                "rank": rank,
                "team": name,
                "points": points
            })
        except:
            continue

    return leaderboard

# Flask Routes
@app.route("/scrape/participants")
def participants_route():
    return jsonify(scrape_participants())

@app.route("/scrape/events")
def events_route():
    return jsonify(scrape_events())

@app.route("/scrape/leaderboard")
def leaderboard_route():
    return jsonify(scrape_leaderboard())

@app.route("/")
def index():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock")
    except:
        tournament = "Big Rock"

    logo_map = {
        "Big Rock": "/static/images/WHITELOGOBR.png",
        "Kids": "/static/images/WHITELOGOBR.png",
        "KWLA": "/static/images/WHITELOGOBR.png",
        "Edisto Invitational": "https://cdn.reeltimeapps.com/tournaments/logos/000/000/720/original/AppIconLight2025.png"
    }

    logo_url = logo_map.get(tournament, "/static/images/WHITELOGOBR.png")
    theme_class = f"theme-{tournament.lower().replace(' ', '-')}"

    return render_template("index.html", logo_url=logo_url, theme_class=theme_class)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
