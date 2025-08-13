# app.py — clean organized build (non-blocking cache-first)
from __future__ import annotations

# =========================
# Standard Library & 3rd-Party
# =========================
from flask import Flask, jsonify, request, send_from_directory
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from pathlib import Path
from collections import defaultdict
import json, os, re, time, random, subprocess, io, smtplib, requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr
from PIL import Image   # used only for email embedding (not file optimization)

# =========================
# Config
# =========================
app = Flask(__name__)

SETTINGS_FILE     = "settings.json"
CACHE_FILE        = "cache.json"              # legacy heartbeat for /status
DEMO_DATA_FILE    = "demo_data.json"
CACHE_ROOT        = Path("cache")
BOAT_IMAGE_DIR    = Path("static/images/boats")

ALERTS_FILE       = "alerts.json"
NOTIFIED_FILE     = "notified.json"

MASTER_JSON_URL   = "https://js9467.github.io/Brtourney/settings.json"
UA_POOL           = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
]

# Email (kept as provided)
SMTP_USER   = "bigrockapp@gmail.com"
SMTP_PASS   = "coslxivgfqohjvto"  # Gmail App Password
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT   = 587

emailed_events = set()  # in-memory set for dup prevention

# =========================
# Small Utilities
# =========================
def normalize_boat_name(name: str | None) -> str:
    if not name: return "unknown"
    return name.lower().replace("'", "").replace(" ", "_").replace("/", "_")

def get_data_source() -> str:
    s = load_settings()
    return (s.get("data_source") or s.get("mode") or "live").lower()

def get_current_tournament() -> str:
    try:
        with open(SETTINGS_FILE, "r") as f:
            return (json.load(f).get("tournament") or "Big Rock")
    except:
        return "Big Rock"

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f) or {}
        except:
            pass
    return {}

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f) or {}
        except:
            pass
    return {}

def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def ensure_json_file(path: Path, default):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(json.dumps(default, indent=2))

def non_blocking(fn, label="task"):
    def _runner():
        try:
            print(f"🧵 start {label}")
            fn()
            print(f"✅ done {label}")
        except Exception as e:
            print(f"❌ {label} failed: {e}")
    Thread(target=_runner, daemon=True).start()

def fetch_html(url: str, use_scraperapi: bool = False) -> str:
    """Direct fetch first (spoof UA), optional ScraperAPI fallback if desired."""
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    try:
        r = requests.get(url, headers=headers, timeout=45, verify=False)
        if r.status_code == 200 and r.text.strip():
            return r.text
        print(f"⚠️ Direct fetch got {r.status_code} for {url}")
    except Exception as e:
        print(f"⚠️ Direct fetch error for {url}: {e}")

    if use_scraperapi:
        api_key = os.getenv("SCRAPERAPI_KEY", "e6f354c9c073ceba04c0fe82e4243ebd")
        api = f"https://api.scraperapi.com?api_key={api_key}&keep_headers=true&url={requests.utils.quote(url, safe='')}"
        try:
            r = requests.get(api, headers=headers, timeout=60)
            if r.status_code == 200 and r.text.strip():
                return r.text
            print(f"⚠️ ScraperAPI failed: HTTP {r.status_code}")
        except Exception as e:
            print(f"❌ Error via ScraperAPI: {e}")

    time.sleep(1.0)
    try:
        r = requests.get(url, headers=headers, timeout=45, verify=False)
        if r.status_code == 200 and r.text.strip():
            return r.text
        print(f"⚠️ Final direct retry got {r.status_code} for {url}")
    except Exception as e:
        print(f"⚠️ Final direct retry error: {e}")
    return ""

# =========================
# Per-Tournament Cache Helper
# =========================
def tour_slug(name: str) -> str:
    return normalize_boat_name(name or "Big Rock")

class TourCache:
    """cache/<slug>/{events.json,participants.json,leaderboard.json,meta.json}"""
    def __init__(self, tournament: str):
        self.tournament = tournament
        self.slug = tour_slug(tournament)
        self.dir = CACHE_ROOT / self.slug
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = self.dir / "events.json"
        self.participants = self.dir / "participants.json"
        self.leaderboard = self.dir / "leaderboard.json"
        self.meta = self.dir / "meta.json"

    def _read_meta(self) -> dict:
        if self.meta.exists():
            try:
                return json.loads(self.meta.read_text() or "{}")
            except:
                return {}
        return {}

    def _write_meta(self, meta: dict):
        self.meta.write_text(json.dumps(meta, indent=2))

    def touch(self, key: str):
        meta = self._read_meta()
        meta.setdefault(key, {})
        meta[key]["last_scraped"] = datetime.now().isoformat()
        self._write_meta(meta)

    def mark_demo_built(self):
        meta = self._read_meta()
        meta.setdefault("demo", {})
        meta["demo"]["built_at"] = datetime.now().isoformat()
        self._write_meta(meta)

    def last_time(self, key: str) -> datetime | None:
        try:
            ts = self._read_meta().get(key, {}).get("last_scraped")
            return datetime.fromisoformat(ts) if ts else None
        except:
            return None

    def is_fresh(self, key: str, minutes: int) -> bool:
        ts = self.last_time(key)
        return bool(ts and (datetime.now() - ts) < timedelta(minutes=minutes))

def ensure_initialized(mode: str | None = None, tournament: str | None = None):
    """Create empty per-tournament JSONs so routes never block."""
    t = tournament or get_current_tournament()
    tc = TourCache(t)
    ensure_json_file(tc.events, [])
    ensure_json_file(tc.participants, [])
    ensure_json_file(tc.leaderboard, [])
    cache = load_cache()  # legacy for /status
    cache.setdefault(f"events_{t}", {"last_scraped": None})
    cache.setdefault(f"{t}_participants", {"last_scraped": None})
    cache.setdefault(f"{t}_leaderboard", {"last_scraped": None})
    save_cache(cache)
    if (mode or get_data_source()) == "demo":
        ensure_demo_ready(t, force_if_empty=True)

# =========================
# Alerts (persist + helpers)
# =========================
def load_alerts() -> list[str]:
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, "r") as f:
                return json.load(f) or []
        except:
            return []
    return []

def save_alerts(alerts: list[str]):
    with open(ALERTS_FILE, "w") as f:
        json.dump(alerts, f, indent=2)

def load_emailed_events() -> set[str]:
    if os.path.exists(NOTIFIED_FILE):
        try:
            with open(NOTIFIED_FILE, "r") as f:
                return set(json.load(f) or [])
        except:
            return set()
    return set()

def save_emailed_events():
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(list(emailed_events), f)

def get_followed_boats_norm() -> set[str]:
    settings = load_settings()
    return { normalize_boat_name(b) for b in settings.get("followed_boats", []) }

def should_email(event: dict) -> bool:
    etype = (event.get("event") or "").lower()
    uid = event.get("uid") or ""
    if "boated" in etype: return True
    return uid in get_followed_boats_norm()

def send_boat_email_alert(event: dict) -> int:
    """Send inline-image email (uses local image if present; fallback Palmer Lou)."""
    boat = event.get('boat', 'Unknown')
    action = event.get('event', 'Activity')
    timestamp = event.get('timestamp', datetime.now().isoformat())
    uid = event.get('uid', 'unknown')
    details = event.get('details', 'No additional details provided')

    subject = f"{boat} {action}"
    if details and details.lower() != 'hooked up!':
        subject += f" — {details}"
    subject += f" at {timestamp}"

    # detect image file (original only; we no longer optimize or convert)
    img_path = None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = (BOAT_IMAGE_DIR / f"{uid}{ext}")
        if candidate.exists() and candidate.stat().st_size > 0:
            img_path = str(candidate)
            break
    if not img_path and os.path.exists("static/images/palmer_lou.jpg"):
        img_path = "static/images/palmer_lou.jpg"

    recipients = load_alerts()
    if not recipients: return 0

    sent = 0
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)

        for rcpt in recipients:
            try:
                msg = MIMEMultipart("related")
                msg['From'] = formataddr(("BigRock Alerts", SMTP_USER))
                msg['To'] = rcpt
                msg['Subject'] = subject
                alt = MIMEMultipart("alternative"); msg.attach(alt)

                text_body = f"""🚤 {boat} {action}!
Time: {timestamp}
Details: {details}

BigRock Live Alert
"""
                alt.attach(MIMEText(text_body, "plain"))

                html_body = f"""
<html><body>
  <p>🚤 <b>{boat}</b> {action}!<br>Time: {timestamp}<br>Details: {details}</p>
  <img src="cid:boat_image" style="max-width: 600px; height: auto;">
</body></html>
"""
                alt.attach(MIMEText(html_body, "html"))

                if img_path and os.path.exists(img_path):
                    try:
                        with Image.open(img_path) as img:
                            img.thumbnail((600, 600))
                            buff = io.BytesIO()
                            img.save(buff, format="JPEG", quality=70)
                            buff.seek(0)
                            image = MIMEImage(buff.read(), name=os.path.basename(img_path))
                            image.add_header("Content-ID", "<boat_image>")
                            image.add_header("Content-Disposition", "inline", filename=os.path.basename(img_path))
                            msg.attach(image)
                    except Exception as e:
                        print(f"⚠️ Could not attach image: {e}")

                server.sendmail(SMTP_USER, [rcpt], msg.as_string())
                sent += 1
            except Exception as e:
                print(f"❌ Email to {rcpt} failed: {e}")
    return sent

# =========================
# Demo Injection
# =========================
def inject_hooked_up_events(events: list[dict], tournament: str | None = None) -> list[dict]:
    """Insert synthetic Hooked Up 5–120m before resolution events. Keep resolution times intact."""
    demo_events, inserted = [], set()
    today = datetime.now().date()
    events.sort(key=lambda e: date_parser.parse(e["timestamp"]))

    for e in events:
        boat = e.get("boat", "Unknown"); uid = e.get("uid", "unknown")
        et  = (e.get("event") or "").lower()
        dd  = (e.get("details") or "").lower()

        is_resolution = ("boated" in et) or ("released" in et) or ("pulled hook" in dd) or ("wrong species" in dd)
        if not is_resolution: continue

        try:
            orig_dt = date_parser.parse(e["timestamp"])
            res_dt  = datetime.combine(today, orig_dt.time())
            e["timestamp"] = res_dt.isoformat()

            delta = random.randint(5, 120)
            hook_dt = res_dt - timedelta(minutes=delta)
            if hook_dt.date() < today:
                hook_dt = datetime.combine(today, datetime.min.time()) + timedelta(minutes=1)

            key = f"{uid}_{res_dt.isoformat()}"
            if key in inserted: 
                continue
            demo_events.append({
                "timestamp": hook_dt.isoformat(),
                "event": "Hooked Up",
                "boat": boat,
                "uid": uid,
                "details": "Hooked up!",
                "hookup_id": key
            })
            inserted.add(key)
        except Exception as ex:
            print(f"⚠️ Demo inject failed for {boat}: {ex}")

    all_events = sorted(events + demo_events, key=lambda e: date_parser.parse(e["timestamp"]))
    print(f"📦 Returning {len(all_events)} events (with {len(demo_events)} injections)")
    return all_events

def build_demo_cache(tournament: str) -> int:
    print(f"📦 [DEMO] Building for {tournament} …")
    try:
        events = scrape_events(force=True, tournament=tournament)
        if not events:
            tc = TourCache(tournament)
            if tc.events.exists() and tc.events.stat().st_size > 0:
                events = json.loads(tc.events.read_text())
                print(f"🟡 Using cached live events: {len(events)}")
        injected = inject_hooked_up_events(events, tournament)
        leaderboard = scrape_leaderboard(tournament, force=True) or []

        data = {}
        if os.path.exists(DEMO_DATA_FILE):
            try:
                with open(DEMO_DATA_FILE, "r") as f:
                    data = json.load(f) or {}
            except:
                data = {}
        data[tournament] = {"events": injected, "leaderboard": leaderboard}
        with open(DEMO_DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

        TourCache(tournament).mark_demo_built()
        print(f"✅ [DEMO] Saved {len(injected)} events")
        return len(injected)
    except Exception as e:
        print(f"❌ [DEMO] build failed: {e}")
        return 0

def load_demo_data(tournament: str) -> dict:
    if os.path.exists(DEMO_DATA_FILE):
        try:
            with open(DEMO_DATA_FILE, "r") as f:
                data = json.load(f) or {}
                return data.get(tournament, {"events": [], "leaderboard": []})
        except Exception as e:
            print(f"⚠️ demo_data read error: {e}")
    return {"events": [], "leaderboard": []}

def ensure_demo_ready(tournament: str, force_if_empty: bool = True):
    data = load_demo_data(tournament)
    if force_if_empty and not data.get("events"):
        build_demo_cache(tournament)

# =========================
# Scrapers (events / participants / leaderboard)
# =========================
def scrape_events(force: bool = False, tournament: str | None = None) -> list[dict]:
    t = tournament or get_current_tournament()
    tc = TourCache(t)
    key = f"events_{t}"

    # TTL 2 minutes
    if not force and tc.is_fresh("events", 2):
        if tc.events.exists():
            try:
                return json.loads(tc.events.read_text())
            except:
                return []
        return []

    try:
        remote = requests.get(MASTER_JSON_URL, timeout=20).json()
        keyname = next((k for k in remote if normalize_boat_name(k) == normalize_boat_name(t)), None)
        if not keyname: raise Exception(f"Tournament '{t}' not in master JSON")
        events_url = remote[keyname].get("events")
        if not events_url: raise Exception(f"No events URL for {t}")
        html = fetch_html(events_url)
        if not html:
            tc.events.write_text(json.dumps([], indent=2))
            cache = load_cache(); cache[key] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
            print("⚠️ events: empty HTML; wrote empty file")
            return []

        soup = BeautifulSoup(html, "html.parser")
        events = []
        seen = set()

        # load participants for canonical boat name
        parts = {}
        if tc.participants.exists():
            try:
                parts_list = json.loads(tc.participants.read_text())
                parts = {p["uid"]: p for p in parts_list}
            except: pass

        for article in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
            tm = article.select_one("p.pull-right")
            nm = article.select_one("h4.montserrat")
            ds = article.select_one("p > strong")
            if not (tm and nm and ds): 
                continue
            raw = tm.get_text(strip=True).replace("@","").strip()
            try:
                ts = date_parser.parse(raw).replace(year=datetime.now().year).isoformat()
            except: 
                continue

            boat = nm.get_text(strip=True)
            desc = ds.get_text(strip=True)
            uid  = normalize_boat_name(boat)
            if uid in parts:
                boat = parts[uid]["boat"]

            dl = desc.lower()
            if "released" in dl: et = "Released"
            elif "boated" in dl: et = "Boated"
            elif "pulled hook" in dl: et = "Pulled Hook"
            elif "wrong species" in dl: et = "Wrong Species"
            else: et = "Other"

            dkey = f"{uid}_{et}_{ts}"
            if dkey in seen: 
                continue
            seen.add(dkey)
            events.append({"timestamp": ts, "event": et, "boat": boat, "uid": uid, "details": desc})

        events.sort(key=lambda e: e["timestamp"])
        tc.events.write_text(json.dumps(events, indent=2))
        tc.touch("events")
        cache = load_cache(); cache[key] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
        print(f"✅ events scraped: {len(events)}")
        return events
    except Exception as e:
        print(f"❌ scrape_events: {e}")
        if not tc.events.exists(): tc.events.write_text(json.dumps([], indent=2))
        cache = load_cache(); cache[key] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
        return []

def cache_boat_image(boat_name: str, image_url: str) -> str:
    """Download original file as-is; no optimization. Returns public path or default."""
    try:
        BOAT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        uid = normalize_boat_name(boat_name)
        ext = os.path.splitext(image_url.split("?")[0])[-1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            ext = ".jpg"
        dest = BOAT_IMAGE_DIR / f"{uid}{ext}"
        if dest.exists() and dest.stat().st_size > 0:
            return f"/{dest.as_posix()}"
        r = requests.get(image_url, timeout=15)
        if r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
            print(f"📸 saved {dest.name}")
            return f"/{dest.as_posix()}"
        print(f"⚠️ image fetch {image_url} -> {r.status_code}")
    except Exception as e:
        print(f"⚠️ image cache error for {boat_name}: {e}")
    return "/static/images/boats/default.jpg"

def scrape_participants(force: bool = False) -> list[dict]:
    t = get_current_tournament()
    tc = TourCache(t)
    key = f"{t}_participants"

    # TTL 1 day
    if not force and tc.is_fresh("participants", 1440):
        if tc.participants.exists():
            try: return json.loads(tc.participants.read_text())
            except: return []
        return []

    try:
        remote = requests.get(MASTER_JSON_URL, timeout=30).json()
        keyname = next((k for k in remote if k.lower() == t.lower()), None)
        if not keyname: raise Exception(f"Tournament '{t}' not found")
        url = remote[keyname].get("participants")
        if not url: raise Exception(f"No participants URL for {t}")

        html = fetch_html(url)
        if not html:
            tc.participants.write_text(json.dumps([], indent=2))
            print("⚠️ participants: empty HTML; wrote empty file")
            return []

        soup = BeautifulSoup(html, "html.parser")
        participants = {}
        seen = set()
        downloads = []

        for article in soup.select("article.post.format-image"):
            name_tag = article.select_one("h2.post-title")
            type_tag = article.select_one("ul.post-meta li")
            img_tag  = article.select_one("img")
            if not name_tag: continue

            boat_name = name_tag.get_text(strip=True)
            if "," in boat_name:  # skip angler rows etc
                continue
            if boat_name.lower() in seen:
                continue
            seen.add(boat_name.lower())

            boat_type = type_tag.get_text(strip=True) if type_tag else ""
            uid = normalize_boat_name(boat_name)
            image_url = img_tag['src'] if img_tag and img_tag.has_attr("src") else None

            participants[uid] = {
                "uid": uid,
                "boat": boat_name,
                "type": boat_type,
                "image_path": ""
            }
            if image_url:
                downloads.append((uid, boat_name, image_url))

        # write immediately so UI can render, even if images pending
        plist = list(participants.values())
        tc.participants.write_text(json.dumps(plist, indent=2))
        tc.touch("participants")
        cache = load_cache(); cache[key] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
        print(f"💾 participants written ({len(plist)}) — downloading {len(downloads)} images in background")

        # background image downloads update json incrementally
        def _download(uid, name, url):
            try:
                path = cache_boat_image(name, url)
                participants[uid]["image_path"] = path
                tc.participants.write_text(json.dumps(list(participants.values()), indent=2))
            except Exception as e:
                print(f"❌ img {uid}: {e}")

        if downloads:
            with ThreadPoolExecutor(max_workers=6) as ex:
                for uid, bname, url in downloads:
                    ex.submit(_download, uid, bname, url)

        return plist
    except Exception as e:
        print(f"❌ scrape_participants: {e}")
        if not tc.participants.exists(): tc.participants.write_text(json.dumps([], indent=2))
        return []

def split_boat_and_type(boat_name: str, trailing_text: str) -> tuple[str, str]:
    trailing_text = trailing_text.strip()
    if trailing_text and re.match(r"^\d{2,2}'", trailing_text):
        return boat_name, trailing_text
    return f"{boat_name} {trailing_text}".strip(), ""

def scrape_leaderboard(tournament: str | None = None, force: bool = False) -> list[dict]:
    t = tournament or get_current_tournament()
    tc = TourCache(t)
    key = f"{t}_leaderboard"

    # TTL 30 minutes
    if not force and tc.is_fresh("leaderboard", 30):
        if tc.leaderboard.exists():
            try: return json.loads(tc.leaderboard.read_text())
            except: return []
        return []

    try:
        remote = requests.get(MASTER_JSON_URL, timeout=30).json()
        keyname = next((k for k in remote if k.lower() == t.lower()), None)
        if not keyname:
            tc.leaderboard.write_text(json.dumps([], indent=2))
            return []
        url = remote[keyname].get("leaderboard")
        if not url:
            tc.leaderboard.write_text(json.dumps([], indent=2))
            return []

        html = fetch_html(url)
        if not html:
            tc.leaderboard.write_text(json.dumps([], indent=2))
            print("⚠️ leaderboard: empty HTML; wrote empty file")
            return []

        soup = BeautifulSoup(html, "html.parser")
        leaderboard = []

        categories = [a.get_text(strip=True) for a in soup.select("ul.dropdown-menu li a.leaderboard-nav")]
        for category in categories:
            tab_link = soup.find("a", string=lambda x: x and x.strip() == category)
            if not tab_link: continue
            tab_id = tab_link.get("href")
            tab = soup.select_one(tab_id)
            if not tab: continue

            for row in tab.select("tr.montserrat"):
                cols = row.find_all("td")
                if len(cols) < 2: 
                    continue
                rank = cols[0].get_text(strip=True)
                boat_block = cols[1]
                points = cols[-1].get_text(strip=True)

                h4 = boat_block.find("h4")
                name = h4.get_text(strip=True) if h4 else ""
                text_after = boat_block.get_text(" ", strip=True).replace(name, "").strip()

                angler, boat, btype = None, name, text_after
                if "lb" in points.lower() and "'" not in text_after:
                    angler, boat, btype = name, None, None
                else:
                    boat, btype = split_boat_and_type(name, text_after)

                uid = normalize_boat_name(boat or angler or f"rank_{rank}")
                image_path = ""
                if boat:
                    # resolve existing local file if present
                    for ext in (".webp", ".jpg", ".jpeg", ".png"):
                        cand = (BOAT_IMAGE_DIR / f"{uid}{ext}")
                        if cand.exists() and cand.stat().st_size > 0:
                            image_path = "/" + cand.as_posix()
                            break

                leaderboard.append({
                    "rank": rank,
                    "category": category,
                    "angler": angler,
                    "boat": boat,
                    "type": btype,
                    "points": points,
                    "uid": uid,
                    "image_path": image_path or "/static/images/boats/default.jpg"
                })

        tc.leaderboard.write_text(json.dumps(leaderboard, indent=2))
        tc.touch("leaderboard")
        cache = load_cache(); cache[key] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
        print(f"✅ leaderboard scraped: {len(leaderboard)}")
        return leaderboard
    except Exception as e:
        print(f"❌ scrape_leaderboard: {e}")
        if not tc.leaderboard.exists(): tc.leaderboard.write_text(json.dumps([], indent=2))
        return []

# =========================
# Orchestration (order & background)
# =========================
def orchestrate_refresh(force: bool = False, mode: str | None = None, tournament: str | None = None):
    """Order: events → (participants & leaderboard in parallel)"""
    t = tournament or get_current_tournament()
    tc = TourCache(t)
    _mode = (mode or get_data_source()).lower()

    ensure_initialized(_mode, t)

    EVENTS_TTL = 2; PARTS_TTL = 1440; LBRD_TTL = 30

    # 1) events
    if force or not tc.is_fresh("events", EVENTS_TTL):
        events = scrape_events(force=True, tournament=t)
        tc.events.write_text(json.dumps(events or [], indent=2))
        tc.touch("events")
        cache = load_cache(); cache[f"events_{t}"] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
    else:
        print("⏭️ events fresh")

    # 2) participants + leaderboard
    tasks = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        if force or not tc.is_fresh("participants", PARTS_TTL):
            tasks.append(("participants", ex.submit(lambda: scrape_participants(force=True))))
        if force or not tc.is_fresh("leaderboard", LBRD_TTL):
            tasks.append(("leaderboard", ex.submit(lambda: scrape_leaderboard(t, force=True))))

        for name, fut in tasks:
            try:
                data = fut.result()
                if name == "participants":
                    tc.participants.write_text(json.dumps(data or [], indent=2))
                    tc.touch("participants")
                    cache = load_cache(); cache[f"{t}_participants"] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
                else:
                    tc.leaderboard.write_text(json.dumps(data or [], indent=2))
                    tc.touch("leaderboard")
                    cache = load_cache(); cache[f"{t}_leaderboard"] = {"last_scraped": datetime.now().isoformat()}; save_cache(cache)
            except Exception as e:
                print(f"❌ refresh {name}: {e}")

    if _mode == "demo":
        ensure_demo_ready(t, force_if_empty=False)

# =========================
# Background Email Watcher
# =========================
def process_new_event(event: dict):
    global emailed_events
    uid = f"{event.get('timestamp')}_{event.get('uid')}_{event.get('event')}"
    if uid in emailed_events:
        return
    emailed_events.add(uid)
    save_emailed_events()
    if should_email(event):
        try:
            send_boat_email_alert(event)
        except Exception as e:
            print(f"❌ email failed for {event.get('boat')}: {e}")

def background_event_emailer():
    global emailed_events
    emailed_events = load_emailed_events()
    print(f"📡 Email watcher loaded {len(emailed_events)} ids")

    while True:
        try:
            t = get_current_tournament()
            mode = get_data_source()
            tc = TourCache(t)

            if mode == "demo":
                data = load_demo_data(t).get("events", [])
                now = datetime.now().time()
                events = [e for e in data if date_parser.parse(e["timestamp"]).time() <= now]
            else:
                if not tc.events.exists():
                    time.sleep(5); continue
                events = json.loads(tc.events.read_text() or "[]")

            events.sort(key=lambda e: e.get("timestamp",""), reverse=True)
            for e in events[:50]:
                process_new_event(e)
        except Exception as e:
            print(f"⚠️ email watcher loop error: {e}")
        time.sleep(30)

# =========================
# Routes
# =========================
@app.route("/")
def homepage():
    return send_from_directory("templates", "index.html")

@app.route("/participants")
def participants_page():
    return send_from_directory("static", "participants.html")

@app.route("/leaderboard")
def leaderboard_page():
    return send_from_directory("static", "leaderboard.html")

@app.route("/release-summary")
def release_summary_page():
    return send_from_directory("static", "release-summary.html")

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory("static", filename)

# ---- Scrape endpoints (serve cache immediately, refresh if stale in background)
@app.route("/scrape/events")
def scrape_events_route():
    settings = load_settings()
    tournament = get_current_tournament()
    mode = settings.get("data_source", "live").lower()
    tc = TourCache(tournament)
    ensure_initialized(mode, tournament)

    if mode == "demo":
        data = load_demo_data(tournament)
        if not data.get("events"):
            non_blocking(lambda: ensure_demo_ready(tournament, True), "build_demo")
            data = load_demo_data(tournament)

        now_time = datetime.now().time()
        events = []
        for e in data.get("events", []):
            try:
                if date_parser.parse(e["timestamp"]).time() <= now_time:
                    events.append(e)
            except: pass
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        if not events:
            non_blocking(lambda: ensure_demo_ready(tournament, True), "rebuild_demo")
        return jsonify({"status": "ok", "count": len(events), "events": events[:100]})

    # live/historical
    try:
        cached = []
        if tc.events.exists():
            try: cached = json.loads(tc.events.read_text() or "[]")
            except: cached = []
        if not tc.is_fresh("events", 2):
            non_blocking(lambda: orchestrate_refresh(False, mode, tournament), "refresh_events")
        cached.sort(key=lambda e: e.get("timestamp",""), reverse=True)
        return jsonify({"status":"ok","count":len(cached),"events":cached[:100]})
    except Exception as e:
        print(f"❌ /scrape/events: {e}")
        return jsonify({"status":"error","message":str(e)})

@app.route("/participants_data")
def participants_data():
    tournament = get_current_tournament()
    tc = TourCache(tournament)
    ensure_initialized(get_data_source(), tournament)

    try:
        participants = []
        if tc.participants.exists():
            participants = json.loads(tc.participants.read_text() or "[]")
    except:
        participants = []

    if not tc.is_fresh("participants", 1440):
        non_blocking(lambda: orchestrate_refresh(False, tournament=tournament), "refresh_participants")

    # no webp preference (we keep original), but ensure default
    for p in participants:
        if not p.get("image_path"):
            p["image_path"] = "/static/images/boats/default.jpg"

    participants.sort(key=lambda p: p.get("boat","").lower())
    return jsonify({"status":"ok","participants":participants,"count":len(participants)})

@app.route("/api/leaderboard")
def api_leaderboard():
    tournament = get_current_tournament()
    tc = TourCache(tournament)
    ensure_initialized(get_data_source(), tournament)

    try:
        leaderboard = []
        if tc.leaderboard.exists():
            leaderboard = json.loads(tc.leaderboard.read_text() or "[]")
    except:
        leaderboard = []

    if (not leaderboard) or (not tc.is_fresh("leaderboard", 30)):
        non_blocking(lambda: orchestrate_refresh(False, tournament=tournament), "refresh_leaderboard")

    # enforce uid and default image
    for row in leaderboard or []:
        uid = row.get("uid") or normalize_boat_name(row.get("boat", ""))
        row["uid"] = uid
        if not row.get("image_path"):
            row["image_path"] = "/static/images/boats/default.jpg"

    return jsonify({"status":"ok" if leaderboard else "error","leaderboard":leaderboard})

@app.route("/scrape/leaderboard")
def scrape_leaderboard_route():
    force = request.args.get("force") == "1"
    t = get_current_tournament()
    data = scrape_leaderboard(t, force=force)
    return jsonify({"status":"ok" if data else "error","leaderboard":data})

@app.route("/scrape/all")
def scrape_all():
    t = get_current_tournament()
    ensure_initialized(get_data_source(), t)
    # run full warm in background; respond immediately
    non_blocking(lambda: orchestrate_refresh(True, tournament=t), "force_refresh_all")
    # return current counts from cache
    tc = TourCache(t)
    try:
        e = json.loads(tc.events.read_text() or "[]")
        p = json.loads(tc.participants.read_text() or "[]")
        l = json.loads(tc.leaderboard.read_text() or "[]")
    except: e,p,l = [],[],[]
    return jsonify({"status":"ok","message":"Refreshing in background",
                    "tournament":t,"events":len(e),"participants":len(p),"leaderboard":len(l)})

# ---- Hooked feed (demo vs live)
@app.route("/hooked")
def get_hooked_up_events():
    settings = load_settings()
    t = get_current_tournament()
    mode = settings.get("data_source", "live").lower()
    now_time = datetime.now().time()
    tc = TourCache(t)

    if mode == "demo":
        data = load_demo_data(t).get("events", [])
        events = [e for e in data if date_parser.parse(e["timestamp"]).time() <= now_time]
    else:
        if tc.events.exists():
            try: events = json.loads(tc.events.read_text() or "[]")
            except: events = []
        else:
            events = []

    events.sort(key=lambda e: date_parser.parse(e["timestamp"]))
    hooked_feed = []

    if mode == "demo":
        resolved = set()
        for e in events:
            if e["event"] in ["Released","Boated"] or \
               "pulled hook" in e.get("details","").lower() or \
               "wrong species" in e.get("details","").lower():
                key = f"{e['uid']}_{date_parser.parse(e['timestamp']).replace(microsecond=0).isoformat()}"
                resolved.add(key)
        for e in events:
            if e.get("event") == "Hooked Up":
                key = e.get("hookup_id")
                if not key or key not in resolved:
                    hooked_feed.append(e)
    else:
        active = {}
        for e in events:
            uid = e.get("uid")
            et  = (e.get("event") or "").lower()
            if et == "hooked up":
                active.setdefault(uid, []).append(e)
            elif et in ["boated","released"] or \
                 "pulled hook" in e.get("details","").lower() or \
                 "wrong species" in e.get("details","").lower():
                if uid in active and active[uid]:
                    active[uid].pop(0)
        for lst in active.values(): hooked_feed.extend(lst)

    hooked_feed.sort(key=lambda e: date_parser.parse(e["timestamp"]), reverse=True)
    return jsonify({"status":"ok","count":len(hooked_feed),"events":hooked_feed[:50]})

# ---- Release summary (by day/species, respects demo time-of-day)
@app.route("/release-summary-data")
def release_summary_data():
    try:
        t = get_current_tournament()
        mode = get_data_source()
        tc = TourCache(t)

        if mode == "demo":
            data = load_demo_data(t).get("events", [])
            now = datetime.now().time()
            events = [e for e in data if date_parser.parse(e["timestamp"]).time() <= now]
        else:
            if not tc.events.exists():
                return jsonify({"status":"ok","summary":[]})
            events = json.loads(tc.events.read_text() or "[]")

        summary = defaultdict(lambda: {
            "blue_marlins":0, "white_marlins":0, "sailfish":0, "total_releases":0
        })

        for e in events:
            if (e.get("event") or "").lower() != "released": continue
            try:
                day = date_parser.parse(e["timestamp"]).strftime("%Y-%m-%d")
            except:
                continue
            det = (e.get("details") or "").lower()
            if "blue marlin" in det:  summary[day]["blue_marlins"]  += 1
            elif "white marlin" in det: summary[day]["white_marlins"] += 1
            elif "sailfish" in det:     summary[day]["sailfish"]     += 1
            summary[day]["total_releases"] += 1

        result = [{"date":k, **v} for k,v in sorted(summary.items(), key=lambda x: x[0], reverse=True)]
        return jsonify({"status":"ok","demo_mode": mode=="demo","summary":result})
    except Exception as e:
        print(f"❌ release-summary: {e}")
        return jsonify({"status":"error","message":str(e)})

# ---- Alerts API
@app.route("/alerts/list", methods=["GET"])
def list_alerts():
    return jsonify(load_alerts())

@app.route("/alerts/subscribe", methods=["POST"])
def subscribe_alerts():
    data = request.get_json() or {}
    new_emails = data.get("sms_emails", [])
    alerts = load_alerts()
    for email in new_emails:
        if email not in alerts:
            alerts.append(email)
    save_alerts(alerts)
    return jsonify({"status":"subscribed","count":len(alerts)})

@app.route("/alerts/test", methods=["GET"])
def test_alerts():
    recips = load_alerts()
    if not recips:
        return jsonify({"status":"no_subscribers"}), 404
    event = {"boat":"Palmer Lou","event":"Hooked Up","timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "uid":"palmer_lou","details":"Test message"}
    n = send_boat_email_alert(event)
    return jsonify({"status":"sent","success_count": n})

# ---- Settings (persist + warm cache on change; build demo on switch)
@app.route("/api/settings", methods=["GET","POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json() or {}
        old = load_settings()
        old_t = old.get("tournament")
        new_t = data.get("tournament") or old_t
        new_m = (data.get("data_source") or data.get("mode") or old.get("data_source") or "live").lower()
        data["data_source"] = new_m
        data["mode"] = new_m
        data.setdefault("followed_sound", old.get("followed_sound","Fishing Reel"))
        data.setdefault("boated_sound",   old.get("boated_sound","Fishing Reel"))
        data.setdefault("followed_boats", old.get("followed_boats", []))
        data["sms_emails"] = data.get("sms_emails", old.get("sms_emails", []))
        save_alerts(data["sms_emails"])
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)

        if new_t != old_t:
            print(f"🔄 Tournament changed: {old_t} → {new_t}")
            ensure_initialized(new_m, new_t)
            non_blocking(lambda: orchestrate_refresh(False, new_m, new_t), "warm_after_change")

        if new_m == "demo":
            non_blocking(lambda: ensure_demo_ready(new_t or old_t or get_current_tournament(), True), "build_demo_on_switch")

        return jsonify({"status":"success"})

    s = load_settings()
    s.setdefault("followed_sound","Fishing Reel")
    s.setdefault("boated_sound","Fishing Reel")
    s["sms_emails"] = load_alerts()
    return jsonify(s)

# ---- Generate demo data on demand
@app.route("/generate_demo")
def generate_demo():
    try:
        t = get_current_tournament()
        count = build_demo_cache(t)
        return jsonify({"status":"ok","events":count})
    except Exception as e:
        print(f"❌ generate_demo: {e}")
        return jsonify({"status":"error","message":str(e)})

# ---- Followed boats
@app.route("/followed-boats", methods=["GET"])
def get_followed_boats_api():
    return jsonify(load_settings().get("followed_boats", []))

@app.route("/followed-boats/toggle", methods=["POST"])
def toggle_followed_boat():
    data = request.get_json() or {}
    boat = data.get("boat")
    if not boat:
        return jsonify({"status":"error","message":"Missing 'boat'"}), 400
    s = load_settings()
    followed = s.get("followed_boats", [])
    uid = normalize_boat_name(boat)
    followed_norm = [normalize_boat_name(b) for b in followed]
    if uid in followed_norm:
        followed = [b for b in followed if normalize_boat_name(b) != uid]
        action = "unfollowed"
    else:
        followed.append(boat); action = "followed"
    s["followed_boats"] = followed
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)
    return jsonify({"status":"ok","action":action,"followed_boats":followed})

# ---- Sounds, Version
@app.route("/sounds")
def list_sounds():
    try:
        files = [f for f in os.listdir("static/sounds") if f.lower().endswith(".mp3")]
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"files": [], "error": str(e)}), 500

@app.route("/api/version")
def api_version():
    try:
        with open("version.txt") as f:
            return jsonify({"version": f.read().strip()})
    except:
        return jsonify({"version": "Unknown"})

# ---- Wi-Fi / Bluetooth stubs
@app.route("/bluetooth/status")
def bluetooth_status():
    return jsonify({"enabled": True})

@app.route("/bluetooth/scan")
def bluetooth_scan():
    return jsonify({"devices":[{"name":"Test Device","mac":"00:11:22:33:44:55","connected":False}]})

@app.route("/bluetooth/connect", methods=["POST"])
def bluetooth_connect():
    data = request.get_json() or {}
    print(f"Connecting to: {data.get('mac')}")
    return jsonify({"status":"ok"})

@app.route("/wifi/scan")
def wifi_scan():
    try:
        out = subprocess.check_output(['nmcli','-t','-f','SSID,SIGNAL,IN-USE','dev','wifi'], text=True)
        seen, connected = {}, None
        for line in out.strip().split("\n"):
            parts = line.strip().split(":")
            if len(parts) >= 3:
                ssid, signal, in_use = parts
                if not ssid.strip(): continue
                try: signal = int(signal)
                except: continue
                is_conn = in_use.strip() == '*'
                if ssid not in seen or is_conn or signal > seen[ssid]['signal']:
                    seen[ssid] = {'ssid': ssid, 'signal': signal, 'connected': is_conn}
                if is_conn: connected = ssid
        return jsonify({'networks': list(seen.values()), 'connected': connected})
    except Exception as e:
        print(f"❌ Wi-Fi scan error: {e}")
        return jsonify({'networks': [], 'connected': None})

@app.route("/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.get_json() or {}
    ssid = data.get("ssid"); password = data.get("password","")
    if not ssid: return jsonify({'status':'error','message':'Missing SSID'}), 400
    try:
        cmd = ['sudo','nmcli','dev','wifi','connect',ssid]
        if password: cmd += ['password', password]
        res = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return jsonify({'status':'ok','message':res})
    except subprocess.CalledProcessError as e:
        if "Secrets were required" in e.output:
            return jsonify({'status':'error','message':'Password required for new network','code':'password_required'}), 400
        return jsonify({'status':'error','message':e.output.strip()}), 500

@app.route("/wifi/disconnect", methods=["POST"])
def wifi_disconnect():
    try:
        result = subprocess.check_output(['nmcli','-t','-f','NAME,TYPE,DEVICE','con','show','--active'], text=True)
        for line in result.strip().split('\n'):
            parts = line.strip().split(':')
            if len(parts) < 3: continue
            name, ctype, device = parts
            if ctype == 'wifi':
                subprocess.check_call(['nmcli','con','down',name])
                return jsonify({'status':'ok','message':f'Disconnected from {name}'})
        subprocess.check_call(['nmcli','device','disconnect','wlan0'])
        return jsonify({'status':'ok','message':'Disconnected wlan0'})
    except subprocess.CalledProcessError as e:
        return jsonify({'status':'error','message':str(e)}), 500
    except Exception as e:
        return jsonify({'status':'error','message':str(e)}), 500

# ---- Keyboard (Onboard)
@app.route("/launch_keyboard", methods=["POST"])
def launch_keyboard():
    try:
        env = os.environ.copy(); env['DISPLAY']=':0'; env['XAUTHORITY']='/home/pi/.Xauthority'
        subprocess.Popen(['onboard'], env=env)
        return jsonify({"status":"launched"})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/hide_keyboard", methods=["POST"])
def hide_keyboard():
    try:
        subprocess.call(['pkill','-f','onboard'])
        return jsonify({"status":"hidden"})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ---- Status for frontend
@app.route("/status")
def get_status():
    try:
        cache = load_cache()
        t = get_current_tournament()
        data_source = get_data_source()
        tc = TourCache(t)

        status = {
            "mode": data_source,
            "tournament": t,
            "participants_last_scraped": None,
            "events_last_scraped": None,
            "participants_cache_fresh": tc.is_fresh("participants", 1440),
            "events_cache_fresh": tc.is_fresh("events", 2),
        }
        part_key = f"{t}_participants"
        event_key = f"events_{t}"
        if part_key in cache:
            status["participants_last_scraped"] = cache[part_key].get("last_scraped")
        if event_key in cache:
            status["events_last_scraped"] = cache[event_key].get("last_scraped")
        return jsonify(status)
    except Exception as e:
        print(f"❌ /status: {e}")
        return jsonify({"status":"error","message":str(e)}), 500

# =========================
# Main
# =========================
if __name__ == "__main__":
    # Start email watcher
    Thread(target=background_event_emailer, daemon=True).start()

    # Warm caches non-blocking on boot
    try:
        mode = get_data_source()
        t = get_current_tournament()
        ensure_initialized(mode, t)
        non_blocking(lambda: orchestrate_refresh(False, mode, t), "startup_warm")
    except Exception as e:
        print(f"⚠️ startup warm skipped: {e}")

    app.run(host="0.0.0.0", port=5000, debug=True)
