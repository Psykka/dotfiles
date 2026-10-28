#!/usr/bin/env python3
"""Checks that every notification card has the same size, and keeps it:
short or long text, markup, a picture or an icon, buttons, a progress bar,
critical, replaced in place, more than fit on screen, closing one by one.
Also the volume indicator (osd).

Sends them straight to the running server (waybar/.config/waybar/
notifications.py) over D-Bus, reads the sizes on screen every 20ms through
its Layout call, and closes its own notifications at the end (yours stay).
Exit status 1 when a card is not CARD_W×CARD_H or something changed size.

Usage: dev/notification-sizes.py [--shots DIR]
"""
import json
import os
import subprocess
import sys
import time

import gi

gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

NAME, PATH = "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
OWN = "org.dotfiles.Notifications"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "waybar/.config/waybar"))
import notifications  # noqa: E402  (for CARD_W, CARD_H, OSD_W, OSD_H)

bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def call(iface, method, params=None, reply=None):
    out = bus.call_sync(NAME, PATH, iface, method, params, GLib.VariantType(reply) if reply else None,
                        Gio.DBusCallFlags.NONE, 3000)
    return out.unpack()[0] if out and out.n_children() else None


def notify(summary, body="", app="size-test", icon="", actions=(), hints=None, replaces=0, timeout=0):
    # Transient: kept out of the history the calendar shows
    hints = {"transient": GLib.Variant("b", True), **(hints or {})}
    params = GLib.Variant("(susssasa{sv}i)", (app, replaces, icon, summary, body, list(actions), hints, timeout))
    return call(NAME, "Notify", params, "(u)")


def pixels(w, h):
    """A raw RGBA picture, sent the way apps do (image-data)."""
    data = bytes((x * 255 // w, y * 255 // h, 160, 255)[c] for y in range(h) for x in range(w) for c in range(4))
    return GLib.Variant("(iiibiiay)", (w, h, w * 4, True, 8, 4, data))


def main():
    shots = sys.argv[2] if sys.argv[1:2] == ["--shots"] else None
    if shots:
        os.makedirs(shots, exist_ok=True)
    server = bus.call_sync(NAME, PATH, NAME, "GetServerInformation", None, None, Gio.DBusCallFlags.NONE, 3000)
    if server.unpack()[0] != "notifications":
        sys.exit(f"notification-sizes: the server running is {server.unpack()[0]!r}, not notifications.py")

    want = [notifications.CARD_W, notifications.CARD_H]
    want_osd = [notifications.OSD_W, notifications.OSD_H]
    bad = {}  # (step, what): [first size, last size, frames]
    seen = {"window": None, "osd": None}
    step = ["start"]

    def problem(what, size):
        p = bad.setdefault((step[0], what), [size, size, 0])
        p[1], p[2] = size, p[2] + 1

    def check():
        layout = json.loads(call(OWN, "Layout", None, "(s)"))
        for card in layout["cards"]:
            for part in ("size", "box"):
                if card[part] != want:
                    problem(f"a card's {part} is not {want[0]}x{want[1]}", card[part])
        for key in ("window", "osd"):
            size = layout[key]
            if key == "osd" and size and size != want_osd:
                problem(f"the osd is not {want_osd[0]}x{want_osd[1]}", size)
            if size and seen[key] and size != seen[key]:
                problem(f"the {key} changed size from {seen[key][0]}x{seen[key][1]}", size)
            seen[key] = size or seen[key]

    def wait(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            check()
            time.sleep(0.02)

    def shot(name):
        if shots:
            subprocess.run(["grim", os.path.join(shots, f"notifications-{name}.png")])

    ids = []
    long_text = "A body long enough to need more than two lines in the card, so it has to be cut " * 3
    cases = [
        ("short", lambda: notify("Short", "Hello")),
        ("no body", lambda: notify("Only a title")),
        ("no title", lambda: notify("", "Only a body", app="Some app")),
        ("long", lambda: notify("A very long title that goes on and on well past the card's width", long_text)),
        ("markup", lambda: notify("Markup", "<b>bold</b> <i>italic</i> <a href='x'>link</a> <img src='x'/> end")),
        ("bad markup", lambda: notify("Not markup", "a < b & c > d <unclosed")),
        ("lines", lambda: notify("New lines", "one\ntwo\nthree\nfour")),
        ("icon", lambda: notify("Icon", "From the icon theme", icon="audio-volume-high")),
        ("missing icon", lambda: notify("Missing icon", "Not in the theme", icon="no-such-icon-anywhere")),
        ("picture", lambda: notify("Picture", long_text, hints={"image-data": pixels(320, 120)})),
        ("tall picture", lambda: notify("Tall picture", "Portrait", hints={"image-data": pixels(40, 300)})),
        ("buttons", lambda: notify("Buttons", long_text, actions=["default", "Open", "a", "One",
                                                               "b", "Two", "c", "Three", "d", "Four"])),
        ("progress", lambda: notify("Progress", long_text, hints={"value": GLib.Variant("i", 40)})),
        ("all at once", lambda: notify("Everything", long_text, icon="audio-volume-high",
                                       actions=["a", "One"], hints={"value": GLib.Variant("i", 70),
                                                                    "urgency": GLib.Variant("y", 2)})),
        ("critical", lambda: notify("Critical", "Never expires", hints={"urgency": GLib.Variant("y", 2)})),
        ("long app name", lambda: notify("App", "Name", app="An application with a really long name")),
    ]
    try:
        for name, send in cases:
            step[0] = f"send {name}"
            ids.append(send())
            wait(0.35)
        shot("full")
        step[0] = "replace with longer text"
        notify("Replaced", long_text * 2, replaces=ids[0])
        wait(0.4)
        for value in (10, 55, 100):
            step[0] = f"progress {value}"
            notify("Progress", "Updating", hints={"value": GLib.Variant("i", value)}, replaces=ids[12])
            wait(0.2)
        for value in (20, 80, 0):
            step[0] = f"osd {value}"
            notify(f"Volume {value}%", app="OSD", hints={"category": GLib.Variant("s", "osd"),
                                                       "value": GLib.Variant("i", value)})
            wait(0.2)
        shot("osd")
        step[0] = "expiring"
        ids.append(notify("Expires", "In two seconds", timeout=2000))
        wait(2.8)
        for nid in reversed(ids):
            step[0] = f"close {nid}"
            call(NAME, "CloseNotification", GLib.Variant("(u)", (nid,)))
            wait(0.15)
        step[0] = "settle"
        wait(1.0)
    finally:
        for nid in ids:
            call(NAME, "CloseNotification", GLib.Variant("(u)", (nid,)))

    if bad:
        for (when, what), (first, last, frames) in bad.items():
            print(f"  {when:26} {what} ({first[0]}x{first[1]} .. {last[0]}x{last[1]}, {frames} frames)")
        print(f"notifications: FAIL after {len({w for w, _ in bad})} steps")
        sys.exit(1)
    print(f"notifications: ok, every card {want[0]}x{want[1]}, window {seen['window']}, osd {seen['osd']}")


if __name__ == "__main__":
    main()
