import json
import os
import requests
from flask import Flask, jsonify, request, render_template, render_template_string
from datetime import datetime, time as dt_time
import random
import subprocess
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

app = Flask(__name__, template_folder='static')

SETTINGS_FILE = 'settings.json'
MOCK_DATA_FILE = 'mock_data.json'
HISTORICAL_DATA_FILE = 'historical_data.json'
CACHE_FILE = 'cache.json'
PARTICIPANTS_CACHE_FILE = 'participants.json'
PARTICIPANTS_CACHE = {'last_time': 0, 'data': []}


def get_current_tournament():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            return settings.get("tournament", "Big Rock").lower()
    except Exception as e:
        print("⚠️ Could not load tournament from settings:", e)
        return "bigrock"


def cache_boat_image(boat_name, image_url):
    folder = 'static/images/boats'
    os.makedirs(folder, exist_ok=True)
    safe_name = boat_name.replace(' ', '_').replace('/', '_')
    file_path = os.path.join(folder, f"{safe_name}.jpg")
    
    if not os.path.exists(file_path):
        try:
            response = requests.get(image_url, timeout=5)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
        except Exception as e:
            print(f"Failed to download image for {boat_name}: {e}")

    return f"/static/images/boats/{safe_name}.jpg"


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


def check_internet():
    try:
        subprocess.check_call(['ping', '-c', '1', '8.8.8.8'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def scrape_edisto_playwright():
    with sync_playwright() as p:
        print("🌐 Scraping Edisto participants...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.reeltimeapps.com/live/tournaments/2025-edisto-invitational-billfish/participants", timeout=60000)
        page.wait_for_timeout(10000)
        html = page.content()
        browser.close()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.col-sm-3.col-md-3.col-lg-3")
        print(f"✅ Found {len(cards)} teams")

        teams = []
        for card in cards:
            name_tag = card.select_one("h2.post-title")
            img_tag = card.select_one("img.img-responsive")
            if name_tag and img_tag:
                name = name_tag.text.strip()
                image_url = img_tag["src"].strip()
                cached_url = cache_boat_image(name, image_url)
                teams.append({"name": name, "image": cached_url})

        print("📋 Scraped Teams:")
        for t in teams:
            print(f"- {t['name']}: {t['image']}")
        
        return teams


def scrape_bigrock_participants():
    boats = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.goto("https://thebigrock.com/participants", wait_until="load", timeout=120000)
            page.screenshot(path="static/debug.png")
            page.wait_for_selector("img", timeout=15000)
            html = page.content()
            browser.close()

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select(".elementor-widget-container")

            for card in cards:
                name_tag = card.find("h2")
                img_tag = card.find("img")
                if name_tag:
                    name = name_tag.get_text(strip=True)
                    image_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else None
                    local_image = cache_boat_image(name, image_url)
                    boats.append({"boat": name, "image": local_image})
    except Exception as e:
        print(f"❌ Playwright error for Big Rock: {e}")
    
    return boats


@app.route("/api/participants")
def get_participants():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock").lower()
    except Exception as e:
        print(f"⚠️ Failed to load settings.json: {e}")
        tournament = "big rock"

    print(f"🎯 Using tournament: {tournament}")
    if "edisto" in tournament:
        print("🔁 Running Edisto scraper...")
        data = scrape_edisto_playwright()
    else:
        print("🔁 Running Big Rock scraper...")
        data = scrape_bigrock_participants()

    return jsonify(data)


@app.route('/')
def index():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            tournament = settings.get("tournament", "Big Rock").lower().replace(" ", "-")
            logo_url = settings.get("logo_url", "")
    except Exception:
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


@app.route("/api/gallery")
def get_gallery():
    # Stubbed empty gallery to prevent frontend errors
    return jsonify([])


if __name__ == '__main__':
    if os.environ.get("FLASK_RUN_FROM_CLI") != "false":
        app.run(host='0.0.0.0', port=5000)
        
@app.route("/participants")
def participants_page():
    return app.send_static_file("participants.html")


if __name__ == '__main__':
    if os.environ.get("FLASK_RUN_FROM_CLI") != "false":
        app.run(host='0.0.0.0', port=5000)