import os
import time
import threading
import hashlib
import urllib.parse
import requests
from urllib.parse import urlparse
from flask import Flask, request, redirect, jsonify, Response

# Vercel serverless Flask app
app = Flask(__name__)

# Config via env vars (set in Vercel dashboard)
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "http://tatatv.cc/stalker_portal/c/")
PORTAL_MAC = os.getenv("PORTAL_MAC", "00:1A:79:00:13:DA")
PORTAL_TYPE = os.getenv("PORTAL_TYPE", "1")  # "1" = stalker_portal
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # seconds

# Simple thread-safe cache
_cache = {
    "session": None,
    "headers": None,
    "channels": None,
    "portal_name": None,
    "expires": 0
}
_lock = threading.Lock()

# ===== Helpers (based on your original code but without file I/O) =====

def normalize_url_and_name(input_url):
    url = (input_url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    url = urllib.parse.urljoin(url, "/")
    url = url.rstrip("/")
    # strip /stalker_portal/c or /c suffix
    parsed = urlparse(url)
    netloc = parsed.netloc
    name_part = "".join(netloc.split('.')[-2:]) if '.' in netloc else netloc.replace('.', '')
    return url, name_part.lower()


def generate_device_info(mac):
    mac_upper = mac.upper()
    SN = hashlib.md5(mac.encode('utf-8')).hexdigest().upper()
    SNCUT = SN[:13]
    DEV1 = hashlib.sha256(mac.encode('utf-8')).hexdigest().upper()
    DEV2 = hashlib.sha256(SNCUT.encode('utf-8')).hexdigest().upper()
    SIGNATURE = hashlib.sha256((SNCUT + mac).encode('utf-8')).hexdigest().upper()
    return {"SN": SN, "SNCUT": SNCUT, "Device_ID1": DEV1, "Device_ID2": DEV2, "Signature": SIGNATURE, "MAC_Encoded": urllib.parse.quote(mac.upper())}


def create_link(base_url, cmd, session, headers, portal_type, retries=3):
    cmd = cmd.strip().replace("ffrt ", "")
    prefix = "stalker_portal" if portal_type == "1" else "c"
    url = f"{base_url}/{prefix}/server/load.php?type=itv&action=create_link&cmd={urllib.parse.quote(cmd)}&JsHttpRequest=1-xml"
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                continue
            js = resp.json().get("js", {})
            if isinstance(js, dict) and js.get("cmd"):
                return js.get("cmd").replace("ffrt ", "").strip()
        except Exception:
            time.sleep(0.5)
            continue
    return None


def init_portal_session_and_channels(base_url, mac, portal_type):
    session = requests.Session()
    prefix = "stalker_portal" if portal_type == "1" else "c"

    handshake_url = f"{base_url}/{prefix}/server/load.php?action=handshake&type=stb&token=&JsHttpRequest=1-xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
        "X-User-Agent": "Model: MAG250; Link: WiFi",
        "Referer": f"{base_url}/{prefix}/c/",
        "Accept": "*/*",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }
    session.cookies.set("mac", mac)

    # handshake
    resp = session.post(handshake_url, headers=headers, timeout=10)
    js = resp.json().get("js", {}) if resp and resp.status_code == 200 else {}
    token = js.get("token")
    if not token:
        raise RuntimeError("Handshake failed or token missing")
    headers["Authorization"] = f"Bearer {token}"

    # validate profile
    device_info = generate_device_info(mac)
    sn = device_info["SNCUT"]
    device_id = device_info["Device_ID1"]
    signature = device_info["Signature"]
    profile_url = f"{base_url}/{prefix}/server/load.php?type=stb&action=get_profile&sn={sn}&device_id={device_id}&device_id2={device_id}&signature={signature}&JsHttpRequest=1-xml"
    resp = session.get(profile_url, headers=headers, timeout=10)
    if not resp or "js" not in resp.text:
        raise RuntimeError("Profile validation failed")

    # fetch channels
    all_url = f"{base_url}/{prefix}/server/load.php?type=itv&action=get_all_channels&JsHttpRequest=1-xml"
    resp = session.get(all_url, headers=headers, timeout=15)
    data = resp.json() if resp and resp.status_code == 200 else {}
    channels = data.get("js", {}).get("data", []) if isinstance(data, dict) else []

    return session, headers, channels


def ensure_cache():
    with _lock:
        if _cache["channels"] and time.time() < _cache["expires"]:
            return
        base, pname = normalize_url_and_name(PORTAL_BASE_URL)
        session, headers, channels = init_portal_session_and_channels(base, PORTAL_MAC, PORTAL_TYPE)
        _cache.update({
            "session": session,
            "headers": headers,
            "channels": channels,
            "portal_name": pname,
            "expires": time.time() + CACHE_TTL
        })


# ===== Routes =====

@app.route("/")
def index():
    try:
        ensure_cache()
    except Exception as e:
        return jsonify({"error": "init_failed", "details": str(e)}), 500
    return jsonify({"message": "IPTV playlist serverless endpoint", "playlist": f"{request.host_url}playlist.m3u"})


@app.route("/playlist.m3u")
def playlist():
    try:
        ensure_cache()
    except Exception as e:
        return ("#ERROR\n" + str(e), 500, {"Content-Type": "text/plain"})

    base_url, pname = normalize_url_and_name(PORTAL_BASE_URL)
    host = request.host_url.rstrip("/")

    def generate():
        yield "#EXTM3U\n"
        for ch in _cache.get("channels", []):
            name = ch.get("name", "Unknown")
            ch_id = ch.get("id")
            logo = ch.get("logo", "")
            logo_url = f"{base_url}/stalker_portal/misc/logos/320/{logo}" if PORTAL_TYPE == "1" else logo
            # point to our getlink endpoint to avoid fetching all create_link upfront
            yield f'#EXTINF:-1 group-title="All Channels" tvg-logo="{logo_url}",{name}\n{host}/getlink/{ch_id}\n'

    return Response(generate(), mimetype="application/x-mpegurl")


@app.route("/getlink/<int:ch_id>")
def getlink(ch_id):
    try:
        ensure_cache()
    except Exception as e:
        return jsonify({"error": "init_failed", "details": str(e)}), 500

    ch = next((c for c in _cache.get("channels", []) if str(c.get("id")) == str(ch_id)), None)
    if not ch:
        return jsonify({"error": "not_found"}), 404
    cmd = ch.get("cmd", "").strip()
    if not cmd:
        return jsonify({"error": "no_cmd"}), 400
    if "ffmpeg" in cmd:
        # return the URL directly if the command is local ffmpeg
        real_url = cmd.replace("ffmpeg ", "").strip()
    else:
        real_url = create_link(PORTAL_BASE_URL.rstrip('/'), cmd, _cache["session"], _cache["headers"], PORTAL_TYPE)
    if not real_url:
        return jsonify({"error": "failed_to_create_link"}), 502
    return redirect(real_url, code=302)


# DO NOT call app.run() — Vercel will handle invocation
