"""A pretend VPN daemon, with the same calls as waybar/.config/waybar/vpn.py,
to see and test the menu's VPN page without vpnd. dev/panel-sizes.py puts it
in place of the real one; nothing reaches the network.

VPNs: a WireGuard one into an office network, one out to the internet with
a long name, an OpenVPN one whose password is always wrong, an OpenConnect
one. Connecting takes a moment; traffic grows while on.
"""
from gi.repository import GLib

from vpn import PROTOCOLS  # noqa: F401  (the page lists them)

DELAY_MS = 700

watchers = []
PROFILES = [
    dict(name="support", kind="wireguard", server="vpn.example.org"),
    dict(name="Proton BR-FREE#12 with a long name", kind="wireguard", server="node-br-12.protonvpn.net"),
    dict(name="Office", kind="openvpn", server="vpn.example.com", login=True, fails="AUTH: Received control "
         "message: AUTH_FAILED"),
    dict(name="Work", kind="openconnect", server="gp.example.com", protocol="gp"),
]
state = dict(state="off", profile="", kind="", mode="full", error="", since=0, addresses=[], routes=[], dns=[],
             endpoint="", handshake=0, rx=0, tx=0, last="support", apps=[])


def available():
    return True


def snapshot():
    return dict(state, profiles=[dict(p) for p in PROFILES], apps=[dict(a) for a in state["apps"]])


def changed():
    for w in watchers:
        w(snapshot())


def status():
    if state["state"] == "on":
        state["rx"] += 48_000
        state["tx"] += 9_000
    return snapshot()


def watch(fn):
    watchers.append(fn)
    fn(snapshot())


def find(name):
    return next((p for p in PROFILES if p["name"] == name), None)


def up(name):
    p = find(name)
    if not p:
        return f'no VPN named "{name}"'
    state.update(state="connecting", profile=name, kind=p["kind"], error="", last=name, rx=0, tx=0,
                 addresses=[], routes=[], dns=[])
    changed()

    def finish():
        if state["profile"] != name or state["state"] != "connecting":
            return False
        if p.get("fails"):
            state.update(state="failed", error=p["fails"])
        else:
            office = p["name"] == "support"
            state.update(state="on", addresses=["10.8.0.7/32" if office else "10.2.0.2/32"],
                         routes=["10.8.0.0/24"] if office else ["0.0.0.0/0", "::/0"],
                         dns=[] if office else ["10.2.0.1"], endpoint=p["server"] + ":51820")
        changed()
        return False
    GLib.timeout_add(DELAY_MS, finish)
    return None


def down():
    state.update(state="off", error="", addresses=[], routes=[], dns=[], rx=0, tx=0)
    changed()


def set_mode(mode):
    state["mode"] = mode
    changed()


def remove(name):
    PROFILES[:] = [p for p in PROFILES if p["name"] != name]
    if state["profile"] == name:
        down()
    changed()


def candidates(limit=4):
    return [("proton-br-12.conf", "Downloads", ("file", "/fake/proton.conf")),
            ("office.ovpn", "Documents", ("file", "/fake/office.ovpn")),
            ("support", "GNOME", ("nm", "support"))][:limit]


def kind_of(source):
    return ("openvpn", True) if source[1].endswith(".ovpn") else ("wireguard", False)


def import_source(source, name, username="", password=""):
    if find(name):
        return f'there is already a VPN named "{name}"'
    kind, _ = kind_of(source)
    PROFILES.append(dict(name=name, kind=kind, server="imported.example.com"))
    changed()
    return None


def add_openconnect(name, server, protocol, username, password):
    if not server:
        return "the server is missing"
    PROFILES.append(dict(name=name, kind="openconnect", server=server, protocol=protocol))
    changed()
    return None


CHOSEN = ["firefox.desktop", "org.qbittorrent.qBittorrent.desktop", "spotify.desktop"]
APPS = {"firefox.desktop": ("Firefox", "firefox"),
        "org.qbittorrent.qBittorrent.desktop": ("qBittorrent, with a name long enough to be cut", "qbittorrent"),
        "spotify.desktop": ("Spotify", "spotify")}


def chosen():
    return list(CHOSEN)


def choose(app_id):
    if app_id not in CHOSEN:
        CHOSEN.append(app_id)
    changed()


def unchoose(app_id):
    CHOSEN[:] = [i for i in CHOSEN if i != app_id]


def app_info(app_id):
    name, exe = APPS.get(app_id, (None, None))
    return (name, None, exe) if name else None


def outside(exe):
    """Spotify is open outside the VPN."""
    return ["4343"] if exe == "spotify" else []


def add_app(output=None, after=None):
    choose("org.qbittorrent.qBittorrent.desktop")


def open_chosen(app_id):
    _, exe = APPS[app_id]
    state["apps"] = state["apps"] + [dict(name=exe, pids=[4242])]
    changed()
