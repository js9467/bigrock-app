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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr
from PIL import Image
import io
sent_demo_alerts = set()

ALERTS_FILE = 'alerts.json'
NOTIFIED_FILE = 'notified.json'

SMTP_USER = "bigrockapp@gmail.com"
SMTP_PASS = "coslxivgfqohjvto"  # Gmail App Password
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587




app = Flask(__name__)
CACHE_FILE = 'cache.json'
EVENTS_FILE = 'events.json'
SETTINGS_FILE = 'settings.json'
DEMO_DATA_FILE = 'demo_data.json'



def load_alerts():
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE) as f:
            return json.load(f)
    return []

def save_alerts(alerts):
    with open(ALERTS_FILE, 'w') as f:
        json.dump(alerts, f, indent=2)

def load_notified_events():
    if os.path.exists(NOTIFIED_FILE):
        with open(NOTIFIED_FILE) as f:
            return set(json.load(f))
    return set()


def save_notified_events(notified):
    with open(NOTIFIED_FILE, 'w') as f:
        json.dump(list(notified), f)

def send_sms_email(phone_email, message):
    msg = MIMEText(message)
    msg['From'] = SMTP_USER
    msg['To'] = phone_email
    msg['Subject'] = "Boat Alert"

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [phone_email], msg.as_string())

def send_boat_email_alert(event):
    boat = event.get('boat', 'Unknown')
    action = event.get('event', 'Activity')
    timestamp = event.get('timestamp', datetime.now().isoformat())
    uid = event.get('uid', 'unknown')
    details = event.get('details', 'No additional details provided')

    # ✅ Subject line includes details if available
    subject = f"{boat} {action}"
    if details and details.lower() != 'hooked up!':
        subject += f" — {details}"
    subject += f" at {timestamp}"

    # 🔹 Detect the real image file
    base_path = f"static/images/boats/{uid}"
    image_path = None
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        candidate = base_path + ext
        if os.path.exists(candidate):
            image_path = candidate
            break

    # 🔹 Fallback to Palmer Lou if missing
    if not image_path and os.path.exists("static/images/palmer_lou.jpg"):
        print(f"⚠️ No image for {boat}, using fallback Palmer Lou")
        image_path = "static/images/palmer_lou.jpg"

    recipients = load_alerts()
    if not recipients:
        return 0

    success = 0

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)

            for recipient in recipients:
                try:
                    msg = MIMEMultipart("related")
                    msg['From'] = formataddr(("BigRock Alerts", SMTP_USER))
                    msg['To'] = recipient
                    msg['Subject'] = subject  # ✅ Now includes details

                    msg_alt = MIMEMultipart("alternative")
                    msg.attach(msg_alt)

                    # ✅ Plain text version
                    text_body = f"""🚤 {boat} {action}!
Time: {timestamp}
Details: {details}

BigRock Live Alert
"""
                    msg_alt.attach(MIMEText(text_body, "plain"))

                    # ✅ HTML version
                    html_body = f"""
                    <html><body>
                        <p>🚤 <b>{boat}</b> {action}!<br>
                        Time: {timestamp}<br>
                        Details: {details}</p>
                        <img src="cid:boat_image" style="max-width: 600px; height: auto;">
                    </body></html>
                    """
                    msg_alt.attach(MIMEText(html_body, "html"))

                    # 🔹 Attach image if available
                    if image_path and os.path.exists(image_path):
                        with Image.open(image_path) as img:
                            if img.mode in ("RGBA", "LA"):
                                img = img.convert("RGB")
                            img.thumbnail((600, 600))
                            img_bytes = io.BytesIO()
                            img.save(img_bytes, format="JPEG", quality=70)
                            img_bytes.seek(0)
                            image = MIMEImage(img_bytes.read(), name=f"{uid}.jpg")
                            image.add_header("Content-ID", "<boat_image>")
                            image.add_header("Content-Disposition", "inline", filename=f"{uid}.jpg")
                            msg.attach(image)

                    server.sendmail(SMTP_USER, [recipient], msg.as_string())
                    print(f"✅ Email alert sent to {recipient} for {boat} {action}")
                    success += 1

                except Exception as e:
                    print(f"❌ Failed to send alert to {recipient}: {e}")

    except Exception as e:
        print(f"❌ SMTP batch failed: {e}")

    return success



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

from threading import Lock

# Shared lock dictionary for image files
image_locks = {}

def cache_boat_image(boat_name, image_url):
    folder = BOAT_FOLDER
    os.makedirs(folder, exist_ok=True)
    safe_name = normalize_boat_name(boat_name)

    # Extract original file extension
    ext = os.path.splitext(image_url.split('?')[0])[-1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        ext = '.jpg'

    file_path = os.path.join(folder, f"{safe_name}{ext}")

    lock = image_locks.setdefault(file_path, Lock())
    with lock:
        # ✅ If WebP version already exists, return it
        webp_path = os.path.join(folder, f"{safe_name}.webp")
        if os.path.exists(webp_path) and os.path.getsize(webp_path) > 0:
            return f"/{webp_path}"

        # ✅ If original exists and WebP exists, return WebP
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            optimize_boat_image(file_path)
            if os.path.exists(webp_path):
                return f"/{webp_path}"
            return f"/{file_path}"

        # 🔹 Download new image
        try:
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                print(f"✅ Downloaded image for {boat_name}: {file_path}")

                # 🔹 Optimize + Create WebP
                optimize_boat_image(file_path)

                # Prefer WebP if created
                if os.path.exists(webp_path):
                    return f"/{webp_path}"
                return f"/{file_path}"

            else:
                print(f"⚠️ Failed to download image for {boat_name}: HTTP {response.status_code}")
                return "/static/images/boats/default.jpg"

        except Exception as e:
            print(f"⚠️ Error downloading image for {boat_name}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
            return "/static/images/boats/default.jpg"




def inject_hooked_up_events(events, tournament=None):
    """
    Create synthetic Hooked Up events 5–120 min before resolution events.
    Does NOT alter the original resolution timestamps.
    """
    demo_events = []
    inserted_keys = set()
    today = datetime.now().date()

    # Sort by actual timestamp
    events.sort(key=lambda e: date_parser.parse(e["timestamp"]))

    for event in events:
        boat = event.get("boat", "Unknown")
        uid = event.get("uid", "unknown")
        etype = event.get("event", "").lower()
        details = event.get("details", "").lower()

        # Only inject for resolution events
        is_resolution = (
            "boated" in etype
            or "released" in etype
            or "pulled hook" in details
            or "wrong species" in details
        )
        if not is_resolution:
            continue

        try:
            # Keep resolution as-is (optional: shift date to today)
            orig_dt = date_parser.parse(event["timestamp"])
            res_dt = datetime.combine(today, orig_dt.time())
            event["timestamp"] = res_dt.isoformat()  # ✅ Demo uses today's date, same time

            # Create Hooked Up event 5–120 min before
            delta_minutes = random.randint(5, 120)
            hookup_dt = res_dt - timedelta(minutes=delta_minutes)
            if hookup_dt.date() < today:
                hookup_dt = datetime.combine(today, datetime.min.time()) + timedelta(minutes=1)

            key = f"{uid}_{res_dt.isoformat()}"
            if key in inserted_keys:
                continue

            demo_events.append({
                "timestamp": hookup_dt.isoformat(),
                "event": "Hooked Up",
                "boat": boat,
                "uid": uid,
                "details": "Hooked up!",
                "hookup_id": key
            })
            inserted_keys.add(key)

        except Exception as e:
            print(f"⚠️ Demo injection failed for {boat}: {e}")

    # Merge synthetic Hooked Up + original events, sort chronologically
    all_events = sorted(events + demo_events, key=lambda e: date_parser.parse(e["timestamp"]))
    print(f"📦 Returning {len(all_events)} events (with {len(demo_events)} hooked up injections)")
    return all_events



def save_demo_data_if_needed(settings, old_settings):
    if settings.get("data_source") == "demo":
        print("📦 [DEMO] Saving demo data...")
        tournament = settings.get("tournament", "Big Rock")
        try:
            events = scrape_events(force=True)
            leaderboard = scrape_leaderboard(tournament)
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

    # ✅ Check cache freshness (2 minutes)
    cache_key = f"events_{tournament}"
    if not force and is_cache_fresh(cache, cache_key, 2):
        if os.path.exists(events_file):
            with open(events_file) as f:
                return json.load(f)
        return []

    try:
        # Load tournament settings
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        remote = requests.get(settings_url, timeout=15).json()
        key = next(
            (k for k in remote if normalize_boat_name(k) == normalize_boat_name(tournament)),
            None
        )
        if not key:
            raise Exception(f"Tournament '{tournament}' not found in remote settings.json")

        events_url = remote[key].get("events")
        if not events_url:
            raise Exception(f"No events URL found for {tournament}")

        print(f"📡 Scraping events from: {events_url}")
        html = fetch_with_scraperapi(events_url)
        if not html:
            raise Exception("Failed to fetch events page HTML")

        soup = BeautifulSoup(html, 'html.parser')
        events = []
        seen = set()

        # Load participants for boat name normalization
        participants_file = get_cache_path(tournament, "participants.json")
        participants = {}
        if os.path.exists(participants_file):
            with open(participants_file) as f:
                participants = {p["uid"]: p for p in json.load(f)}

        # Parse all event-like elements
        for article in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
            time_tag = article.select_one("p.pull-right")
            name_tag = article.select_one("h4.montserrat")
            desc_tag = article.select_one("p > strong")
            if not time_tag or not name_tag or not desc_tag:
                continue

            # Parse timestamp
            raw = time_tag.get_text(strip=True).replace("@", "").strip()
            try:
                ts = date_parser.parse(raw).replace(year=datetime.now().year).isoformat()
            except:
                continue

            # Normalize boat and event
            boat = name_tag.get_text(strip=True)
            desc = desc_tag.get_text(strip=True)
            uid = normalize_boat_name(boat)

            # Use official participant boat name if available
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

            # Deduplicate
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

        # Sort and save
        events.sort(key=lambda e: e["timestamp"])
        with open(events_file, "w") as f:
            json.dump(events, f, indent=2)

        cache[cache_key] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        print(f"✅ Scraped {len(events)} events for {tournament}")
        return events

    except Exception as e:
        print(f"❌ Error in scrape_events: {e}")
        return []


import requests, os, json
from bs4 import BeautifulSoup

CACHE_DIR = "cache"

import os, json, time
from bs4 import BeautifulSoup
import requests

LEADERBOARD_CACHE = "cache/leaderboard.json"
LEADERBOARD_URL = "https://tournament.thebigrock.com/leaderboard"  # Replace with your live URL

CATEGORY_MAP = {
    "blue marlin": "BLUE_MARLIN",
    "release": "RELEASE",
    "tuna": "TUNA",
    "dolphin": "DOLPHIN",
    "mahi": "DOLPHIN",
    "wahoo": "WAHOO"
}
import re

def split_boat_and_type(raw_text):
    """
    Split 'Rebelette64' Jarrett Bay' -> ('Rebelette', "64' Jarrett Bay")
    """
    match = re.match(r"^([A-Za-z0-9' \-]+?)(\d{2,2}.*)?$", raw_text.strip())
    if match:
        boat = match.group(1).strip()
        btype = (match.group(2) or "").strip()
        return boat, btype
    return raw_text.strip(), ""

def scrape_leaderboard(tournament=None, force=False):
    tournament = tournament or get_current_tournament()
    cache_file = get_cache_path(tournament, "leaderboard.json")

    if not force and os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < 60:
            with open(cache_file) as f:
                return json.load(f)

    print(f"🔄 Scraping fixed leaderboard for {tournament}...")

    # Get leaderboard URL
    settings_url = "https://js9467.github.io/Brtourney/settings.json"
    remote = requests.get(settings_url, timeout=15).json()
    key = next((k for k in remote if normalize_boat_name(k) == normalize_boat_name(tournament)), None)
    if not key:
        return []
    leaderboard_url = remote[key].get("leaderboard")
    if not leaderboard_url:
        return []

    html = fetch_with_scraperapi(leaderboard_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    leaderboard = []

    for heading in soup.select("h2, h3"):
        category = heading.get_text(strip=True)
        table = heading.find_next("table")
        if not table:
            continue

        rows = table.select("tr")[1:]  # skip header
        for row in rows:
            cols = [c.get_text(strip=True) for c in row.select("td")]
            if len(cols) < 2:
                continue

            angler = None
            boat = ""
            boat_type = ""
            score_val = cols[-1]
            rank = cols[0]

            if len(cols) == 4:
                # Rank | Angler | Boat | Points/Weight
                angler = cols[1]
                boat, boat_type = split_boat_and_type(cols[2])
            elif len(cols) == 3:
                # Rank | Boat | Points/Weight
                boat, boat_type = split_boat_and_type(cols[1])
            else:
                # Unexpected format
                continue

            uid = normalize_boat_name(boat)
            score_type = "points" if score_val.replace(".", "", 1).isdigit() else "weight_lbs"

            leaderboard.append({
                "category": category,
                "rank": rank,
                "angler": angler,
                "boat": boat,
                "type": boat_type,
                "uid": uid,
                score_type: score_val,
                "image_path": f"/static/images/boats/{uid}.webp" if boat else ""
            })

    # Save cache
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(leaderboard, f, indent=2)

    print(f"✅ Leaderboard scraped: {len(leaderboard)} entries in {len(set(e['category'] for e in leaderboard))} categories")
    return leaderboard


MAX_IMG_SIZE = (400, 400)  # Max width/height
IMG_QUALITY = 70           # JPEG/WEBP quality
BOAT_FOLDER = "static/images/boats"

def optimize_boat_image(file_path):
    """Resize and compress a single boat image and save WebP version."""
    try:
        if not os.path.exists(file_path):
            return

        # Skip very small files (~already optimized)
        if os.path.getsize(file_path) < 50_000:
            return

        with Image.open(file_path) as img:
            img_format = img.format or "JPEG"

            # Resize in-place if larger than target
            if img.width > MAX_IMG_SIZE[0] or img.height > MAX_IMG_SIZE[1]:
                img.thumbnail(MAX_IMG_SIZE)

            # Overwrite original with optimized JPEG/PNG
            img.save(file_path, optimize=True, quality=IMG_QUALITY)

            # Create WebP version for faster browsers
            webp_path = os.path.splitext(file_path)[0] + ".webp"
            img.save(webp_path, format="WEBP", optimize=True, quality=IMG_QUALITY)

            print(f"✅ Optimized {os.path.basename(file_path)} ({img.width}x{img.height}) -> WebP saved")
    except Exception as e:
        print(f"⚠️ Failed to optimize {file_path}: {e}")


def optimize_all_boat_images():
    """Optimize all boat images in static folder (startup or fallback)."""
    os.makedirs(BOAT_FOLDER, exist_ok=True)
    optimized_count = 0
    for fname in os.listdir(BOAT_FOLDER):
        if fname.lower().endswith((".jpg", ".jpeg", ".png")):
            fpath = os.path.join(BOAT_FOLDER, fname)
            optimize_boat_image(fpath)
            optimized_count += 1
    print(f"🎉 Boat image optimization complete ({optimized_count} checked)")
    
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

@app.route("/scrape/leaderboard")
def scrape_leaderboard_route():
    force = request.args.get("force") == "1"
    tournament = get_current_tournament()
    data = scrape_leaderboard(tournament, force=force)
    return jsonify({"status": "ok" if data else "error", "leaderboard": data})


@app.route("/participants_data")
def participants_data():
    print("📥 /participants_data requested")
    tournament = get_current_tournament()
    participants_file = get_cache_path(tournament, "participants.json")
    master_file = "participants_master.json"
    participants = []

    def prefer_webp(path: str) -> str:
        """Return .webp version if it exists, else original path."""
        if not path:
            return "/static/images/bigrock.png"
        base, ext = os.path.splitext(path)
        webp_path = base + ".webp"
        # Remove leading slash for filesystem check
        if os.path.exists(webp_path.lstrip("/")):
            return webp_path
        return path

    try:
        # 1️⃣ Try tournament-specific participants.json
        if os.path.exists(participants_file) and os.path.getsize(participants_file) > 0:
            with open(participants_file) as f:
                participants = json.load(f)

        # 2️⃣ Fallback to participants_master.json filtered by tournament
        elif os.path.exists(master_file):
            with open(master_file) as f:
                master = json.load(f)
                participants = [
                    p for p in master
                    if tournament.lower() in p.get("display_name", "").lower()
                ]

        # 3️⃣ Final fallback: scan boat images in static folder
        if not participants:
            folder = "static/images/boats"
            os.makedirs(folder, exist_ok=True)
            for fname in os.listdir(folder):
                if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    uid = os.path.splitext(fname)[0]
                    participants.append({
                        "uid": uid,
                        "boat": uid.replace("_", " ").replace("-", " ").title(),
                        "type": "",
                        "image_path": f"/static/images/boats/{fname}"
                    })
            print(f"🛟 Fallback loaded {len(participants)} participants from images")

        # 🔹 Ensure every participant has a valid image path and prefer .webp
        for p in participants:
            p["image_path"] = prefer_webp(p.get("image_path", ""))

    except Exception as e:
        print(f"⚠️ Error loading participants: {e}")

    # 🔹 Always sort alphabetically by boat name
    participants.sort(key=lambda p: p.get("boat", "").lower())

    return jsonify({
        "status": "ok",
        "participants": participants,
        "count": len(participants)
    })





@app.route("/scrape/events")
def get_events():
    settings = load_settings()
    tournament = get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")
    participants_file = get_cache_path(tournament, "participants.json")

    # ✅ Ensure participants cache exists before scraping events
    if not os.path.exists(participants_file):
        print("⏳ No participants yet — scraping them first...")
        scrape_participants(force=True)
        # Wait briefly for participants to be saved
        for _ in range(10):
            if os.path.exists(participants_file):
                break
            time.sleep(0.5)

    # ✅ Demo mode logic
    if settings.get("data_source") == "demo":
        data = load_demo_data(tournament)
        all_events = data.get("events", [])
        now = datetime.now()

        # ✅ Filter out events that are in the future
        filtered = []
        for e in all_events:
            try:
                ts = date_parser.parse(e["timestamp"])
                if ts <= now:
                    filtered.append(e)
            except:
                continue

        # ✅ Sort newest first
        filtered.sort(key=lambda e: e["timestamp"], reverse=True)

        return jsonify({
            "status": "ok",
            "count": len(filtered),
            "events": filtered[:100]
        })

    # ✅ Live mode
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
    """Force-scrape all data (events, participants, leaderboard) for the current tournament."""
    tournament = get_current_tournament()
    print(f"🔁 Starting full scrape for tournament: {tournament}")

    # ✅ Force scrape participants first (ensures images for leaderboard)
    participants = scrape_participants(force=True)

    # ✅ Force scrape events
    events = scrape_events(force=True, tournament=tournament)

    # ✅ Force scrape leaderboard (caches images from participants)
    leaderboard = scrape_leaderboard(tournament, force=True)

    return jsonify({
        "status": "ok",
        "tournament": tournament,
        "events": len(events),
        "participants": len(participants),
        "leaderboard": len(leaderboard),
        "message": "Scraped all data and cached it."
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

# ==========================================
# Alerts + Settings Combined Persistence
# ==========================================

@app.route('/alerts/list', methods=['GET'])
def list_alerts():
    """Return all alert subscriber emails/SMS gateways."""
    return jsonify(load_alerts())

@app.route('/alerts/subscribe', methods=['POST'])
def subscribe_alerts():
    """Add new alert subscribers to alerts.json."""
    data = request.get_json()
    new_emails = data.get('sms_emails', [])
    alerts = load_alerts()

    for email in new_emails:
        if email not in alerts:
            alerts.append(email)

    save_alerts(alerts)
    return jsonify({"status": "subscribed", "count": len(alerts)})

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr
from datetime import datetime
from PIL import Image
import os, io, smtplib

@app.route('/alerts/test', methods=['GET'])
def test_alerts():
    """Send a test email alert with Palmer Lou image inline in the email body."""
    boat_name = "Palmer Lou"
    action = "Hooked Up"
    action_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    image_path = "static/images/palmer_lou.jpg"

    recipients = load_alerts()
    if not recipients:
        return jsonify({"status": "no_subscribers"}), 404

    success = 0
    for recipient in recipients:
        try:
            # Create HTML email with inline image
            msg = MIMEMultipart("related")
            msg['From'] = formataddr(("BigRock Alerts", SMTP_USER))
            msg['To'] = recipient
            msg['Subject'] = f"{boat_name} {action} at {action_time}"

            # Create alternative plain+html body
            msg_alternative = MIMEMultipart("alternative")
            msg.attach(msg_alternative)

            # Plain text fallback
            text_body = f"🚤 {boat_name} {action}!\nTime: {action_time}\n\nBigRock Live Alert"
            msg_alternative.attach(MIMEText(text_body, "plain"))

            # HTML body referencing the inline image
            html_body = f"""
            <html>
            <body>
                <p>🚤 <b>{boat_name}</b> {action}!<br>
                Time: {action_time}</p>
                <img src="cid:boat_image" style="max-width: 600px; height: auto;">
            </body>
            </html>
            """
            msg_alternative.attach(MIMEText(html_body, "html"))

            # Attach the boat image inline
            if os.path.exists(image_path):
                try:
                    with Image.open(image_path) as img:
                        img.thumbnail((600, 600))
                        img_bytes = io.BytesIO()
                        img.save(img_bytes, format="JPEG", quality=70)
                        img_bytes.seek(0)
                        image = MIMEImage(img_bytes.read(), name=os.path.basename(image_path))
                        image.add_header("Content-ID", "<boat_image>")
                        image.add_header("Content-Disposition", "inline", filename=os.path.basename(image_path))
                        msg.attach(image)
                except Exception as e:
                    print(f"⚠️ Could not resize/attach image: {e}")
            else:
                print(f"❌ Image not found at {image_path}")

            # Send email
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [recipient], msg.as_string())

            print(f"✅ Test email sent to {recipient} with Palmer Lou image inline")
            success += 1

        except Exception as e:
            print(f"❌ Failed to send to {recipient}: {e}")

    return jsonify({"status": "sent", "success_count": success})




# ==========================================
# Settings API with Alerts Integration
# ==========================================

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """Get or update app settings, including alert recipients."""
    if request.method == 'POST':
        settings_data = request.get_json()
        if not settings_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

        old_settings = load_settings()
        old_tournament = old_settings.get("tournament")
        new_tournament = settings_data.get("tournament")
        new_mode = settings_data.get("data_source")

        # ✅ Ensure sound fields exist
        settings_data.setdefault(
            "followed_sound",
            old_settings.get("followed_sound", "fishing reel")
        )
        settings_data.setdefault(
            "boated_sound",
            old_settings.get("boated_sound", "fishing reel")
        )

        # ✅ Save SMS/email alerts
        sms_emails = settings_data.get("sms_emails", [])
        save_alerts(sms_emails)

        # ✅ Save settings.json
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_data, f, indent=4)

        # ✅ Trigger scrapes if tournament changed in live mode
        if new_tournament != old_tournament and new_mode == "live":
            print(f"🔄 Tournament changed: {old_tournament} → {new_tournament}")
            run_in_thread(lambda: scrape_events(force=True, tournament=new_tournament), "events")
            run_in_thread(lambda: scrape_participants(force=True), "participants")

        # ✅ Handle demo mode data caching
        save_demo_data_if_needed(settings_data, old_settings)

        return jsonify({'status': 'success'})

    # ----- GET Settings -----
    settings = load_settings()
    settings.setdefault("followed_sound", "Fishing Reel")
    settings.setdefault("boated_sound", "Fishing Reel")

    # ✅ Include alerts in GET response
    settings["sms_emails"] = load_alerts()

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

@app.route("/api/leaderboard")
def api_leaderboard():
    """Return leaderboard for current tournament with image paths, using cache if fresh."""
    tournament = get_current_tournament()
    lb_file = get_cache_path(tournament, "leaderboard.json")
    participants_file = get_cache_path(tournament, "participants.json")

    # Load participants for image mapping
    participants = {}
    if os.path.exists(participants_file):
        with open(participants_file) as f:
            participants = {p["uid"]: p for p in json.load(f)}

    # ✅ Load from cache if <15 min old
    if os.path.exists(lb_file) and (time.time() - os.path.getmtime(lb_file)) < 900:
        with open(lb_file) as f:
            leaderboard = json.load(f)
    else:
        leaderboard = scrape_leaderboard(tournament, force=True)

    # ✅ Ensure each entry has the correct image path
    for entry in leaderboard:
        uid = entry["uid"]
        if uid in participants:
            entry["image_path"] = participants[uid].get("image_path", "/static/images/boats/default.jpg")
        else:
            entry["image_path"] = "/static/images/boats/default.jpg"

    # ✅ Overwrite cache with enriched data
    with open(lb_file, "w") as f:
        json.dump(leaderboard, f, indent=2)

    return jsonify({"status": "ok", "leaderboard": leaderboard})




@app.route("/hooked")
def get_hooked_up_events():
    settings = load_settings()
    tournament = get_current_tournament()
    data_source = settings.get("data_source", "live").lower()

    now = datetime.now()
    events = []

    # Load events from appropriate source
    if data_source == "demo":
        data = load_demo_data(tournament)
        events = data.get("events", [])
        # Only consider events that have "occurred" in demo timeline
        events = [
            e for e in events
            if date_parser.parse(e["timestamp"]) <= now
        ]
    else:
        events_file = get_cache_path(tournament, "events.json")
        if os.path.exists(events_file):
            with open(events_file, "r") as f:
                events = json.load(f)

    # Sort events chronologically
    events.sort(key=lambda e: date_parser.parse(e["timestamp"]))

    hooked_feed = []

    if data_source == "demo":
        # ✅ DEMO MODE: resolve using hookup_id
        resolved_ids = set()

        # Collect all resolution event keys
        for e in events:
            if e["event"] in ["Released", "Boated"] or \
               "pulled hook" in e.get("details", "").lower() or \
               "wrong species" in e.get("details", "").lower():
                # In demo mode, use event uid+timestamp as resolution key
                key = f"{e['uid']}_{date_parser.parse(e['timestamp']).replace(microsecond=0).isoformat()}"
                resolved_ids.add(key)

        for e in events:
            if e["event"] != "Hooked Up":
                continue

            key = e.get("hookup_id")
            if not key or key not in resolved_ids:
                hooked_feed.append(e)

    else:
        # ✅ LIVE MODE: resolve oldest hooked per boat
        active_hooks = {}  # boat_uid -> list of hooked events
        for e in events:
            uid = e.get("uid")
            etype = e.get("event", "").lower()

            if etype == "hooked up":
                active_hooks.setdefault(uid, []).append(e)
            elif etype in ["boated", "released"] or \
                 "pulled hook" in e.get("details", "").lower() or \
                 "wrong species" in e.get("details", "").lower():
                # Resolve oldest hooked for that boat if any
                if uid in active_hooks and active_hooks[uid]:
                    active_hooks[uid].pop(0)

        # Remaining hooked events are unresolved
        for boat_hooks in active_hooks.values():
            hooked_feed.extend(boat_hooks)

    # ✅ Sort newest first for feed
    hooked_feed.sort(key=lambda e: date_parser.parse(e["timestamp"]), reverse=True)

    return jsonify({
        "status": "ok",
        "count": len(hooked_feed),
        "events": hooked_feed[:50]  # limit to 50 to keep feed clean
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



import threading

import json, os, time, threading
from datetime import datetime
from dateutil import parser as date_parser

NOTIFIED_FILE = "notified.json"
emailed_events = set()

# ==========================================
# Email Alert System (Cleaned & Reliable)
# ==========================================

NOTIFIED_FILE = "notified.json"
emailed_events = set()

def load_emailed_events():
    """Load previously emailed events to avoid duplicates."""
    if os.path.exists(NOTIFIED_FILE):
        try:
            with open(NOTIFIED_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_emailed_events():
    """Save emailed events to disk."""
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(list(emailed_events), f)

def get_followed_boats():
    """Read followed boats list from settings.json."""
    settings = load_settings()
    # Ensure they are normalized to match uids
    return [normalize_boat_name(b) for b in settings.get("followed_boats", [])]

def should_email(event):
    """Only email if event is boated or boat is followed."""
    etype = event.get("event", "").lower()
    uid = event.get("uid", "")
    
    # Always send for boated events
    if "boated" in etype:
        return True

    # Send for followed boats
    followed_boats = get_followed_boats()
    if uid in followed_boats:
        return True

    return False

def process_new_event(event):
    """Send email for any new event exactly once."""
    global emailed_events
    uid = f"{event.get('timestamp')}_{event.get('uid')}_{event.get('event')}"

    # Skip duplicates
    if uid in emailed_events:
        return
    emailed_events.add(uid)
    save_emailed_events()

    if should_email(event):
        try:
            send_boat_email_alert(event)  # ✅ Use existing function
            print(f"📧 Email sent for {event['boat']} - {event['event']}")
        except Exception as e:
            print(f"❌ Email failed for {event['boat']}: {e}")

def background_event_emailer():
    global emailed_events
    emailed_events = load_emailed_events()
    print(f"📡 Email watcher started. Loaded {len(emailed_events)} previous notifications.")

    tournament = get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")

    # ✅ Preload recent events to prevent flood on startup
    try:
        if os.path.exists(events_file):
            with open(events_file) as f:
                events = json.load(f)
            events.sort(key=lambda e: e["timestamp"], reverse=True)

            # Preload the newest 50 events so they won't email immediately
            for e in events[:50]:
                uid = f"{e.get('timestamp')}_{e.get('uid')}_{e.get('event')}"
                emailed_events.add(uid)

            save_emailed_events()
            print(f"⏩ Preloaded {min(50, len(events))} events as already emailed to prevent flood")
    except Exception as e:
        print(f"⚠️ Failed to preload events: {e}")

    # ✅ Continuous watch loop
    while True:
        try:
            settings = load_settings()
            tournament = get_current_tournament()

            # Load events from demo or live
            if settings.get("data_source") == "demo":
                events = load_demo_data(tournament).get("events", [])
                now = datetime.now().time()
                events = [e for e in events if date_parser.parse(e["timestamp"]).time() <= now]
            else:
                if not os.path.exists(events_file):
                    time.sleep(5)
                    continue
                with open(events_file) as f:
                    events = json.load(f)

            # Check only the newest 50 events
            events.sort(key=lambda e: e["timestamp"], reverse=True)
            for e in events[:50]:
                process_new_event(e)  # Will only email if not in emailed_events

        except Exception as e:
            print(f"⚠️ Email watcher error: {e}")

        time.sleep(30)



def save_emailed_events():
    """Save emailed events to disk."""
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(list(emailed_events), f)





if __name__ == '__main__':
    print("🚀 Optimizing boat images on startup...")
    optimize_all_boat_images()

    # ✅ Start email watcher
    Thread(target=background_event_emailer, daemon=True).start()

    # ✅ Start Flask
    app.run(host='0.0.0.0', port=5000, debug=True)
