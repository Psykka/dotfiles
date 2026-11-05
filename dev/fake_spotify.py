"""A pretend Spotify, with the same calls the media popup uses from
waybar/.config/waybar/spotify.py, to see and test the popup without a
Spotify account. dev/panel-sizes.py puts it in place of the real one;
nothing reaches Spotify or Soloist (the real player is left alone).

Playlists: Liked Songs and more than fit on a page, one with a name far too
long. Search: mixed results; "nothing" finds nothing and "fail" fails.
Devices: this computer (Soloist), a phone, a speaker with a long name.
log_out() and log_out_soloist() take the two logins away, to see what the
popup asks; logging back in takes a moment, like the browser.
"""
import pathlib
import time

from gi.repository import GLib

# Pictures for the rows (any will do): the repo's screenshots
SHOTS = pathlib.Path(__file__).resolve().parents[1] / "screenshots"
PICTURES = ["file://" + str(p) for p in sorted(SHOTS.glob("*.png"))]


def pic(i):
    """Every third row without one: the icon stays in its place."""
    return PICTURES[i % len(PICTURES)] if PICTURES and i % 3 else None


DELAY_S = 0.3  # each call, like the Web API (they run in threads)
LOGIN_MS = 1500


class NotLoggedIn(Exception):
    pass


class Failed(Exception):
    pass


state = {"web": True, "soloist": True, "pending": False, "active": "here", "played": None, "liked": set()}
PLAYLISTS = ([dict(kind="liked", uri="spotify:user:me:collection", title="Liked Songs", sub="372 songs", image=None)]
             + [dict(kind="playlist", uri=f"spotify:playlist:p{i}", title=f"Playlist {i}", sub=f"Me, {i * 7} songs",
                     image=pic(i)) for i in range(1, 15)]
             + [dict(kind="playlist", uri="spotify:playlist:long",
                     title="A playlist with a name far too long to fit in the popup at all",
                     sub="Someone with a long name too, 1234 songs", image=pic(2))])
QUEUE = [dict(kind="track", uri=f"spotify:track:q{i}", title=f"Up next {i}", sub="Some Artist", image=pic(i))
         for i in range(1, 10)]
DEVICES = [
    dict(id="here", name="fedora", type="speaker", here=True),
    dict(id="phone", name="Pixel 8", type="smartphone", here=False),
    dict(id="tv", name="Living Room Speaker With A Long Name", type="speaker", here=False),
    dict(id="pc", name="DESKTOP-RUBAGJ4", type="computer", here=False),
]


def wait():
    time.sleep(DELAY_S)


def web():
    wait()
    if not state["web"]:
        raise NotLoggedIn()


def available():
    return True


def logged_in():
    return state["web"]


def soloist_up():
    return state["soloist"]


def login_pending():
    return state["pending"]


def start_login():
    state["pending"] = True

    def done():
        state.update(web=True, pending=False)
        return False
    GLib.timeout_add(LOGIN_MS, done)


def cancel_login():
    state["pending"] = False


def log_out():
    state["web"] = False


def log_out_soloist():
    state["soloist"] = False


def log_in_soloist():
    state["soloist"] = True


def playlists():
    web()
    return [dict(p) for p in PLAYLISTS]


def search(words, kind=None):
    web()
    if words == "fail":
        raise Failed("Spotify asks to wait a moment")
    if not words.strip() or words == "nothing":
        return []
    if kind == "album":
        return ALBUMS[:3]
    out = [dict(kind="artist", uri="spotify:artist:a", title=words.title(), sub="Artist", image=pic(1))]
    out += [dict(kind="track", uri=f"spotify:track:s{i}", title=f"{words} song {i}", sub="Some Artist, Another",
                 image=pic(i), context="spotify:album:b", length=150000 + i * 17000) for i in range(1, 11)]
    out += [dict(kind="album", uri="spotify:album:b", title=f"{words} (deluxe edition, remastered, with bonus tracks)",
                 sub="Album · Some Artist", image=pic(2))]
    return [r for r in out if not kind or r["kind"] == kind]


ALBUMS = [dict(kind="album", uri=f"spotify:album:a{i}", title=f"Album {i}", sub="Some Artist", image=pic(i))
          for i in range(1, 5)]
ARTISTS = []  # follows nobody: the empty page


def albums():
    web()
    return [dict(a) for a in ALBUMS]


def artists():
    web()
    return list(ARTISTS)


def recent():
    web()
    return [dict(q, title=f"Played before {i}", context="spotify:album:b") for i, q in enumerate(QUEUE[:5], 1)]


def tracks(item):
    web()
    n = 40 if item["kind"] == "liked" else 9
    return [dict(kind="track", uri=f"spotify:track:t{i}", title=f"Song {i} of {item['title']}",
                 sub="Some Artist", image=item.get("image") or pic(i), context=item["uri"], length=180000 + i * 1000)
            for i in range(1, n + 1)]


def liked(uri):
    wait()
    return uri in state["liked"]


def set_liked(uri, on):
    wait()
    (state["liked"].add if on else state["liked"].discard)(uri)


def soloist_version():
    return "1.3.10.44 (20261105)"


def queue():
    web()
    return [dict(q) for q in QUEUE]


def devices():
    web()
    return [dict(d, active=d["id"] == state["active"]) for d in DEVICES]


def play(uri, context=None):
    wait()
    if not state["soloist"]:
        raise Failed("Soloist isn't logged in: pick this computer once in the Spotify app")
    state.update(played=(context, uri), active="here")


def transfer(device):
    wait()
    state["active"] = device["id"]
