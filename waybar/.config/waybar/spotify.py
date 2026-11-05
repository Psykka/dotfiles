#!/usr/bin/env python3
"""Spotify for the bar's media popup: playlists, search, the queue and the
devices from the Web API, through your own Spotify app; the playing itself
is Soloist's (soloist/ in the dotfiles), driven with `soloist ctl`.

The app's client ID and the login's refresh token live in the keyring.
Logging in (the popup's button, or `spotify.py login`) opens the browser
once; Spotify sends it back to 127.0.0.1:8989/login, the redirect URI the
app has to list. Every call here blocks: the popup makes them in threads.

dev/fake_spotify.py has the same calls, for tests without Spotify.

Usage: spotify.py login            log in (opens the browser)
       spotify.py length TRACK_ID  a track's length in ms (for soloist-mpris)
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SOLOIST = os.path.expanduser("~/.local/bin/soloist")
# Soloist's own Connect device ID: tells it apart from the official app,
# which also goes by the hostname
SOLOIST_ID = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                          "soloist", ".device_id")
API = "https://api.spotify.com/v1/"
ACCOUNTS = "https://accounts.spotify.com/"
REDIRECT = ("127.0.0.1", 8989, "/login")
SCOPES = ("playlist-read-private playlist-read-collaborative user-library-read "
          "user-read-playback-state user-modify-playback-state user-read-currently-playing")
LOGIN_TIMEOUT_S = 300
# The access token (an hour long) between popups, so each one doesn't
# refresh it; only this user can read it
TOKEN_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "spotify-token.json")
PAGE = 50  # the most the Web API gives at once


class NotLoggedIn(Exception):
    pass


class Failed(Exception):
    """Spotify said no, or couldn't be reached: the message is for the user."""


# ------------------------------------------------------------ keyring

def secret(key):
    out = subprocess.run(["secret-tool", "lookup", "service", "spotify", "key", key],
                         capture_output=True, text=True)
    return out.stdout.strip() or None


def store(key, value, label):
    subprocess.run(["secret-tool", "store", "--label", label, "service", "spotify", "key", key],
                   input=value, text=True, check=True)


def client_id():
    return secret("client-id")


def available():
    """Set up on this machine: Soloist installed and an app's client ID."""
    return os.path.exists(SOLOIST) and bool(shutil.which("secret-tool")) and bool(client_id())


def logged_in():
    return bool(secret("refresh-token"))


# ------------------------------------------------------------ login

def login():
    """PKCE, as the Web API asks of apps without a secret: the browser
    logs in and comes back here with a code, traded for the tokens."""
    cid = client_id()
    if not cid:
        raise Failed("No Spotify app: store its client ID in the keyring first")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    host, port, path = REDIRECT
    redirect = f"http://{host}:{port}{path}"
    got = {}

    class Back(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            if url.path != path or q.get("state", [""])[0] != state:
                self.send_response(404)
                self.end_headers()
                return
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            done = "Logged in" if "code" in got else "Not logged in"
            self.wfile.write(f"<p style='font:16px sans-serif'>{done}. You can close this tab.</p>".encode())

        def log_message(self, *_):
            pass

    try:
        server = http.server.HTTPServer((host, port), Back)
    except OSError:
        raise Failed(f"Port {port} is busy: another login is open")
    server.timeout = 1
    url = ACCOUNTS + "authorize?" + urllib.parse.urlencode(dict(
        client_id=cid, response_type="code", redirect_uri=redirect, scope=SCOPES, state=state,
        code_challenge_method="S256", code_challenge=challenge))
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.monotonic() + LOGIN_TIMEOUT_S
    try:
        while not got and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in got:
        raise Failed("Login cancelled" if got else "Login timed out")
    keep(token_request(grant_type="authorization_code", code=got["code"], redirect_uri=redirect,
                       client_id=cid, code_verifier=verifier))


def logout():
    subprocess.run(["secret-tool", "clear", "service", "spotify", "key", "refresh-token"])
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass


def token_request(**form):
    req = urllib.request.Request(ACCOUNTS + "api/token", data=urllib.parse.urlencode(form).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            # The refresh token was revoked (or the app's ID changed)
            raise NotLoggedIn()
        raise Failed(f"Spotify answered {e.code}")
    except (OSError, ValueError):
        raise Failed("Can't reach Spotify")


def keep(tokens):
    # Spotify may hand out a new refresh token each time: the old one dies
    if tokens.get("refresh_token"):
        store("refresh-token", tokens["refresh_token"], "Spotify login (the bar's media popup)")
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"access": tokens["access_token"], "until": time.time() + tokens.get("expires_in", 3600) - 60}, f)
    return tokens["access_token"]


def access_token(fresh=False):
    if not fresh:
        try:
            t = json.load(open(TOKEN_FILE))
            if t["until"] > time.time():
                return t["access"]
        except (OSError, ValueError, KeyError):
            pass
    refresh = secret("refresh-token")
    if not refresh:
        raise NotLoggedIn()
    return keep(token_request(grant_type="refresh_token", refresh_token=refresh, client_id=client_id()))


# ------------------------------------------------------------ Web API

def api(method, path, body=None, fresh=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + access_token(fresh), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code == 401 and not fresh:
            return api(method, path, body, fresh=True)
        if e.code == 429:
            raise Failed("Spotify asks to wait a moment")
        if e.code == 404 and path.startswith("me/player"):
            raise Failed("No device is playing")
        try:
            msg = json.load(e)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            msg = f"Spotify answered {e.code}"
        raise Failed(msg)
    except (OSError, ValueError):
        raise Failed("Can't reach Spotify")


def names(people):
    return ", ".join(p.get("name", "") for p in people or [] if p)


def row(kind, uri, title, sub):
    return {"kind": kind, "uri": uri, "title": title or "", "sub": sub or ""}


def playlists():
    """Liked Songs first, then every playlist (followed ones too)."""
    me = api("GET", "me")
    liked = api("GET", "me/tracks?limit=1").get("total", 0)
    rows = [row("liked", f"spotify:user:{me['id']}:collection", "Liked Songs", f"{liked} songs")]
    offset = 0
    while True:
        page = api("GET", f"me/playlists?limit={PAGE}&offset={offset}")
        for p in page.get("items") or []:
            if p:
                total = (p.get("items") or p.get("tracks") or {}).get("total")
                owner = (p.get("owner") or {}).get("display_name") or ""
                sub = ", ".join(x for x in (owner, f"{total} songs" if total is not None else "") if x)
                rows.append(row("playlist", p["uri"], p.get("name"), sub))
        offset += PAGE
        if not page.get("next") or offset >= 500:
            return rows


def search(words):
    if not words.strip():
        return []
    q = urllib.parse.urlencode({"q": words, "type": "artist,track,album,playlist", "limit": 10})
    r = api("GET", "search?" + q)
    items = lambda k: [x for x in (r.get(k) or {}).get("items") or [] if x]
    out = [row("artist", a["uri"], a.get("name"), "Artist") for a in items("artists")[:1]]
    out += [row("track", t["uri"], t.get("name"), names(t.get("artists"))) for t in items("tracks")]
    out += [row("album", a["uri"], a.get("name"), "Album · " + names(a.get("artists"))) for a in items("albums")[:4]]
    out += [row("playlist", p["uri"], p.get("name"), "Playlist · " + ((p.get("owner") or {}).get("display_name") or ""))
            for p in items("playlists")[:4]]
    return out


def queue():
    r = api("GET", "me/player/queue") or {}
    return [row("track", t["uri"], t.get("name"), names(t.get("artists") or (t.get("show") and [t["show"]])))
            for t in r.get("queue") or [] if t]


def devices():
    """Every Connect device, this machine's Soloist marked "here"."""
    try:
        mine = open(SOLOIST_ID).read().strip()
    except OSError:
        mine = None
    return [{"id": d["id"], "name": d["name"], "type": (d.get("type") or "").lower(),
             "active": d.get("is_active", False), "here": d["id"] == mine}
            for d in api("GET", "me/player/devices").get("devices") or []]


def length(track_id):
    return api("GET", f"tracks/{track_id}").get("duration_ms")


# ------------------------------------------------------------ playing

def ctl(*args):
    r = subprocess.run([SOLOIST, "ctl", *args], capture_output=True, text=True, timeout=15)
    if r.returncode:
        raise Failed((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                     else "Soloist didn't answer")
    return r.stdout


def soloist_up():
    try:
        return "logged in: yes" in ctl("status")
    except (Failed, OSError, subprocess.TimeoutExpired):
        return False


def play(uri):
    """Plays here, on Soloist (it takes over from another device)."""
    if not soloist_up():
        raise Failed("Soloist isn't logged in: pick this computer once in the Spotify app")
    ctl("play", uri)


def transfer(device):
    """Moves the playing to another device (or back here)."""
    if device.get("here"):
        ctl("activate")
    else:
        api("PUT", "me/player", {"device_ids": [device["id"]], "play": True})


def main():
    args = sys.argv[1:]
    try:
        if args == ["login"]:
            login()
            print("Logged in")
        elif len(args) == 2 and args[0] == "length":
            print(length(args[1]) or "")
        else:
            sys.exit(__doc__.strip())
    except NotLoggedIn:
        sys.exit("Not logged in: spotify.py login")
    except Failed as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
