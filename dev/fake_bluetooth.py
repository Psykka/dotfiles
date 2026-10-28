"""A pretend Bluetooth, with the same calls as waybar/.config/waybar/
bluetooth.py, to see and test the menu's Bluetooth page on a machine
without an adapter. dev/panel-sizes.py puts it in place of the real one;
nothing reaches BlueZ.

Devices: headphones connected with their battery, a mouse and a speaker
paired, a few nearby. Connecting takes a moment; the speaker always fails
(off or out of reach); pairing a phone asks to confirm a code.
"""
from gi.repository import GLib

DELAY_MS = 700

state = {"powered": True, "discovering": False}
watchers = []
agents = []
DEVICES = [
    dict(path="/fake/hp", name="WH-1000XM4", icon="audio-headphones", paired=True, connected=True, battery=80),
    dict(path="/fake/mouse", name="MX Master 3", icon="input-mouse", paired=True, connected=False, battery=None),
    dict(path="/fake/speaker", name="Living Room Speaker With A Long Name", icon="audio-card",
         paired=True, connected=False, battery=None, fails=True),
    dict(path="/fake/phone", name="Pixel 8", icon="phone", paired=False, connected=False, battery=None,
         rssi=-50, confirm=True),
    dict(path="/fake/kb", name="Keychron K2", icon="input-keyboard", paired=False, connected=False,
         battery=None, rssi=-60),
    dict(path="/fake/tv", name="Samsung TV", icon="", paired=False, connected=False, battery=None, rssi=-75),
]


def changed():
    for w in watchers:
        w()


def adapter():
    return "/fake/hci0", {"Powered": state["powered"], "Alias": "fedora", "Discovering": state["discovering"]}


def devices():
    return [{"address": "00:00:00:00:00:00", "named": True, "rssi": None, **d} for d in DEVICES]


def find(path):
    return next(d for d in DEVICES if d["path"] == path)


def set_powered(on):
    state["powered"] = on
    if not on:
        state["discovering"] = False
    changed()


def discover(on):
    state["discovering"] = on and state["powered"]
    changed()


def later(fn):
    GLib.timeout_add(DELAY_MS, lambda: fn() or False)


def connect(path, done=None):
    d = find(path)

    def finish():
        if d.get("fails"):
            done and done("br-connection-page-timeout")
            return
        d["connected"] = True
        if d["icon"] == "input-mouse":
            d["battery"] = 45
        changed()
        done and done(None)
    later(finish)


def disconnect(path, done=None):
    def finish():
        find(path)["connected"] = False
        changed()
        done and done(None)
    later(finish)


def pair(path, done=None):
    d = find(path)

    def paired(ok=True):
        if not ok:
            done and done("Authentication Rejected")
            return
        d["paired"] = True
        connect(path, done)
    if d.get("confirm") and agents:
        later(lambda: agents[-1].on_request("confirm", d["name"], "123456", paired))
    else:
        later(paired)


def cancel_pairing(path):
    pass


def forget(path):
    d = find(path)
    d.update(paired=False, connected=False, battery=None)
    later(changed)


def watch(on_change):
    watchers.append(on_change)


class Agent:
    def __init__(self, on_request):
        self.on_request = on_request
        agents.append(self)

    def close(self):
        agents.remove(self)
