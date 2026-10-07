"""Web blueprint of Main.py: stateless functions, no input()/print/dotenv. See MainWeb.md before porting."""
import re
import time
import json
import base64
import hashlib
import secrets
import difflib
from urllib.parse import urlparse, parse_qs, urlencode

import requests

SPOTIFY = "https://api.spotify.com/v1"
YOUTUBE = "https://www.googleapis.com/youtube/v3"
SCOPE = "playlist-modify-private"
MAX_SONGS = 150            # cap per playlist
MATCHED, UNCERTAIN = 0.8, 0.6   # score >= 0.8 matched, 0.6-0.8 uncertain, below not_found
SESSION_TTL = 30 * 24 * 3600    # stay logged in for 30 days


class WebError(Exception):
    """Error with an http status and a message that is safe to show the user."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


# ---------- YouTube ----------

def extract_playlist_id(playlist_url):
    """Strict check: youtube.com link with a ?list= id. Mix playlists (RD...) are not readable by the API."""
    parsed = urlparse(playlist_url.strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        raise WebError(400, "Please paste a youtube.com playlist link.")
    ids = parse_qs(parsed.query).get("list", [])
    if not ids or not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", ids[0]):
        raise WebError(400, "No playlist found in that link.")
    if ids[0].startswith("RD"):
        raise WebError(400, "YouTube Mix playlists can't be read. Save it as a normal playlist first.")
    return ids[0]


def youtube_get(endpoint, youtube_api_key, **params):
    response = requests.get(f"{YOUTUBE}/{endpoint}", params={**params, "key": youtube_api_key}, timeout=15)
    if response.status_code == 404:
        raise WebError(404, "Playlist not found. Is it private?")
    if response.status_code != 200:
        raise WebError(502, "YouTube API error.")
    return response.json()


def fetch_playlist_title(playlist_id, youtube_api_key):
    items = youtube_get("playlists", youtube_api_key, part="snippet", id=playlist_id)["items"]
    if not items:
        raise WebError(404, "Playlist not found. Is it private?")
    return items[0]["snippet"]["title"]


def fetch_playlist_videos(playlist_id, youtube_api_key, limit=MAX_SONGS):
    """Returns [{id, title, channel, description}] for up to `limit` videos."""
    ids, page = [], None
    while len(ids) < limit:
        data = youtube_get("playlistItems", youtube_api_key, part="contentDetails", playlistId=playlist_id, maxResults=50, **({"pageToken": page} if page else {}))
        ids += [i["contentDetails"]["videoId"] for i in data["items"]]
        page = data.get("nextPageToken")
        if not page:
            break
    ids = ids[:limit]
    videos = []
    for i in range(0, len(ids), 50):   # private/deleted videos simply don't come back
        data = youtube_get("videos", youtube_api_key, part="snippet", id=",".join(ids[i:i + 50]))
        videos += [{"id": v["id"], "title": v["snippet"]["title"], "channel": v["snippet"].get("channelTitle", ""),
                    "description": v["snippet"].get("description", "")} for v in data["items"]]
    if not videos:
        raise WebError(404, "That playlist has no readable videos.")
    return videos


# ---------- matching (same logic as Main.py) ----------

def clean_title(video_title, channel_title="", description=""):
    """Returns (artist, song) using only what the youtube api gives us."""
    provided = re.search(r"Provided to YouTube by [^\n]*\n+([^\n·]+?) · ([^\n·]+)", description)  # auto-generated Topic videos
    if provided:
        return provided.group(2).strip(), provided.group(1).strip()
    title = video_title.split("|")[0]
    junk = r"official|videos?|audio|lyrics?|visuali[sz]er|music|mv|m/v|hd|4k|hq|explicit|clip|full|version"
    title = re.sub(rf"[\(\[][^\)\]]*\b({junk})\b[^\)\]]*[\)\]]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\(\[]?\b(feat|ft)\b\.?[^\)\]]*[\)\]]?", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -–—")
    parts = re.split(r"\s[-–—]\s", title, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip().strip('"')
    return re.sub(r"\s*(- Topic|VEVO)$", "", channel_title, flags=re.IGNORECASE).strip(), title.strip('"')


def similarity(a, b):
    clean = lambda text: re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
    return difflib.SequenceMatcher(None, clean(a), clean(b)).ratio()


def spotify_request(method, path, token, **kwargs):
    """Spotify call with 429 retry (waits Retry-After) and a pause so we stay under the rate limit."""
    for _ in range(5):
        response = requests.request(method, SPOTIFY + path, headers={"Authorization": f"Bearer {token}"}, timeout=15, **kwargs)
        if response.status_code != 429:
            break
        time.sleep(int(response.headers.get("Retry-After", 5)) + 1)
    time.sleep(0.3)
    if response.status_code == 401:
        raise WebError(401, "Spotify session expired. Please log in again.")
    if response.status_code == 403:
        raise WebError(403, "Spotify refused (the app owner needs Premium, and this account must be on the app's allow-list).")
    return response


def search_track(token, song, artist):
    """Best of the top 5 results: (uri, 'Song - Artist', score), uri None when nothing is close."""
    response = spotify_request("GET", "/search", token, params={"q": f"{song} {artist}".strip(), "type": "track", "limit": 5})
    if response.status_code != 200:
        return None, None, 0
    best, best_score = None, 0
    for track in response.json().get("tracks", {}).get("items", []):
        score = similarity(song, track["name"])
        if artist:
            score = 0.6 * score + 0.4 * max(similarity(artist, a["name"]) for a in track["artists"])
        if score > best_score:
            best, best_score = track, score
    if best is None or best_score < UNCERTAIN:
        return None, None, round(best_score, 2)
    return best["uri"], f"{best['name']} - {best['artists'][0]['name']}", round(best_score, 2)


def match_videos(token, videos):
    """Call with a chunk (~20) of videos. Returns one result per video with status matched/uncertain/not_found."""
    results = []
    for video in videos:
        artist, song = clean_title(video["title"], video.get("channel", ""), video.get("description", ""))
        uri, matched_name, score = search_track(token, song, artist)
        status = "not_found" if uri is None else "matched" if score >= MATCHED else "uncertain"
        results.append({"video_title": video["title"], "artist": artist, "song": song,
                        "uri": uri, "spotify_match": matched_name, "score": score, "status": status})
    return results


def dedupe_uris(uris):
    return list(dict.fromkeys(u for u in uris if u))   # keeps order, drops None and repeats


def create_playlist(token, name):
    """Private playlist on the logged-in account (the old /users/{id}/playlists url returns 403)."""
    response = spotify_request("POST", "/me/playlists", token, json={"name": name, "description": "Created from YouTube", "public": False})
    if response.status_code not in (200, 201):
        raise WebError(502, "Could not create the Spotify playlist.")
    body = response.json()
    return body["id"], body["external_urls"]["spotify"]


def add_items(token, playlist_id, uris):
    """Spotify takes 100 at a time; /items replaces the old /tracks url (403). Answers 201."""
    for i in range(0, len(uris), 100):
        response = spotify_request("POST", f"/playlists/{playlist_id}/items", token, json={"uris": uris[i:i + 100]})
        if response.status_code not in (200, 201):
            raise WebError(502, "Could not add songs to the playlist.")


# ---------- Spotify login (authorization code + PKCE) ----------

def make_pkce():
    """Returns (verifier, challenge). Keep the verifier server-side until the callback."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_login_url(client_id, redirect_uri, state, challenge):
    """`state` is a random value stored (e.g. in a short-lived cookie) and compared on return, blocks forged logins."""
    return "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPE,
        "state": state, "code_challenge_method": "S256", "code_challenge": challenge})


def token_request(client_id, client_secret, **form):
    response = requests.post("https://accounts.spotify.com/api/token", data=form, timeout=15,
                             headers={"Authorization": "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()})
    if response.status_code != 200:
        raise WebError(401, "Spotify login failed.")
    return response.json()   # access_token, expires_in, refresh_token (may be absent on refresh)


def exchange_code(client_id, client_secret, redirect_uri, code, verifier):
    return token_request(client_id, client_secret, grant_type="authorization_code", code=code, redirect_uri=redirect_uri, code_verifier=verifier)


# ---------- owner only + sessions ----------

def assert_owner(access_token, owner_spotify_id):
    """Asks Spotify who is logged in and refuses anyone but the owner."""
    response = requests.get(f"{SPOTIFY}/me", headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    if response.status_code != 200 or response.json().get("id") != owner_spotify_id:
        raise WebError(403, "This tool is private.")


def start_session(store, tokens, owner_spotify_id):
    """After the callback: verify owner, keep tokens SERVER-side, return a random id for the cookie.
    store is dict-like (Cloudflare KV in production, set it with expiry = SESSION_TTL)."""
    assert_owner(tokens["access_token"], owner_spotify_id)
    session_id = secrets.token_urlsafe(32)
    store[session_id] = {"user": owner_spotify_id, "refresh_token": tokens["refresh_token"],
                         "access_token": tokens["access_token"], "access_expires": time.time() + tokens["expires_in"] - 60,
                         "session_expires": time.time() + SESSION_TTL}
    return session_id


def get_access_token(store, session_id, client_id, client_secret, owner_spotify_id):
    """Every API request: owner re-checked, token refreshed when old (and owner verified again on refresh)."""
    session = store.get(session_id) if session_id else None
    if not session or session["user"] != owner_spotify_id or session["session_expires"] < time.time():
        raise WebError(401, "Please log in.")
    if session["access_expires"] < time.time():
        tokens = token_request(client_id, client_secret, grant_type="refresh_token", refresh_token=session["refresh_token"])
        assert_owner(tokens["access_token"], owner_spotify_id)
        session.update(access_token=tokens["access_token"], access_expires=time.time() + tokens["expires_in"] - 60,
                       refresh_token=tokens.get("refresh_token", session["refresh_token"]))
        store[session_id] = session
    return session["access_token"]
