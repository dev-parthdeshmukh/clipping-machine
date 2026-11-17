"""Which GTA streams to clip right now. Three places to look, all free:
YouTube search (today's long GTA streams, most viewed first), the user's watchlist
(gta6-clips/streamers.txt), and Twitch's live GTA directory when the user added their own
Twitch app key to gta6-clips/.env."""

import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config
from .fetch import base_args
from .util import log, run

TODAY_LONGEST_VIEWED = "CAMSBAgCGAI%253D"     # YouTube search filter: today, > 20 min, by views


def _listing(url, n, args=()):
    try:
        data = json.loads(run(["yt-dlp", "--flat-playlist", "--playlist-end", str(n), "-J", *args, url], timeout=120))
    except (RuntimeError, ValueError) as exc:
        log(f"couldn't read {url[:60]} ({str(exc).splitlines()[0][:80]})", "warn")
        return []
    return data.get("entries") or []


def _entry(url, platform, name, title, views, duration, live, source):
    return {"url": url, "platform": platform, "name": name, "title": title, "views": views or 0,
            "duration": duration or 0, "live": live, "source": source}


def youtube_today(query, limit=15):
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp={TODAY_LONGEST_VIEWED}"
    return [_entry(f"https://www.youtube.com/watch?v={e['id']}", "youtube", e.get("channel") or "?",
                   e.get("title") or "", e.get("view_count"), e.get("duration"),
                   e.get("live_status") == "is_live", "youtube search")
            for e in _listing(url, limit, base_args("youtube"))
            if e.get("id") and e.get("_type") in (None, "url")]


def parse_watchlist(text):
    """Lines like `twitch:xqc  # comment` -> [("twitch", "xqc")]."""
    pairs = []
    for line in text.splitlines():
        body = line.split("#", 1)[0].strip()
        site, colon, who = body.partition(":")
        if colon and site in ("twitch", "youtube", "kick") and who.strip():
            pairs.append((site, who.strip()))
    return pairs


def watchlist_file():
    path = config.HOME / "streamers.txt"
    if not path.exists():
        config.HOME.mkdir(parents=True, exist_ok=True)
        starter = config.ROOT / "streamers.txt"
        path.write_text(starter.read_text(encoding="utf-8") if starter.exists() else "", encoding="utf-8")
    return path


def _newest_gta_vod(site, who, cfg):
    if site == "kick":
        return None                                       # Kick needs cookies: links by hand
    page = (f"https://www.twitch.tv/{who}/videos?filter=archives&sort=time" if site == "twitch"
            else f"https://www.youtube.com/@{who.lstrip('@')}/streams")
    args = base_args(page)
    keywords = [w.lower() for w in cfg["title_words"]]
    for e in _listing(page, 3, args):
        title = e.get("title") or ""
        if keywords and not any(k in title.lower() for k in keywords):
            continue
        url = e.get("url") or e.get("webpage_url") or ""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={e.get('id')}"
        try:
            meta = json.loads(run(["yt-dlp", "-J", "--no-playlist", *args, url], timeout=120))
        except (RuntimeError, ValueError):
            continue
        when = meta.get("timestamp") or meta.get("release_timestamp") or 0
        if when and time.time() - when > cfg["max_age_hours"] * 3600:
            return None
        return _entry(url, site, meta.get("channel") or meta.get("uploader") or who, title,
                      meta.get("view_count"), meta.get("duration"), meta.get("live_status") == "is_live",
                      "watchlist")
    return None


def watchlist(cfg):
    people = parse_watchlist(watchlist_file().read_text(encoding="utf-8"))
    if not people:
        return []
    log(f"checking {len(people)} streamer(s) from your watchlist...", "step")
    with ThreadPoolExecutor(max_workers=6) as pool:
        return [s for s in pool.map(lambda p: _newest_gta_vod(p[0], p[1], cfg), people) if s]


def _keys():
    keys = dict(os.environ)
    env = config.HOME / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, eq, v = line.partition("=")
            if eq and k.strip():
                keys.setdefault(k.strip(), v.strip().strip('"'))
    return keys


def twitch_top(cfg, limit=10):
    """Most-watched live GTA streams on Twitch, via the user's own (free) Twitch app key."""
    keys = _keys()
    cid, secret = keys.get("TWITCH_CLIENT_ID"), keys.get("TWITCH_CLIENT_SECRET")
    if not (cid and secret):
        return []

    def api(url, method="GET", headers=None):
        with urllib.request.urlopen(urllib.request.Request(url, method=method, headers=headers or {}), timeout=20) as r:
            return json.loads(r.read().decode())

    try:
        token = api("https://id.twitch.tv/oauth2/token?" + urllib.parse.urlencode(
            {"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"}), "POST")["access_token"]
        auth = {"Client-Id": cid, "Authorization": f"Bearer {token}"}
        game = api("https://api.twitch.tv/helix/games?" + urllib.parse.urlencode({"name": cfg["game"]}), headers=auth)["data"]
        if not game:
            log(f"Twitch has no category called '{cfg['game']}'", "warn")
            return []
        found = []
        for s in api("https://api.twitch.tv/helix/streams?" + urllib.parse.urlencode(
                {"game_id": game[0]["id"], "first": limit}), headers=auth)["data"]:
            vod = api("https://api.twitch.tv/helix/videos?" + urllib.parse.urlencode(
                {"user_id": s["user_id"], "type": "archive", "first": 1}), headers=auth)["data"]
            if vod:
                found.append(_entry(vod[0]["url"], "twitch", s["user_name"], s["title"], s["viewer_count"],
                                    0, True, "twitch top live"))
        return found
    except Exception as exc:
        log(f"Twitch directory skipped ({exc})", "warn")
        return []


def find(cfg, limit=5):
    """One stream per streamer, GTA in the title, YouTube live streams left out (nothing to
    download until they end), biggest first."""
    words = [w.lower() for w in cfg["title_words"]]
    best = {}
    for s in twitch_top(cfg) + watchlist(cfg) + youtube_today(cfg["search"] + " stream"):
        if not any(w in s["title"].lower() for w in words) or (s["live"] and s["platform"] == "youtube"):
            continue
        key = s["name"].lower()
        if key not in best or s["views"] > best[key]["views"]:
            best[key] = s
    return sorted(best.values(), key=lambda s: s["views"], reverse=True)[:limit]
