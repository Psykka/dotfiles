#!/usr/bin/env python3
"""Bar popups: mini media player, calendar + notifications, general menu,
sound, displays, bluetooth, wallpaper.

Usage: panel.py media|calendar|menu|network|updates|sound|displays|bluetooth|wallpaper
Running it again with the same mode closes it; another mode replaces it.
"""
import atexit
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import gi

import audio
import bluetooth
import displays
import wallpaper

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")

# Approximate bar layout, used to center the media popup under the free
# space between the workspaces and the clock
WORKSPACES_WIDTH = 70
CLOCK_WIDTH = 150
PIDFILE = os.path.join(RUNTIME, "bar-panel.pid")
PANEL = os.path.abspath(__file__)

# Font Awesome glyphs
ICON = {
    "music": "", "play": "", "pause": "",
    "prev": "", "next": "", "volume": "", "muted": "",
    "mic": "", "mic-off": "", "lock": "", "logout": "",
    "reboot": "", "power": "", "keyboard": "",
    "down": "\uf078", "right": "\uf054", "left": "\uf053", "check": "\uf00c",
    "wifi": "\uf1eb", "ethernet": "\uf0e8", "offline": "\uf00d",
    "upgrade": "\uf35b",
    "display": "\uf108", "bluetooth": "\uf293",
    "warning": "\uf071", "wrench": "\uf0ad", "headphones": "\uf025",
    "mouse": "\uf8cc", "gamepad": "\uf11b", "phone": "\uf3cd", "laptop": "\uf109",
    "trash": "\uf1f8", "image": "\uf03e", "terminal": "\uf120",
}

CSS = b"""
window { background: transparent; }
.panel {
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.32);
    background: @surface;
    border-radius: 6px;
    padding: 16px;
    font-family: "JetBrains Mono", monospace;
    font-size: 13px;
    color: @fg;
}
.icon { font-family: "Font Awesome 6 Free"; font-weight: 900; }
.title { color: @hi; font-weight: bold; }
.muted { color: @mute; }
.heading { color: @mute; font-size: 11px; }
.art { background: @bg2; border-radius: 4px; color: @mute; font-size: 22px; }

button {
    background: transparent;
    border: none;
    border-radius: 4px;
    box-shadow: none;
    padding: 6px 10px;
    color: @fg;
}
button:hover { background: @line; color: @hi; }
button.yes { background: @accent; color: @bg0; }
button.tile { background: @bg2; padding: 12px 0; }
button.device { background: @bg2; padding: 8px 12px; }
button.device:hover { background: @line; }
.device-title { color: @hi; }
button.tile:hover { background: @line; }
.tile .icon { font-size: 16px; }
button.choice { background: @bg2; padding: 6px 0; }
button.choice:hover { background: @line; }
button.choice.yes { background: @accent; color: @bg0; }
button.small { padding: 2px 8px; font-size: 11px; color: @mute; }
button.small:hover { color: @hi; }
button.small:disabled { color: @faint; background: transparent; }
button.back { padding: 0; }
button.back:hover { background: transparent; }
button.back:hover .heading { color: @hi; }
.small { font-size: 11px; }
button.ctl { min-width: 40px; min-height: 32px; padding: 0; font-size: 14px; }
button.ctl.main { min-width: 48px; font-size: 18px; }
scale { padding: 0; margin: 0; }
levelbar trough { background: @line; border: none; border-radius: 3px; min-height: 6px; padding: 0; }
levelbar block { border: none; border-radius: 3px; min-height: 6px; }
levelbar block.filled { background: @accent; }
levelbar block.empty { background: transparent; }

scale.pill trough { border-radius: 8px; background: @line; }
scale.pill highlight { border-radius: 8px; background: @accent; }
scale.horizontal-pill trough { min-height: 28px; }
scale.horizontal-pill highlight { min-height: 28px; min-width: 34px; }
scale.vertical-pill trough { min-width: 28px; }
scale.vertical-pill highlight { min-width: 28px; min-height: 34px; }
scale.pill.off highlight { background: @off; }
scale.pill slider {
    min-width: 0;
    min-height: 0;
    margin: 0;
    background: transparent;
}
.pill-icon { color: @bg0; font-size: 12px; margin-left: 11px; }
.pill-icon.bottom { margin: 0 0 10px 0; }

scale trough {
    background: @line;
    border: none;
    border-radius: 2px;
    min-height: 4px;
}
scale highlight { background: @fg; border: none; border-radius: 2px; }
scale slider {
    background: @accent;
    border: none;
    border-radius: 6px;
    box-shadow: none;
    min-width: 12px;
    min-height: 12px;
    margin: -4px;
}


.notif { background: @bg2; border-radius: 4px; padding: 8px 10px; }

button.thumb { padding: 0; background: @bg2; border: 2px solid transparent; border-radius: 4px; }
button.thumb:hover { background: @bg2; border-color: @faint; }
button.thumb.picked { border-color: @accent; }
.slot { background: @bg2; border-radius: 4px; }
.loading { opacity: 0.4; transition: opacity 150ms; }
.panel.slim { padding: 8px 8px 8px 16px; }
.notice { background: @bg0; border-radius: 6px; padding: 10px 14px; }
.mark { background: @accent; color: @bg0; border-radius: 4px; font-size: 9px; padding: 2px 4px; margin: 4px; }
button.chip { padding: 2px; border: 1px solid transparent; border-radius: 4px; }
button.chip:hover { background: transparent; border-color: @faint; }
button.chip.yes { background: transparent; border-color: @accent; }
button.filter { padding: 2px 8px; font-size: 11px; background: @bg2; }
button.filter:hover { background: @line; }
button.filter.yes { background: @accent; color: @bg0; }
button.tab { padding: 2px 10px; font-size: 11px; color: @mute; }
button.tab.on { background: @bg2; color: @hi; }
.tuning:disabled { opacity: 0.5; }
entry.search { background: @bg2; color: @fg; border: none; border-radius: 4px; box-shadow: none; padding: 4px 8px; }
entry.search image { color: @mute; }

calendar {
    background: transparent;
    border: none;
    color: @fg;
    padding: 2px;
}
calendar.header { background: transparent; border: none; }
calendar.big { font-size: 15px; padding: 4px 6px; }
calendar.button { color: @mute; background: transparent; border: none; }
calendar:selected {
    background: @accent;
    color: @bg0;
    border-radius: 3px;
}
calendar.highlight { color: @mute; }
calendar:indeterminate { color: @faint; }
"""


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def spawn(*cmd):
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def take_over(mode):
    """Closes the open panel. Exits if it was this same mode (toggle)."""
    try:
        pid, old = open(PIDFILE).read().split()
        pid = int(pid)
        if b"panel.py" in open(f"/proc/{pid}/cmdline", "rb").read():
            os.kill(pid, signal.SIGTERM)
            if old == mode:
                sys.exit(0)
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(f"{os.getpid()} {mode}")


def label(text="", css=(), xalign=0.0, ellipsize=False, width=None):
    w = Gtk.Label(label=text, xalign=xalign)
    for c in css:
        w.get_style_context().add_class(c)
    if ellipsize:
        w.set_ellipsize(Pango.EllipsizeMode.END)
    if width:
        w.set_max_width_chars(width)
        w.set_width_chars(width)
    return w


def icon_button(icon, text=None, on_click=None, css=()):
    box = Gtk.Box(spacing=8)
    if text:
        box.pack_start(label(ICON[icon], ["icon"], xalign=0.5, width=2), False, False, 0)
        box.pack_start(label(text), False, False, 0)
    else:
        box.set_halign(Gtk.Align.CENTER)
        box.pack_start(label(ICON[icon], ["icon"], xalign=0.5), False, False, 0)
    b = Gtk.Button()
    for c in css:
        b.get_style_context().add_class(c)
    b.add(box)
    if on_click:
        b.connect("clicked", lambda _: on_click())
    return b


def hslider(lo, hi, on_change):
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
    s.set_draw_value(False)
    s.set_hexpand(True)
    s.connect("change-value", lambda _w, _s, v: on_change(max(lo, min(hi, v))) or False)
    return s


class Pill(Gtk.Overlay):
    """Thick rounded volume bar with the icon inside it (no knob).

    Clicking the icon calls on_icon_click, e.g. to toggle mute."""

    def __init__(self, icon, on_change, on_icon_click=None, vertical=False):
        super().__init__()
        if vertical:
            # Bottom is 0, the icon sits at the bottom
            self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
            self.scale.set_inverted(True)
            self.scale.set_draw_value(False)
            self.scale.set_vexpand(True)
            self.scale.connect("change-value", lambda _w, _s, v: on_change(max(0, min(100, v))) or False)
        else:
            self.scale = hslider(0, 100, on_change)
        ctx = self.scale.get_style_context()
        ctx.add_class("pill")
        ctx.add_class("vertical-pill" if vertical else "horizontal-pill")
        self.add(self.scale)
        self.icon = label(ICON[icon], ["icon", "pill-icon"] + (["bottom"] if vertical else []), xalign=0.5)
        self.icon.set_halign(Gtk.Align.CENTER if vertical else Gtk.Align.START)
        self.icon.set_valign(Gtk.Align.END if vertical else Gtk.Align.CENTER)
        self.add_overlay(self.icon)
        self.set_overlay_pass_through(self.icon, True)
        if on_icon_click:
            def hits_icon(e):
                if vertical:
                    return e.y > self.scale.get_allocated_height() - 34
                return e.x < 34
            self.scale.connect("button-press-event", lambda _w, e: hits_icon(e) and (on_icon_click() or True))

    def set(self, value, icon=None, muted=False):
        self.scale.set_value(value)
        if icon:
            self.icon.set_text(ICON[icon])
        ctx = self.scale.get_style_context()
        (ctx.add_class if muted else ctx.remove_class)("off")


def page_title(text, on_back):
    """Heading of a menu sub page, with a way back to the menu."""
    back = Gtk.Button(halign=Gtk.Align.START)
    back.get_style_context().add_class("back")
    row = Gtk.Box(spacing=6)
    row.pack_start(label(ICON["left"], ["icon", "heading"]), False, False, 0)
    row.pack_start(label(text, ["heading"]), False, False, 0)
    back.add(row)
    back.connect("clicked", lambda _: on_back())
    return back


def fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


# ---------------------------------------------------------------- media

class Media(Gtk.Box):
    FIELDS = ["status", "xesam:title", "xesam:artist", "mpris:artUrl",
              "mpris:length", "position", "volume", "playerName"]

    def __init__(self):
        super().__init__(spacing=28)
        self.art_url = None
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main.set_size_request(320, -1)
        self.pack_start(main, True, True, 0)

        top = Gtk.Box(spacing=14)
        self.art = Gtk.Image()
        self.art_box = Gtk.EventBox()
        self.art_placeholder = label(ICON["music"], ["icon", "art"], xalign=0.5)
        self.art_placeholder.set_size_request(64, 64)
        self.art_box.add(self.art_placeholder)
        top.pack_start(self.art_box, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_valign(Gtk.Align.CENTER)
        self.title = label(css=["title"], ellipsize=True, width=26)
        self.artist = label(ellipsize=True, width=26)
        self.player = label(css=["muted"], ellipsize=True, width=26)
        for w in (self.title, self.artist, self.player):
            info.pack_start(w, False, False, 0)
        top.pack_start(info, True, True, 0)
        main.pack_start(top, False, False, 0)

        self.seek = hslider(0, 1, lambda v: run("playerctl", "position", str(int(v))))
        times = Gtk.Box()
        self.pos = label(css=["muted"])
        self.length = label(css=["muted"], xalign=1.0)
        times.pack_start(self.pos, True, True, 0)
        times.pack_start(self.length, True, True, 0)
        main.pack_start(self.seek, False, False, 0)
        main.pack_start(times, False, False, 0)

        controls = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        controls.pack_start(icon_button("prev", css=["ctl"], on_click=lambda: run("playerctl", "previous")), False, False, 0)
        self.play = icon_button("play", css=["ctl", "main"], on_click=lambda: run("playerctl", "play-pause"))
        controls.pack_start(self.play, False, False, 0)
        controls.pack_start(icon_button("next", css=["ctl"], on_click=lambda: run("playerctl", "next")), False, False, 0)
        main.pack_start(controls, False, False, 0)

        self.vol = Pill("volume", lambda v: run("playerctl", "volume", f"{v / 100:.2f}"), vertical=True)
        self.pack_start(self.vol, False, False, 0)

        self.refresh()
        GLib.timeout_add_seconds(1, self.refresh)

    def refresh(self):
        fmt = "\x1f".join("{{%s}}" % f for f in self.FIELDS)
        out = run("playerctl", "metadata", "--format", fmt)
        if not out:
            self.title.set_text("Nothing playing")
            self.artist.set_text("")
            self.player.set_text("")
            self.pos.set_text("")
            self.length.set_text("")
            self.set_art(None)
            return True
        status, title, artist, art, length, pos, vol, player = (out.split("\x1f") + [""] * 8)[:8]
        self.title.set_text(title or "Unknown")
        self.artist.set_text(artist)
        self.player.set_text(player.capitalize())
        length_s = int(length or 0) / 1e6
        pos_s = int(pos or 0) / 1e6
        if length_s:
            pos_s = min(pos_s, length_s)
        self.seek.set_range(0, max(length_s, 1))
        self.seek.set_value(pos_s)
        self.pos.set_text(fmt_time(pos_s))
        self.length.set_text(fmt_time(length_s) if length_s else "")
        self.vol.set(float(vol or 0) * 100)
        self.play.get_child().get_children()[0].set_text(
            ICON["pause"] if status == "Playing" else ICON["play"])
        self.set_art(art or None)
        return True

    def set_art(self, url):
        if url == self.art_url:
            return
        self.art_url = url
        if not url:
            self.show_art(None)
        elif url.startswith("file://"):
            self.show_art(urllib.parse.unquote(url[7:]))
        elif url.startswith("http"):
            threading.Thread(target=self.fetch_art, args=(url,), daemon=True).start()

    def fetch_art(self, url):
        path = os.path.join(RUNTIME, "bar-art-" + hashlib.md5(url.encode()).hexdigest())
        try:
            if not os.path.exists(path):
                with urllib.request.urlopen(url, timeout=3) as r, open(path, "wb") as f:
                    f.write(r.read())
        except OSError:
            path = None
        GLib.idle_add(self.show_art, path)

    def show_art(self, path):
        child = self.art_box.get_child()
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 64, 64, True)
            self.art.set_from_pixbuf(pix)
            new = self.art
        except (GLib.Error, TypeError):
            new = self.art_placeholder
        if child is not new:
            self.art_box.remove(child)
            self.art_box.add(new)
            new.show()
        return False


# ------------------------------------------------- calendar + notifications

def notifications():
    try:
        data = json.loads(run("makoctl", "history", "-j") or "[]")
    except json.JSONDecodeError:
        return []
    # Older mako wraps the list as {"data": [[{"key": {"data": value}}]]}
    if isinstance(data, dict):
        data = data.get("data", [[]])[0]
        data = [{k: v.get("data") for k, v in n.items()} for n in data]
    return data


# mako keeps no "clear history" command, so clearing remembers the newest
# id seen and hides everything up to it (reset on reboot, like mako's history)
CLEARED = os.path.join(RUNTIME, "bar-notifications-cleared")


def visible_notifications():
    try:
        cleared = int(open(CLEARED).read())
    except (OSError, ValueError):
        cleared = 0
    # On-screen indicators (volume, brightness) are not notifications
    notes = [n for n in notifications() if int(n.get("id") or 0) > cleared
             and (n.get("app_name") or n.get("app-name")) != "OSD" and n.get("category") != "osd"]
    return sorted(notes, key=lambda n: -int(n.get("id") or 0))  # newest first


class Calendar(Gtk.Box):
    def __init__(self):
        super().__init__(spacing=28)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(400, -1)
        header = Gtk.Box()
        header.pack_start(label("NOTIFICATIONS", ["heading"]), True, True, 0)
        self.clear = Gtk.Button(label="Clear")
        self.clear.get_style_context().add_class("small")
        self.clear.connect("clicked", lambda _: self.clear_all())
        header.pack_end(self.clear, False, False, 0)
        left.pack_start(header, False, False, 0)

        # Shows as many whole cards as fit next to the calendar, then scrolls
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.scroll.add(self.items)
        left.pack_start(self.scroll, False, False, 0)
        self.header = header
        self.pack_start(left, True, True, 0)

        self.right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top = Gtk.Box()
        top.pack_start(label("CALENDAR", ["heading"]), True, True, 0)
        top.pack_end(icon_button("image", "Wallpaper", lambda: spawn(PANEL, "wallpaper"), css=["small"]),
                     False, False, 0)
        self.right.pack_start(top, False, False, 0)
        cal = Gtk.Calendar()
        cal.get_style_context().add_class("big")
        self.right.pack_start(cal, False, False, 0)
        self.pack_start(self.right, False, False, 0)
        self.fill(visible_notifications())

    def fill(self, notes):
        for c in self.items.get_children():
            self.items.remove(c)
        self.clear.set_sensitive(bool(notes))
        if not notes:
            self.items.pack_start(label("No notifications", ["muted"]), False, False, 0)
        # Same height for every card: one line each, cut with "…"
        for n in notes:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.get_style_context().add_class("notif")
            top = Gtk.Box(spacing=8)
            top.pack_start(label(n.get("summary") or "", ["title"], ellipsize=True), True, True, 0)
            app = n.get("app_name") or n.get("app-name") or ""
            top.pack_end(label(app, ["muted", "small"], xalign=1.0), False, False, 0)
            card.pack_start(top, False, False, 0)
            body = " ".join((n.get("body") or "").split())
            if body:
                card.pack_start(label(body, ellipsize=True), False, False, 0)
            self.items.pack_start(card, False, False, 0)
        self.items.show_all()
        # Sizes are only known once the window is styled and shown
        GLib.idle_add(self.fit)

    def fit(self):
        cards = self.items.get_children()
        if not cards:
            return False
        # Real height of each card (with or without a body line)
        room = self.right.get_preferred_height()[1] - self.header.get_preferred_height()[1] - 8
        height = 0
        for i, card in enumerate(cards):
            h = card.get_preferred_height()[1] + (6 if i else 0)
            if i and height + h > room:
                break
            height += h
        self.scroll.set_min_content_height(height)
        self.scroll.set_max_content_height(height)
        return False

    def clear_all(self):
        ids = [int(n.get("id") or 0) for n in notifications()]
        with open(CLEARED, "w") as f:
            f.write(str(max(ids, default=0)))
        run("makoctl", "dismiss", "--all")
        self.fill([])


# ---------------------------------------------------------- general menu

def devices(kind):
    """[(name, title, subtitle)] for 'sinks' or 'sources', without monitors.

    The full description is often huge ("ES1371/ES1373 / Creative Labs
    CT2518 (...)"), so the title is the device's short nick and the
    subtitle its active port ("Analog Output", "Headphones")."""
    try:
        items = json.loads(run("pactl", "--format=json", "list", kind) or "[]")
    except json.JSONDecodeError:
        return []
    out = []
    for d in items:
        if d["name"].endswith(".monitor"):
            continue
        props = d.get("properties", {})
        title = props.get("device.nick") or props.get("alsa.card_name") or d.get("description") or d["name"]
        port = next((x.get("description", "") for x in d.get("ports", [])
                     if x.get("name") == d.get("active_port")), "")
        out.append((d["name"], title, port or props.get("device.profile.description", "")))
    return out


class AudioRow(Gtk.Box):
    """Device picker + volume pill (icon toggles mute) for the sink or source."""

    def __init__(self, kind, heading, icon_on, icon_off, on_pick=None, action=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.kind = kind  # "sink" or "source"
        self.on_pick = on_pick
        self.icons = (icon_on, icon_off)
        target = f"@DEFAULT_{kind.upper()}@"
        # An optional small button on the heading's right (like "Clear")
        top = Gtk.Box()
        top.pack_start(label(heading, ["heading"]), True, True, 0)
        if action:
            top.pack_end(action, False, False, 0)
        self.pack_start(top, False, False, 0)

        # Current device; clicking opens the list of devices below it
        self.devices = devices(kind + "s")
        picker = Gtk.Button()
        picker.get_style_context().add_class("device")
        row = Gtk.Box(spacing=8)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title = label(css=["device-title"], ellipsize=True)
        self.subtitle = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.title, False, False, 0)
        names.pack_start(self.subtitle, False, False, 0)
        row.pack_start(names, True, True, 0)
        self.chevron = label(ICON["right"], ["icon", "muted"], xalign=1.0)
        row.pack_end(self.chevron, False, False, 0)
        picker.add(row)
        picker.connect("clicked", lambda _: self.toggle_list())
        self.pack_start(picker, False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=200)
        self.revealer.add(self.list)
        self.pack_start(self.revealer, False, False, 0)
        self.show_device()

        self.pill = Pill(icon_on, lambda v: run("pactl", f"set-{kind}-volume", target, f"{int(v)}%"),
                         lambda: run("pactl", f"set-{kind}-mute", target, "toggle") or self.refresh())
        self.pack_start(self.pill, False, False, 0)
        self.refresh()

    def show_device(self):
        default = run("pactl", f"get-default-{self.kind}")
        current = next((d for d in self.devices if d[0] == default), (default, default, ""))
        self.title.set_text(current[1])
        self.subtitle.set_text(current[2])
        for c in self.list.get_children():
            self.list.remove(c)
        for name, title, subtitle in self.devices:
            b = Gtk.Button()
            row = Gtk.Box(spacing=10)
            mark = label(ICON["check"] if name == default else "", ["icon"], xalign=0.5, width=2)
            row.pack_start(mark, False, False, 0)
            row.pack_start(label(f"{title} · {subtitle}" if subtitle else title, ellipsize=True), True, True, 0)
            b.add(row)
            b.connect("clicked", lambda _, n=name: self.pick(n))
            self.list.pack_start(b, False, False, 0)
        self.list.show_all()

    def toggle_list(self):
        opening = not self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(opening)
        self.chevron.set_text(ICON["down" if opening else "right"])

    def pick(self, name):
        run("pactl", f"set-default-{self.kind}", name)
        self.show_device()
        self.toggle_list()
        self.refresh()
        if self.on_pick:
            self.on_pick(name)

    def refresh(self):
        target = f"@DEFAULT_{self.kind.upper()}@"
        m = re.search(r"(\d+)%", run("pactl", f"get-{self.kind}-volume", target))
        muted = run("pactl", f"get-{self.kind}-mute", target).endswith("yes")
        self.pill.set(int(m.group(1)) if m else 0, self.icons[muted], muted)


def nm_fields(line):
    """Splits a `nmcli -t` line: fields are ':'-separated, '\\:' is a colon."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur, esc = cur + ch, False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


class NetworkRow(Gtk.Box):
    """Current connection; with a Wi-Fi card, a list of networks to join.

    Desktops with only a cable just show the connection."""

    def __init__(self, open_list=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.pack_start(label("NETWORK", ["heading"]), False, False, 0)
        devices = [nm_fields(l) for l in run("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device").splitlines()]
        self.has_wifi = any(d[0] == "wifi" for d in devices)

        card = Gtk.Button()
        card.get_style_context().add_class("device")
        row = Gtk.Box(spacing=10)
        self.icon = label(css=["icon"], xalign=0.5, width=2)
        row.pack_start(self.icon, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title = label(css=["device-title"], ellipsize=True)
        self.subtitle = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.title, False, False, 0)
        names.pack_start(self.subtitle, False, False, 0)
        row.pack_start(names, True, True, 0)
        card.add(row)
        self.pack_start(card, False, False, 0)

        if self.has_wifi:
            self.chevron = label(ICON["right"], ["icon", "muted"], xalign=1.0)
            row.pack_end(self.chevron, False, False, 0)
            card.connect("clicked", lambda _: self.toggle_list())
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            toggle = Gtk.Box(spacing=10, margin_top=4)
            toggle.pack_start(label("Wi-Fi", ["muted"]), True, True, 0)
            self.switch = Gtk.Switch(active=run("nmcli", "radio", "wifi") == "enabled")
            self.switch.connect("notify::active", lambda s, _: self.set_radio(s.get_active()))
            toggle.pack_end(self.switch, False, False, 0)
            body.pack_start(toggle, False, False, 0)
            self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            body.pack_start(self.list, False, False, 0)
            # Password for a new protected network, shown when needed
            self.ask = Gtk.Box(spacing=6)
            self.password = Gtk.Entry(visibility=False, placeholder_text="Password", hexpand=True)
            self.password.connect("activate", lambda _: self.join(self.asking, self.password.get_text()))
            go = Gtk.Button(label="Join")
            go.get_style_context().add_class("yes")
            go.connect("clicked", lambda _: self.join(self.asking, self.password.get_text()))
            self.ask.pack_start(self.password, True, True, 0)
            self.ask.pack_start(go, False, False, 0)
            self.ask.set_no_show_all(True)
            body.pack_start(self.ask, False, False, 0)
            self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                         transition_duration=200)
            self.revealer.add(body)
            self.pack_start(self.revealer, False, False, 0)
        self.asking = None
        self.show_status()
        if open_list and self.has_wifi:
            GLib.idle_add(lambda: self.toggle_list() or False)

    def show_status(self):
        devices = [nm_fields(l) for l in run("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device").splitlines()]
        up = [d for d in devices if len(d) == 3 and d[1] == "connected" and d[0] in ("ethernet", "wifi")]
        if not up:
            self.icon.set_text(ICON["offline"])
            self.title.set_text("Disconnected")
            self.subtitle.set_text("Wi-Fi off" if self.has_wifi and run("nmcli", "radio", "wifi") != "enabled" else "")
        elif up[0][0] == "wifi":
            self.icon.set_text(ICON["wifi"])
            self.title.set_text(up[0][2])
            self.subtitle.set_text("Wi-Fi")
        else:
            self.icon.set_text(ICON["ethernet"])
            self.title.set_text("Wired")
            self.subtitle.set_text(up[0][2])

    def toggle_list(self):
        opening = not self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(opening)
        self.chevron.set_text(ICON["down" if opening else "right"])
        if opening:
            self.scan()

    def set_radio(self, on):
        run("nmcli", "radio", "wifi", "on" if on else "off")
        self.show_status()
        self.scan()

    def scan(self):
        for c in self.list.get_children():
            self.list.remove(c)
        if run("nmcli", "radio", "wifi") != "enabled":
            self.list.show_all()
            return
        self.list.pack_start(label("Searching…", ["muted", "small"]), False, False, 4)
        self.list.show_all()
        threading.Thread(target=self.scan_worker, daemon=True).start()

    def scan_worker(self):
        lines = run("nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list").splitlines()
        known = {f[0] for f in map(nm_fields, run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show").splitlines())
                 if len(f) > 1 and f[1] == "802-11-wireless"}
        nets = {}
        for f in map(nm_fields, lines):
            if len(f) < 4 or not f[1]:
                continue
            in_use, ssid, signal, security = f[0] == "*", f[1], int(f[2] or 0), f[3]
            if ssid not in nets or in_use or signal > nets[ssid][1]:
                nets[ssid] = (in_use or nets.get(ssid, (False,))[0], signal, security not in ("", "--"))
        found = sorted(nets.items(), key=lambda n: (not n[1][0], -n[1][1]))[:8]
        GLib.idle_add(self.show_networks, found, known)

    def show_networks(self, found, known):
        for c in self.list.get_children():
            self.list.remove(c)
        if not found:
            self.list.pack_start(label("No networks found", ["muted", "small"]), False, False, 4)
        for ssid, (in_use, signal, secured) in found:
            b = Gtk.Button()
            row = Gtk.Box(spacing=10)
            row.pack_start(label(ICON["check"] if in_use else "", ["icon"], xalign=0.5, width=2), False, False, 0)
            row.pack_start(label(ssid, ellipsize=True), True, True, 0)
            row.pack_end(label(f"{signal}%", ["muted", "small"]), False, False, 0)
            if secured:
                row.pack_end(label(ICON["lock"], ["icon", "muted"]), False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _, s=ssid, sec=secured: self.pick(s, sec, s in known))
            self.list.pack_start(b, False, False, 0)
        self.list.show_all()
        return False

    def pick(self, ssid, secured, known):
        if known or not secured:
            self.join(ssid, None)
            return
        self.asking = ssid
        self.password.set_text("")
        self.password.set_placeholder_text(f"Password for {ssid}")
        self.ask.set_no_show_all(False)  # hidden when the menu opened
        self.ask.show_all()
        self.password.grab_focus()

    def join(self, ssid, password):
        if not ssid:
            return
        self.ask.hide()
        self.subtitle.set_text(f"Connecting to {ssid}…")

        def work():
            known = any(nm_fields(l)[0] == ssid for l in run("nmcli", "-t", "-f", "NAME", "connection", "show").splitlines())
            if known and not password:
                run("nmcli", "connection", "up", "id", ssid)
            elif password:
                run("nmcli", "device", "wifi", "connect", ssid, "password", password)
            else:
                run("nmcli", "device", "wifi", "connect", ssid)
            GLib.idle_add(lambda: (self.show_status(), self.scan(), False)[2])

        threading.Thread(target=work, daemon=True).start()


UPDATES = os.path.expanduser("~/.config/waybar/updates.py")


class Updates(Gtk.Box):
    """Pending updates (updates.py): a new release first, then the packages,
    and the choice to update now in a terminal."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_size_request(340, -1)
        try:
            data = json.loads(run(UPDATES, "list") or "{}")
        except json.JSONDecodeError:
            data = {}
        packages, release = data.get("packages", []), data.get("release")
        self.pack_start(label("UPDATES", ["heading"]), False, False, 0)

        if release:
            card = Gtk.Box(spacing=10)
            card.get_style_context().add_class("notif")
            card.pack_start(label(ICON["upgrade"], ["icon"], xalign=0.5, width=2), False, False, 0)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            names.pack_start(label(f"Fedora {release} is available", ["title"]), False, False, 0)
            names.pack_start(label("Upgrade the whole system, then reboot", ["muted", "small"]), False, False, 0)
            card.pack_start(names, True, True, 0)
            up = Gtk.Button(label="Upgrade")
            up.get_style_context().add_class("yes")
            up.set_valign(Gtk.Align.CENTER)
            up.connect("clicked", lambda _: self.start("release"))
            card.pack_end(up, False, False, 0)
            self.pack_start(card, False, False, 0)

        if packages:
            self.pack_start(label(f"{len(packages)} package{'s' if len(packages) != 1 else ''} to update",
                                  ["muted", "small"]), False, False, 0)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(min(240, 26 * len(packages)))
            scroll.set_max_content_height(240)
            rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for p in packages:
                row = Gtk.Box(spacing=12)
                row.pack_start(label(p["name"], ellipsize=True), True, True, 0)
                row.pack_end(label(p["version"], ["muted", "small"], xalign=1.0), False, False, 0)
                rows.pack_start(row, False, False, 2)
            scroll.add(rows)
            self.pack_start(scroll, False, False, 0)
        elif not release:
            self.pack_start(label("Everything is up to date", ["muted"]), False, False, 0)

        buttons = Gtk.Box(spacing=8, homogeneous=True)
        later = Gtk.Button(label="Not now")
        later.connect("clicked", lambda _: self.close_panel())
        buttons.pack_start(later, True, True, 0)
        if packages:
            now = Gtk.Button(label="Update now")
            now.get_style_context().add_class("yes")
            now.connect("clicked", lambda _: self.start("packages"))
            buttons.pack_start(now, True, True, 0)
        self.pack_start(buttons, False, False, 0)

    def close_panel(self):
        top = self.get_toplevel()
        top.close() if hasattr(top, "revealer") else Gtk.main_quit()

    def start(self, kind):
        spawn(UPDATES, "run", kind)
        self.close_panel()


class Network(Gtk.Box):
    """Network popup from the bar's network icon: Wi-Fi list already open."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(320, -1)
        self.pack_start(NetworkRow(open_list=True), False, False, 0)


TEST_SOUND = "/usr/share/sounds/freedesktop/stereo/audio-test-signal.oga"


class Sound(Gtk.Box):
    """Sound page of the general menu (also opened by the speaker and mic on
    the bar): devices and volumes, a live meter of the microphone, its
    hardware gains, the apps recording, and buttons that fix the usual
    problems. The meter only listens while the page is on screen."""

    def __init__(self, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.set_size_request(320, -1)
        self.on_back = on_back
        self.meter_proc = None
        self.active = False
        self.build()
        GLib.timeout_add_seconds(2, self.refresh_apps)
        self.connect("destroy", lambda _: self.stop_meter())

    def build(self):
        for c in self.get_children():
            self.remove(c)
        # Titled like the other sections, with a way back to the menu;
        # closer to the first section than the sections are to each other
        first = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        first.pack_start(page_title("SOUND", self.on_back), False, False, 0)
        self.pack_start(first, False, False, 0)
        test = Gtk.Button(label="Test")
        test.get_style_context().add_class("small")
        test.connect("clicked", lambda _: spawn("paplay", TEST_SOUND))
        first.pack_start(AudioRow("sink", "OUTPUT", "volume", "muted", action=test), False, False, 0)

        self.input = AudioRow("source", "INPUT", "mic", "mic-off", on_pick=lambda _: self.build())
        self.meter = Gtk.LevelBar(min_value=0, max_value=1)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.meter.remove_offset_value(offset)
        self.input.pack_start(self.meter, False, False, 0)
        # One line whatever it says, so the page keeps its height
        self.signal = label(css=["muted", "small"], ellipsize=True)
        self.input.pack_start(self.signal, False, False, 0)
        self.pack_start(self.input, False, False, 0)

        # The device's own capture volumes, under PipeWire's: one stuck at 0%
        # silences the microphone whatever the input volume says
        source = audio.find(audio.real_sources(), run("pactl", "get-default-source"))
        props = source["properties"] if source else {}
        controls = audio.capture_controls(props["alsa.card"]) if "alsa.card" in props else []
        if controls:
            gains = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            gains.pack_start(label("HARDWARE GAIN", ["heading"]), False, False, 0)
            for c in controls:
                gains.pack_start(self.gain_row(props, c), False, False, 0)
            self.pack_start(gains, False, False, 0)

        apps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        apps.pack_start(label("RECORDING", ["heading"]), False, False, 0)
        self.apps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        apps.pack_start(self.apps, False, False, 0)
        self.pack_start(apps, False, False, 0)
        self.apps_seen = None
        self.refresh_apps()

        fixes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.result = label(css=["small"])
        self.result.set_line_wrap(True)
        self.result.set_no_show_all(True)
        fixes.pack_start(self.result, False, False, 0)
        buttons = Gtk.Box(spacing=8, homogeneous=True)
        restart = Gtk.Button(label="Restart audio")
        restart.connect("clicked", lambda _: self.restart())
        buttons.pack_start(restart, True, True, 0)
        fix = Gtk.Button(label="Fix microphone")
        fix.get_style_context().add_class("yes")
        fix.connect("clicked", lambda _: self.fix())
        buttons.pack_start(fix, True, True, 0)
        fixes.pack_start(buttons, False, False, 0)
        self.pack_start(fixes, False, False, 0)
        self.show_all()
        self.source = source
        if self.active:
            self.start_meter(source)

    def activate(self):
        self.active = True
        self.start_meter(self.source)

    def deactivate(self):
        self.active = False
        self.stop_meter()

    def gain_row(self, props, c):
        row = Gtk.Box(spacing=10)
        name = c["name"] if c["index"] == 0 and not any(
            o != c and o["name"] == c["name"] for o in audio.capture_controls(props["alsa.card"])) \
            else f"{c['name']} {c['index']}"
        row.pack_start(label(name, width=8, ellipsize=True), False, False, 0)
        value = label(f"{c['percent']}%", ["muted", "small"], xalign=1.0, width=4)

        def change(v):
            audio.set_gain(props["alsa.card"], c["name"], c["index"], v)
            audio.save_gain(audio.device_key(props), f"{c['name']},{c['index']}", int(v))
            value.set_text(f"{int(v)}%")

        slider = hslider(0, 100, change)
        slider.set_value(c["percent"])
        row.pack_start(slider, True, True, 0)
        row.pack_end(value, False, False, 0)
        return row

    # -------------------------------------------------------- level meter

    def start_meter(self, source):
        self.stop_meter()
        if not source:
            self.signal.set_text("No microphone found: is it plugged in?")
            return
        if source["mute"]:
            self.signal.set_text("Muted: click the mic icon above")
        else:
            self.signal.set_text("Listening…")
        self.meter_proc = proc = audio.level_stream(source["name"])
        threading.Thread(target=self.listen, args=(proc, source["mute"]), daemon=True).start()

    def stop_meter(self):
        if self.meter_proc:
            self.meter_proc.kill()
            self.meter_proc = None

    def listen(self, proc, muted):
        level, started, heard = 0.0, time.monotonic(), False
        while True:
            chunk = proc.stdout.read(400)  # 25 ms
            if not chunk or proc is not self.meter_proc:
                return
            p = audio.peak(chunk)
            heard = heard or p > 0
            level = max(audio.dbfs(p), level * 0.85)
            silent = not heard and time.monotonic() - started > 1.5
            GLib.idle_add(self.show_level, level, silent, muted)

    def show_level(self, level, silent, muted):
        self.meter.set_value(level)
        if muted:
            return False
        if silent:
            text = "Nothing yet: speak, or check mute and gain"
        else:
            text = "Sound is coming in"
        if self.signal.get_text() != text:
            self.signal.set_text(text)
        return False

    # ------------------------------------------------------- apps + fixes

    def refresh_apps(self):
        sources = audio.real_sources()
        default = audio.find(sources, run("pactl", "get-default-source"))
        names = {s["index"]: s["properties"].get("device.nick", s["description"]) for s in sources}
        apps = [(i, app, src) for i, app, src in audio.recording(sources)]
        seen = [(app, src) for _, app, src in apps]
        if seen == self.apps_seen:
            return True
        self.apps_seen = seen
        for c in self.apps.get_children():
            self.apps.remove(c)
        if not apps:
            self.apps.pack_start(label("No app is using the microphone", ["muted"]), False, False, 0)
        for index, app, src in apps:
            row = Gtk.Box(spacing=10)
            row.pack_start(label(app, ellipsize=True), True, True, 0)
            row.pack_end(label(names.get(src, "?"), ["muted", "small"], xalign=1.0), False, False, 0)
            if default and src != default["index"]:
                move = Gtk.Button(label="Use this mic")
                move.get_style_context().add_class("small")
                move.connect("clicked", lambda _, i=index, d=default["name"]: run(
                    "pactl", "move-source-output", str(i), d) or self.refresh_apps())
                row.pack_end(move, False, False, 0)
            self.apps.pack_start(row, False, False, 0)
        self.apps.show_all()
        return True

    def report(self, lines):
        self.build()
        self.result.set_text("\n".join(lines))
        self.result.show()

    def fix(self):
        self.report(audio.fix())

    def restart(self):
        self.stop_meter()
        self.signal.set_text("Restarting the sound server…")

        def work():
            subprocess.run(["systemctl", "--user", "restart", "wireplumber", "pipewire", "pipewire-pulse"])
            time.sleep(2)  # devices show up again
            audio.restore_gains()
            GLib.idle_add(lambda: self.report(["Sound server restarted"]) or False)

        threading.Thread(target=work, daemon=True).start()


class Arrangement(Gtk.DrawingArea):
    """The displays as they sit side by side, to scale; clicking one picks it."""

    WIDTH, MAX_HEIGHT, GAP = 288, 110, 4

    def __init__(self, items, main, selected, on_select):
        super().__init__()
        self.items, self.main, self.selected, self.on_select = items, main, selected, on_select
        x0 = min(o["rect"]["x"] for o in items)
        y0 = min(o["rect"]["y"] for o in items)
        w = max(o["rect"]["x"] + o["rect"]["width"] for o in items) - x0
        h = max(o["rect"]["y"] + o["rect"]["height"] for o in items) - y0
        self.k = min(self.WIDTH / w, self.MAX_HEIGHT / h)
        self.dx = (self.WIDTH - w * self.k) / 2
        self.origin = (x0, y0)
        self.set_size_request(self.WIDTH, int(h * self.k))
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self.draw)
        self.connect("button-press-event", self.click)

    def box(self, o):
        r = o["rect"]
        return (self.dx + (r["x"] - self.origin[0]) * self.k + self.GAP / 2,
                (r["y"] - self.origin[1]) * self.k + self.GAP / 2,
                r["width"] * self.k - self.GAP, r["height"] * self.k - self.GAP)

    def color(self, name):
        found, c = self.get_style_context().lookup_color(name)
        return (c.red, c.green, c.blue) if found else (0.5, 0.5, 0.5)

    def draw(self, _w, cr):
        for o in self.items:
            x, y, w, h = self.box(o)
            chosen = o["id"] == self.selected
            r = min(6, w / 4, h / 4)
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -1.5708, 0)
            cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
            cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
            cr.arc(x + r, y + r, r, 3.1416, 4.7124)
            cr.close_path()
            cr.set_source_rgb(*self.color("line" if chosen else "bg2"))
            cr.fill_preserve()
            cr.set_source_rgb(*self.color("accent" if chosen else "faint"))
            cr.set_line_width(1.5 if chosen else 1)
            cr.stroke()
            text = o["name"] + ("\nMain" if o["id"] == self.main and len(self.items) > 1 else "")
            layout = self.create_pango_layout(text)
            layout.set_alignment(Pango.Alignment.CENTER)
            layout.set_width(int(max(1, w - 8) * Pango.SCALE))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            th = layout.get_pixel_size()[1]
            cr.move_to(x + 4, y + (h - th) / 2)
            cr.set_source_rgb(*self.color("hi" if chosen else "mute"))
            PangoCairo.show_layout(cr, layout)
        return False

    def click(self, _w, e):
        for o in self.items:
            x, y, w, h = self.box(o)
            if x <= e.x <= x + w and y <= e.y <= y + h:
                self.on_select(o["id"])
        return True


class Displays(Gtk.Box):
    """Displays page of the general menu: the arrangement (click a display to
    pick it), which one is the main display, and the resolution and scale of
    each. Saved for the next login by displays.py."""

    def __init__(self, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.set_size_request(320, -1)
        self.on_back = on_back
        self.selected = None
        self.build()

    def build(self):
        for c in self.get_children():
            self.remove(c)
        items = displays.outputs()
        first = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        first.pack_start(page_title("DISPLAYS", self.on_back), False, False, 0)
        self.pack_start(first, False, False, 0)
        if not items:
            first.pack_start(label("No display found", ["muted"]), False, False, 0)
            self.show_all()
            return
        main = displays.primary(items)
        if not any(o["id"] == self.selected for o in items):
            self.selected = main
        o = next(o for o in items if o["id"] == self.selected)
        many = len(items) > 1

        first.pack_start(Arrangement(items, main, self.selected, self.pick), False, False, 0)
        if many:
            order = [x["id"] for x in sorted(items, key=lambda x: x["rect"]["x"])]
            i = order.index(o["id"])
            moves = Gtk.Box(spacing=8, homogeneous=True)
            for step, text in ((-1, "Move left"), (1, "Move right")):
                b = icon_button("left" if step < 0 else "right", text, css=["small"],
                                on_click=lambda s=step: self.act(displays.move, o["id"], s))
                b.get_child().set_halign(Gtk.Align.CENTER)
                if step > 0:  # arrow after the text
                    b.get_child().reorder_child(b.get_child().get_children()[0], -1)
                b.set_sensitive(0 <= i + step < len(order))
                moves.pack_start(b, True, True, 0)
            first.pack_start(moves, False, False, 0)

        # The picked display: its name, and the main display switch
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        section.pack_start(label("DISPLAY", ["heading"]), False, False, 0)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("notif")
        card.pack_start(label(displays.title(o), ["device-title"], ellipsize=True), False, False, 0)
        card.pack_start(label(f"{o['name']} · {displays.mode_text(o['current_mode'])}",
                              ["muted", "small"], ellipsize=True), False, False, 0)
        section.pack_start(card, False, False, 0)
        if many:
            row = Gtk.Box(spacing=10, margin_top=4)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            names.pack_start(label("Main display"), False, False, 0)
            names.pack_start(label("Workspace 1 and the focus at login", ["muted", "small"]), False, False, 0)
            row.pack_start(names, True, True, 0)
            switch = Gtk.Switch(active=o["id"] == main, valign=Gtk.Align.CENTER)
            # There is always one: turn another one on to change it
            switch.set_sensitive(o["id"] != main)
            switch.connect("notify::active", lambda s, _: s.get_active() and self.act(displays.set_primary, o["id"]))
            row.pack_end(switch, False, False, 0)
            section.pack_start(row, False, False, 0)
        self.pack_start(section, False, False, 0)

        self.pack_start(self.resolution(o), False, False, 0)

        scale = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box()
        top.pack_start(label("SCALE", ["heading"]), True, True, 0)
        top.pack_end(label(f"Looks like {o['rect']['width']}×{o['rect']['height']}",
                           ["muted", "small"], xalign=1.0), False, False, 0)
        scale.pack_start(top, False, False, 0)
        choices = Gtk.Box(spacing=4, homogeneous=True)
        for s in displays.SCALES:
            b = Gtk.Button(label=f"{int(s * 100)}%")
            b.get_style_context().add_class("choice")
            if abs(o["scale"] - s) < 0.01:
                b.get_style_context().add_class("yes")
            b.connect("clicked", lambda _, s=s: self.act(displays.set_scale, o["id"], s))
            choices.pack_start(b, True, True, 0)
        scale.pack_start(choices, False, False, 0)
        self.pack_start(scale, False, False, 0)

        # Rotation and free placement are in wdisplays; `displays.py save` keeps them
        advanced = Gtk.Button(label="More settings…")
        advanced.connect("clicked", lambda _: self.advanced())
        self.pack_start(advanced, False, False, 0)
        self.show_all()

    def resolution(self, o):
        """Current mode; clicking opens the list of modes below it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(label("RESOLUTION", ["heading"]), False, False, 0)
        picker = Gtk.Button()
        picker.get_style_context().add_class("device")
        row = Gtk.Box(spacing=8)
        row.pack_start(label(displays.mode_text(o["current_mode"]), ["device-title"]), True, True, 0)
        chevron = label(ICON["right"], ["icon", "muted"], xalign=1.0)
        row.pack_end(chevron, False, False, 0)
        picker.add(row)
        box.pack_start(picker, False, False, 0)

        cur = o["current_mode"]
        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for m in displays.modes(o):
            b = Gtk.Button()
            line = Gtk.Box(spacing=10)
            same = (m["width"], m["height"], m["refresh"]) == (cur["width"], cur["height"], cur["refresh"])
            line.pack_start(label(ICON["check"] if same else "", ["icon"], xalign=0.5, width=2), False, False, 0)
            line.pack_start(label(displays.mode_text(m)), True, True, 0)
            b.add(line)
            b.connect("clicked", lambda _, m=m: self.act(displays.set_mode, o["id"], m))
            items.pack_start(b, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(200)
        scroll.add(items)
        revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                transition_duration=200)
        revealer.add(scroll)
        box.pack_start(revealer, False, False, 0)

        def toggle():
            opening = not revealer.get_reveal_child()
            revealer.set_reveal_child(opening)
            chevron.set_text(ICON["down" if opening else "right"])
        picker.connect("clicked", lambda _: toggle())
        return box

    def pick(self, ident):
        if ident != self.selected:
            self.selected = ident
            self.build()

    def act(self, fn, *args):
        fn(*args)
        # Rebuilt once sway has settled the new layout
        GLib.idle_add(lambda: self.build() or False)

    def advanced(self):
        spawn("wdisplays")
        top = self.get_toplevel()
        top.close() if hasattr(top, "revealer") else Gtk.main_quit()


# Font Awesome glyph for each BlueZ device icon
BT_ICON = {
    "audio-headset": "headphones", "audio-headphones": "headphones", "audio-card": "volume",
    "input-mouse": "mouse", "input-keyboard": "keyboard", "input-gaming": "gamepad",
    "phone": "phone", "computer": "laptop",
}


def bt_reason(err):
    """BlueZ's error, in words."""
    low = err.lower()
    if "page-timeout" in low or "page timeout" in low or "host is down" in low or "timeout" in low:
        return "it is off or out of reach"
    if "profile-unavailable" in low:
        return "no sound profile for it (restart audio on the Sound page)"
    if "authentication" in low or "rejected" in low or "canceled" in low:
        return "pairing was refused or cancelled"
    return err


class Bluetooth(Gtk.Box):
    """Bluetooth page of the general menu: turn it on and off, connect the
    paired devices (with their battery), and pair new ones nearby. Searches
    for devices, and answers pairing requests, only while the page is on
    screen."""

    def __init__(self, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.set_size_request(320, -1)
        self.on_back = on_back
        self.active = False
        self.agent = None
        self.busy = {}  # device path: "Connecting…"
        self.forgetting = None
        self.queued = False

        first = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        first.pack_start(page_title("BLUETOOTH", on_back), False, False, 0)
        toggle = Gtk.Box(spacing=10)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        names.pack_start(label("Bluetooth"), False, False, 0)
        self.visible_as = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.visible_as, False, False, 0)
        toggle.pack_start(names, True, True, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", lambda s, _: self.set_power(s.get_active()))
        toggle.pack_end(self.switch, False, False, 0)
        first.pack_start(toggle, False, False, 0)
        # A pairing code to check or type, when a device asks
        self.prompt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.prompt.get_style_context().add_class("notif")
        self.prompt.set_no_show_all(True)
        first.pack_start(self.prompt, False, False, 0)
        self.pack_start(first, False, False, 0)

        mine = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mine.pack_start(label("MY DEVICES", ["heading"]), False, False, 0)
        self.paired = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        mine.pack_start(self.paired, False, False, 0)
        self.pack_start(mine, False, False, 0)

        self.nearby_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box()
        top.pack_start(label("OTHER DEVICES", ["heading"]), True, True, 0)
        self.searching = label(css=["muted", "small"], xalign=1.0)
        top.pack_end(self.searching, False, False, 0)
        self.nearby_box.pack_start(top, False, False, 0)
        self.nearby = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.nearby_box.pack_start(self.nearby, False, False, 0)
        self.nearby_box.set_no_show_all(True)  # only while Bluetooth is on
        self.pack_start(self.nearby_box, False, False, 0)

        self.message = label(css=["small"])
        self.message.set_line_wrap(True)
        self.message.set_no_show_all(True)
        self.pack_start(self.message, False, False, 0)

        bluetooth.watch(self.changed)
        self.connect("destroy", lambda _: self.deactivate())
        self.refresh()

    # ------------------------------------------------------------ on screen

    def activate(self):
        self.active = True
        self.agent = self.agent or bluetooth.Agent(self.ask)
        self.refresh()
        bluetooth.discover(True)

    def deactivate(self):
        if not self.active:
            return
        self.active = False
        bluetooth.discover(False)
        if self.agent:
            self.agent.close()
            self.agent = None

    def changed(self):
        # Many signals come at once (and RSSI keeps changing while searching)
        if not self.queued:
            self.queued = True
            GLib.timeout_add(300, self.refresh)

    # --------------------------------------------------------------- lists

    def refresh(self):
        self.queued = False
        _, adapter = bluetooth.adapter()
        on = bool(adapter.get("Powered"))
        with self.switch.handler_block(self.switch_handler):
            self.switch.set_active(on)
        self.switch.set_sensitive(bool(adapter))
        self.visible_as.set_text(f"Visible as {adapter.get('Alias', '')}" if on else
                                 "Off" if adapter else "No adapter found")
        devices = bluetooth.devices() if on else []
        for box in (self.paired, self.nearby):
            for c in box.get_children():
                box.remove(c)

        paired = sorted((d for d in devices if d["paired"]), key=lambda d: (not d["connected"], d["name"].lower()))
        if not on:
            self.paired.pack_start(label("Bluetooth is off", ["muted"]), False, False, 0)
        elif not paired:
            self.paired.pack_start(label("No paired devices yet", ["muted"]), False, False, 0)
        for d in paired:
            self.paired.pack_start(self.device_row(d), False, False, 0)

        # Only devices with a name: the rest are beacons and the like
        nearby = sorted((d for d in devices if not d["paired"] and d["named"]),
                        key=lambda d: -(d["rssi"] if d["rssi"] is not None else -999))[:8]
        self.nearby_box.set_no_show_all(not on)
        self.nearby_box.show_all() if on else self.nearby_box.hide()
        self.searching.set_text("Searching…" if adapter.get("Discovering") else "")
        if on and not nearby:
            self.nearby.pack_start(label("Put the device in pairing mode", ["muted"]), False, False, 0)
        for d in nearby:
            self.nearby.pack_start(self.device_row(d), False, False, 0)
        self.paired.show_all()
        self.nearby.show_all()
        return False

    def device_row(self, d):
        row = Gtk.Box(spacing=4)
        b = Gtk.Button()
        b.get_style_context().add_class("device")
        inner = Gtk.Box(spacing=10)
        inner.pack_start(label(ICON[BT_ICON.get(d["icon"], "bluetooth")], ["icon"], xalign=0.5, width=2),
                         False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        names.pack_start(label(d["name"], ["device-title"] if d["connected"] else [], ellipsize=True),
                         False, False, 0)
        if d["path"] in self.busy:
            status = self.busy[d["path"]]
        elif d["connected"]:
            status = "Connected" + (f" · {d['battery']}% battery" if d["battery"] is not None else "")
        else:
            status = "Not connected" if d["paired"] else "Click to pair"
        names.pack_start(label(status, ["muted", "small"], ellipsize=True), False, False, 0)
        inner.pack_start(names, True, True, 0)
        b.add(inner)
        b.set_sensitive(d["path"] not in self.busy)
        b.connect("clicked", lambda _: self.use(d))
        row.pack_start(b, True, True, 0)
        if d["paired"]:
            # Asks once more before forgetting it
            sure = self.forgetting == d["path"]
            forget = Gtk.Button(label="Forget?") if sure else icon_button("trash", css=["small"])
            forget.get_style_context().add_class("small")
            forget.set_valign(Gtk.Align.CENTER)
            forget.connect("clicked", lambda _: self.forget(d, sure))
            row.pack_end(forget, False, False, 0)
        return row

    # ------------------------------------------------------------- actions

    def set_power(self, on):
        bluetooth.set_powered(on)
        if on and self.active:
            bluetooth.discover(True)
        self.refresh()

    def use(self, d):
        path, name = d["path"], d["name"]
        self.forgetting = None
        self.say("")
        if d["connected"]:
            self.busy[path] = "Disconnecting…"
            bluetooth.disconnect(path, lambda err: self.done(path, name, err, "disconnect from"))
        elif d["paired"]:
            self.busy[path] = "Connecting…"
            bluetooth.connect(path, lambda err: self.done(path, name, err, "connect to"))
        else:
            self.busy[path] = "Pairing…"
            bluetooth.pair(path, lambda err: self.done(path, name, err, "pair with"))
        self.refresh()

    def done(self, path, name, err, verb):
        self.busy.pop(path, None)
        self.hide_prompt()
        if err:
            self.say(f"Couldn't {verb} {name}: {bt_reason(err)}")
        self.refresh()

    def forget(self, d, sure):
        self.forgetting = None if sure else d["path"]
        if sure:
            bluetooth.forget(d["path"])
        self.refresh()

    def say(self, text):
        self.message.set_text(text)
        self.message.set_visible(bool(text))

    # ------------------------------------------------------------- pairing

    def ask(self, kind, name, code, reply):
        self.hide_prompt()
        if not kind:
            return
        if kind == "show":
            self.prompt.pack_start(label(f"Type {code} on {name}, then Enter", ["title"]), False, False, 0)
        else:
            self.prompt.pack_start(label(f"Pair with {name}?", ["title"], ellipsize=True), False, False, 0)
            if code:
                self.prompt.pack_start(label(f"Check that {name} shows {code}", ["muted", "small"]),
                                       False, False, 0)
            buttons = Gtk.Box(spacing=8, homogeneous=True)
            for text, ok in (("Cancel", False), ("Pair", True)):
                b = Gtk.Button(label=text)
                if ok:
                    b.get_style_context().add_class("yes")
                b.connect("clicked", lambda _, ok=ok: (reply(ok), self.hide_prompt()))
                buttons.pack_start(b, True, True, 0)
            self.prompt.pack_start(buttons, False, False, 0)
        self.prompt.set_no_show_all(False)
        self.prompt.show_all()

    def hide_prompt(self):
        for c in self.prompt.get_children():
            self.prompt.remove(c)
        self.prompt.hide()


HAS_BLUETOOTH = os.path.isdir("/sys/class/bluetooth") and bool(os.listdir("/sys/class/bluetooth"))


class Menu(Gtk.Box):
    # (icon, tile label, confirmation, command)
    POWER = [
        ("lock", "Lock", "Lock", ["lock"]),
        ("logout", "Log out", "Log out", ["swaymsg", "exit"]),
        ("reboot", "Reboot", "Reboot", ["systemctl", "reboot"]),
        ("power", "Off", "Power off", ["systemctl", "poweroff"]),
    ]

    def __init__(self, page="main"):
        super().__init__()
        # The main page, and sub pages (Sound, Displays, Bluetooth) that slide in from the right
        self.pages = Gtk.Stack(vhomogeneous=False, hhomogeneous=False, transition_duration=200)
        self.add(self.pages)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main.set_size_request(320, -1)
        self.pages.add_named(main, "main")
        self.sound = Sound(on_back=lambda: self.show_page("main"))
        self.pages.add_named(self.sound, "sound")
        self.displays = Displays(on_back=lambda: self.show_page("main"))
        self.pages.add_named(self.displays, "displays")
        self.bluetooth = None
        if HAS_BLUETOOTH:
            self.bluetooth = Bluetooth(on_back=lambda: self.show_page("main"))
            self.pages.add_named(self.bluetooth, "bluetooth")

        main.pack_start(NetworkRow(), False, False, 0)

        # Power buttons, swapped for a confirmation when one is picked
        # Not homogeneous, so the panel shrinks to the confirmation
        self.stack = Gtk.Stack(vhomogeneous=False, interpolate_size=True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        # Settings apps; Bluetooth only where there is an adapter
        buttons.pack_start(label("SETTINGS", ["heading"]), False, False, 4)
        sound = icon_button("headphones", "Sound", lambda: self.show_page("sound"))
        sound.get_child().pack_end(label(ICON["right"], ["icon", "muted"], xalign=1.0), True, True, 0)
        buttons.pack_start(sound, False, False, 0)
        screens = icon_button("display", "Displays", lambda: self.show_page("displays"))
        screens.get_child().pack_end(label(ICON["right"], ["icon", "muted"], xalign=1.0), True, True, 0)
        buttons.pack_start(screens, False, False, 0)
        buttons.pack_start(icon_button("image", "Wallpaper", lambda: self.run_and_quit([PANEL, "wallpaper"])),
                           False, False, 0)
        if self.bluetooth:
            bt = icon_button("bluetooth", "Bluetooth", lambda: self.show_page("bluetooth"))
            bt.get_child().pack_end(label(ICON["right"], ["icon", "muted"], xalign=1.0), True, True, 0)
            buttons.pack_start(bt, False, False, 0)
        buttons.pack_start(label("SYSTEM", ["heading"]), False, False, 4)
        buttons.pack_start(icon_button("keyboard", "Keybindings", lambda: self.run_and_quit(
            [os.path.expanduser("~/.config/sway/keys.sh")])), False, False, 0)

        # "Power" opens a row of tiles below it
        power = icon_button("power", "Power", self.toggle_power)
        self.chevron = label(ICON["right"], ["icon", "muted"], xalign=1.0)
        power.get_child().pack_end(self.chevron, True, True, 0)
        buttons.pack_start(power, False, False, 0)
        tiles = Gtk.Box(spacing=6, homogeneous=True, margin_top=6)
        for icon, text, question, cmd in self.POWER:
            tile = Gtk.Button()
            tile.get_style_context().add_class("tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            inner.pack_start(label(ICON[icon], ["icon"], xalign=0.5), False, False, 0)
            inner.pack_start(label(text, ["small"], xalign=0.5), False, False, 0)
            tile.add(inner)
            tile.connect("clicked", lambda _, q=question, c=cmd: self.confirm(q, c))
            tiles.pack_start(tile, True, True, 0)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=200)
        self.revealer.add(tiles)
        buttons.pack_start(self.revealer, False, False, 0)
        self.stack.add_named(buttons, "buttons")
        self.confirm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.stack.add_named(self.confirm_box, "confirm")
        main.pack_start(self.stack, False, False, 0)
        # Set it even for "main": the stack shows whichever page was shown first
        self.pages.show_all()
        self.show_page(page, animate=False)

    def show_page(self, page, animate=True):
        self.pages.set_transition_type(
            Gtk.StackTransitionType.NONE if not animate else
            Gtk.StackTransitionType.SLIDE_LEFT if page != "main" else Gtk.StackTransitionType.SLIDE_RIGHT)
        self.pages.set_visible_child_name(page)
        if page == "sound":
            self.sound.activate()
        else:
            self.sound.deactivate()
        if page == "displays" and animate:
            self.displays.build()  # changed elsewhere since the menu opened
        if self.bluetooth:
            (self.bluetooth.activate if page == "bluetooth" else self.bluetooth.deactivate)()

    def toggle_power(self):
        opening = not self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(opening)
        self.chevron.set_text(ICON["down" if opening else "right"])

    def confirm(self, text, cmd):
        for c in self.confirm_box.get_children():
            self.confirm_box.remove(c)
        self.confirm_box.pack_start(label(f"{text}?", ["title"], xalign=0.5), False, False, 8)
        row = Gtk.Box(spacing=8, homogeneous=True)
        no = Gtk.Button(label="No")
        no.connect("clicked", lambda _: self.stack.set_visible_child_name("buttons"))
        yes = Gtk.Button(label="Yes")
        yes.get_style_context().add_class("yes")
        yes.connect("clicked", lambda _: self.run_and_quit(cmd))
        row.pack_start(no, True, True, 0)
        row.pack_start(yes, True, True, 0)
        self.confirm_box.pack_start(row, False, False, 0)
        self.confirm_box.show_all()
        self.stack.set_visible_child_name("confirm")
        no.grab_focus()

    def run_and_quit(self, cmd):
        spawn(*cmd)
        top = self.get_toplevel()
        top.close() if hasattr(top, "revealer") else Gtk.main_quit()


# --------------------------------------------------------------- wallpaper

def quote(name):
    return '"' + name.replace('"', '\\"') + '"'


THUMB_W, THUMB_H = 144, 81
CELL_W, CELL_H = THUMB_W + 4, THUMB_H + 4  # with the border
COLUMNS = 4
LOCAL_PAGE = 12  # downloaded wallpapers per page


def cover(pix, w, h):
    """The picture scaled to fill w×h, cut around the middle."""
    k = max(w / pix.get_width(), h / pix.get_height())
    sw, sh = max(w, round(pix.get_width() * k)), max(h, round(pix.get_height() * k))
    scaled = pix.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
    return scaled.new_subpixbuf((sw - w) // 2, (sh - h) // 2, w, h)


def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def css(widget, *classes, on=True):
    ctx = widget.get_style_context()
    for c in classes:
        (ctx.add_class if on else ctx.remove_class)(c)
    return widget


class Chip(Gtk.DrawingArea):
    """A rounded patch of colors side by side."""

    def __init__(self, colors, w, h):
        super().__init__()
        self.colors = colors
        self.set_size_request(w, h)
        self.connect("draw", self.draw)

    def set_colors(self, colors):
        self.colors = colors
        self.queue_draw()

    def draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        rounded(cr, 0, 0, w, h, min(4, h / 2))
        cr.clip()
        step = w / max(1, len(self.colors))
        for i, c in enumerate(self.colors):
            cr.set_source_rgb(*wallpaper.rgb(c))
            cr.rectangle(i * step, 0, step + 1, h)
            cr.fill()
        return False


class Spinner(Gtk.DrawingArea):
    """A thin arc going round in the palette's colors (GTK's own spinner is
    the icon theme's); draws nothing when stopped, but keeps its room."""

    SIZE = 12

    def __init__(self):
        super().__init__()
        self.set_size_request(self.SIZE, self.SIZE)
        self.set_valign(Gtk.Align.CENTER)
        self.angle, self.timer = 0.0, None
        self.connect("draw", self.draw)
        self.connect("destroy", lambda _: self.stop())

    def start(self):
        if not self.timer:
            self.timer = GLib.timeout_add(16, self.turn)

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
            self.queue_draw()

    def turn(self):
        self.angle = (self.angle + 0.15) % 6.2832
        self.queue_draw()
        return True

    def draw(self, _w, cr):
        if not self.timer:
            return False
        c = self.SIZE / 2
        ctx = self.get_style_context()
        cr.set_line_width(1.5)
        for name, start, end in (("line", 0, 6.2832), ("accent", self.angle, self.angle + 1.8)):
            found, color = ctx.lookup_color(name)
            cr.set_source_rgb(*((color.red, color.green, color.blue) if found else (0.5, 0.5, 0.5)))
            cr.arc(c, c, c - 1, start, end)
            cr.stroke()
        return False


class Thumb(Gtk.Button):
    """A wallpaper in a grid; the picture loads in the background, and a
    check marks the one in use."""

    def __init__(self, source, on_click, current=False):
        super().__init__()
        css(self, "thumb")
        self.alive = True
        overlay = Gtk.Overlay()
        self.image = Gtk.Image()
        self.image.set_size_request(THUMB_W, THUMB_H)
        overlay.add(self.image)
        if current:
            mark = label(ICON["check"], ["icon", "mark"], xalign=0.5)
            mark.set_halign(Gtk.Align.END)
            mark.set_valign(Gtk.Align.END)
            overlay.add_overlay(mark)
        self.add(overlay)
        self.connect("clicked", lambda _: on_click())
        self.connect("destroy", lambda _: setattr(self, "alive", False))
        threading.Thread(target=self.load, args=(source,), daemon=True).start()

    def load(self, source):
        path = wallpaper.thumb(source)
        try:
            pix = cover(GdkPixbuf.Pixbuf.new_from_file(str(path)), THUMB_W, THUMB_H) if path else None
        except GLib.Error:
            pix = None
        GLib.idle_add(self.show_picture, pix)

    def show_picture(self, pix):
        if self.alive and pix:
            self.image.set_from_pixbuf(pix)
        return False


class Mock(Gtk.DrawingArea):
    """The desktop in small with the colors being tried: the bar's islands,
    a window with the focused border, a popup with a "Yes" button."""

    W, H = 256, 144

    def __init__(self):
        super().__init__()
        self.set_size_request(self.W, self.H)
        self.pix, self.colors, self.light = None, {}, 1.0
        self.connect("draw", self.draw)

    def set_picture(self, path):
        def work():
            thumb = wallpaper.thumb(path)
            try:
                pix = cover(GdkPixbuf.Pixbuf.new_from_file(str(thumb)), self.W, self.H) if thumb else None
            except GLib.Error:
                pix = None
            GLib.idle_add(lambda: (setattr(self, "pix", pix), self.queue_draw(), False)[2])
        threading.Thread(target=work, daemon=True).start()

    def update(self, colors, light):
        self.colors, self.light = colors, light
        self.queue_draw()

    def draw(self, _w, cr):
        if not self.colors:
            return False
        W, H = self.W, self.H

        def fill(key, x, y, w, h, r=3):
            cr.set_source_rgb(*wallpaper.rgb(self.colors[key]))
            rounded(cr, x, y, w, h, min(r, w / 2, h / 2))
            cr.fill()

        rounded(cr, 0, 0, W, H, 6)
        cr.clip()
        if self.pix:
            Gdk.cairo_set_source_pixbuf(cr, self.pix, 0, 0)
            cr.paint()
        else:
            fill("bg1", 0, 0, W, H, 0)
        # Brightness of the picture, roughly
        if self.light < 1:
            cr.set_source_rgba(0, 0, 0, 1 - self.light)
            cr.paint()
        elif self.light > 1:
            cr.set_source_rgba(1, 1, 1, (self.light - 1) * 0.6)
            cr.paint()
        # Islands hanging from the top
        fill("island", 4, -4, 42, 15)
        for i, key in enumerate(("hi", "mute", "mute")):
            fill(key, 10 + i * 9, 3, 4, 4, 2)
        fill("island", W / 2 - 30, -4, 60, 15)
        fill("fg", W / 2 - 18, 4, 36, 3)
        fill("island", W - 50, -4, 46, 15)
        fill("mute", W - 42, 4, 30, 3)
        # A window with the focused border
        fill("accent", 10, 20, 142, 116, 5)
        fill("bg0", 12, 22, 138, 112, 4)
        for i, (key, width) in enumerate((("hi", 70), ("fg", 110), ("fg", 96), ("sub", 104),
                                           ("mute", 60), ("green", 40), ("blue", 80))):
            fill(key if key in self.colors else "fg", 20, 32 + i * 13, width, 4, 2)
        # A popup with a "Yes" button
        fill("surface", 162, 20, 84, 70, 5)
        fill("mute", 170, 30, 34, 3)
        fill("bg2", 170, 40, 68, 14, 3)
        fill("fg", 175, 46, 40, 3)
        fill("accent", 170, 62, 68, 18, 3)
        fill("bg0", 194, 70, 20, 3)
        return False


def slider_row(title, lo, hi, value, on_change, unit=""):
    row = Gtk.Box(spacing=8)
    row.pack_start(label(title, ["small"], width=10), False, False, 0)
    shown = label(f"{int(value)}{unit}", ["muted", "small"], xalign=1.0, width=4)

    def change(v):
        shown.set_text(f"{int(v)}{unit}")
        on_change(int(v))

    s = hslider(lo, hi, change)
    s.set_value(value)
    row.pack_start(s, True, True, 0)
    row.pack_end(shown, False, False, 0)
    row.scale, row.shown, row.unit = s, shown, unit
    return row


def set_slider(row, value):
    row.scale.set_value(value)
    row.shown.set_text(f"{int(value)}{row.unit}")


class Wallpapers(Gtk.Box):
    """Wallpaper panel: search Wallhaven, pick one already here, take the
    colors from it (or keep the theme's), edit the picture, try it all on
    the desktop, then save it or go back.

    Nothing is saved until "Save" (asked once more); closing the panel while
    trying something puts back what is saved (wallpaper.py has the rest).

    "Preview" shows the desktop clean: every display goes to an empty
    workspace, the bar hides, and the panel becomes one slim bar at the top
    to keep it, drop it, or go back to adjusting it."""

    WIDTH = CELL_W * COLUMNS + 6 * (COLUMNS - 1)
    PREVIEW = "preview"  # name of the empty workspaces
    # A terminal in the middle of the preview, with ufetch and the 16
    # terminal colors; sway floats it by this app_id (sway config)
    TERMINAL = "wallpaper-preview"
    # (ufetch ends with a blank line; the last row has no newline, so
    # nothing scrolls)
    FETCH = ("printf '\\033[?25l'; clear; ~/.local/bin/ufetch; "
             "for row in 4 10; do [ $row = 10 ] && echo; printf '  '; for i in 0 1 2 3 4 5 6 7; do "
             "printf '\\033[%s%sm    ' $row $i; done; printf '\\033[0m'; done; exec sleep infinity")

    def __init__(self):
        super().__init__()
        self.full = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.full.set_size_request(self.WIDTH, -1)
        self.pack_start(self.full, False, False, 0)
        self.slim = Gtk.Box(spacing=8)
        self.slim.set_no_show_all(True)
        self.pack_start(self.slim, False, False, 0)
        self.previewing = None  # {"shown": {output: workspace}, "focus": workspace, "output": output}
        self.terminal = None
        self.sample_notes = []  # ids of the sample notifications
        self.with_examples = True
        self.base = wallpaper.base_palette()
        self.saved_path, self.saved_colors = wallpaper.saved()
        self.filters = dict(wallpaper.FILTERS)
        self.results = {"items": [], "page": 1, "last": 1, "total": 0, "seed": None}
        self.query = 0
        self.local_page = 0
        self.picked = None  # ("wallhaven", item) or ("local", path)
        self.busy = None
        self.asking = None  # "save" or "delete"
        self.found = []
        self.load_saved()
        self.screen = self.wanted()  # what is on the desktop

        top = Gtk.Box(spacing=4)
        top.pack_start(label("WALLPAPER", ["heading"]), True, True, 0)
        self.tabs = {}
        for name, text in (("wallhaven", "Wallhaven"), ("downloaded", "Downloaded"), ("colors", "Colors")):
            b = css(Gtk.Button(label=text), "tab")
            b.connect("clicked", lambda _, n=name: self.show_tab(n))
            top.pack_start(b, False, False, 0)
            self.tabs[name] = b
        self.full.pack_start(top, False, False, 0)

        # All tabs the same height, so switching doesn't resize the panel
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
        self.pages.add_named(self.search_page(), "wallhaven")
        self.pages.add_named(self.local_page_box(), "downloaded")
        self.pages.add_named(self.colors_page(), "colors")
        self.full.pack_start(self.pages, False, False, 0)

        # About the picked wallpaper, and what can be done; as tall as its
        # buttons even when it has none
        self.bar = Gtk.Box(spacing=8)
        self.bar.set_size_request(-1, 36)
        self.full.pack_start(self.bar, False, False, 0)

        atexit.register(self.put_back)
        self.full.show_all()
        self.filter_revealer.set_reveal_child(False)
        self.show_tab("wallhaven")
        self.show_local()
        self.load_colors()
        self.search()

    # ------------------------------------------------------------- state

    def load_saved(self):
        """Controls as saved: the picture behind the wallpaper, its edits,
        and its colors (as saved, until a control is touched)."""
        source, self.edits = wallpaper.original(self.saved_path)
        self.source = str(source)
        self.mode = "wallpaper" if self.saved_colors else "theme"
        self.override = dict(self.saved_colors) if self.saved_colors else None
        self.style = dict(wallpaper.STYLE)
        self.accent = None

    def colors(self):
        if self.mode == "theme":
            return {}
        if self.override is not None:
            return self.override
        return wallpaper.derive(self.base, self.found, self.accent, **self.style)

    def wanted(self):
        return (self.source, tuple(self.edits.values()), tuple(sorted(self.colors().items())))

    def trying(self):
        """Something on the desktop that is not saved."""
        return self.screen != self.saved_key

    @property
    def saved_key(self):
        source, edits = wallpaper.original(self.saved_path)
        return (str(source), tuple(edits.values()), tuple(sorted(self.saved_colors.items())))

    # -------------------------------------------------------------- tabs

    def show_tab(self, name):
        self.pages.set_visible_child_name(name)
        for n, b in self.tabs.items():
            css(b, "on", on=n == name)
        if name == "colors":
            self.refresh_colors()
        else:
            self.show_bar()

    def pager(self, on_step):
        row = Gtk.Box(spacing=8)
        prev = icon_button("left", css=["small"], on_click=lambda: on_step(-1))
        nxt = icon_button("right", css=["small"], on_click=lambda: on_step(1))
        # A spinner beside the text while a page loads; it keeps its room
        # when stopped, so nothing moves
        middle = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        spinner = Spinner()
        text = label(css=["muted", "small"], xalign=0.5)
        middle.pack_start(spinner, False, False, 0)
        middle.pack_start(text, False, False, 0)
        row.pack_start(prev, False, False, 0)
        row.pack_start(middle, True, True, 0)
        row.pack_end(nxt, False, False, 0)
        row.prev, row.next, row.text, row.spinner = prev, nxt, text, spinner
        return row

    def slots(self, grid, n):
        """Empty cells where the pictures will be, so nothing changes size."""
        for c in grid.get_children():
            c.destroy()
        for i in range(n):
            cell = css(Gtk.Box(), "slot")
            cell.set_size_request(CELL_W, CELL_H)
            grid.attach(cell, i % COLUMNS, i // COLUMNS, 1, 1)
        grid.show_all()

    def fill(self, grid, entries):
        """entries: [(thumbnail source, what picking it picks, in use)]"""
        for c in grid.get_children():
            c.destroy()
        for i, (source, what, current) in enumerate(entries):
            t = Thumb(source, lambda w=what: self.pick(w), current)
            t.what = what
            css(t, "picked", on=what == self.picked)
            grid.attach(t, i % COLUMNS, i // COLUMNS, 1, 1)
        grid.show_all()

    def in_use(self, path):
        return str(path) == str(wallpaper.original(self.saved_path)[0])

    # --------------------------------------------------------- wallhaven

    def search_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        row = Gtk.Box(spacing=6)
        self.entry = css(Gtk.SearchEntry(placeholder_text="Search Wallhaven", hexpand=True), "search")
        self.entry.connect("activate", lambda _: self.search())
        row.pack_start(self.entry, True, True, 0)
        self.filter_button = icon_button("right", "Filters", self.toggle_filters, css=["small"])
        self.filter_button.get_child().reorder_child(self.filter_button.get_child().get_children()[0], -1)
        row.pack_end(self.filter_button, False, False, 0)
        page.pack_start(row, False, False, 0)

        filters = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.paints = []
        filters.pack_start(self.choice_row("Type", [("general", "General"), ("anime", "Anime"),
                                                    ("people", "People")]), False, False, 0)
        purity = [("sfw", "SFW"), ("sketchy", "Sketchy")] + ([("nsfw", "NSFW")] if wallpaper.api_key() else [])
        filters.pack_start(self.choice_row("Content", purity), False, False, 0)
        filters.pack_start(self.choice_row("Sort", wallpaper.SORTS, "sorting"), False, False, 0)
        self.range_row = self.choice_row("Top of", wallpaper.RANGES, "range")
        self.range_row.set_sensitive(self.filters["sorting"] == "toplist")
        filters.pack_start(self.range_row, False, False, 0)
        filters.pack_start(self.choice_row("At least", wallpaper.SIZES, "atleast"), False, False, 0)
        filters.pack_start(self.choice_row("Shape", wallpaper.RATIOS, "ratio"), False, False, 0)
        filters.pack_start(self.color_row(), False, False, 0)
        self.filter_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                            transition_duration=200)
        self.filter_revealer.add(filters)
        page.pack_start(self.filter_revealer, False, False, 0)

        self.wh_grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        self.wh_scroll = Gtk.ScrolledWindow()
        self.wh_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        height = THUMB_H * 3 + 4 * 3 + 12 + 4
        self.wh_scroll.set_min_content_height(height)
        self.wh_scroll.set_max_content_height(height)
        self.wh_scroll.add(self.wh_grid)
        # Nothing found, or no connection: a small card over the grid
        self.wh_status = label(css=["muted"], xalign=0.5)
        self.wh_status.set_line_wrap(True)
        self.wh_status.set_max_width_chars(40)
        self.wh_notice = css(Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER), "notice")
        self.wh_notice.add(self.wh_status)
        self.wh_notice.set_no_show_all(True)
        self.wh_status.show()
        status = Gtk.Overlay()
        status.add(self.wh_scroll)
        status.add_overlay(self.wh_notice)
        status.set_overlay_pass_through(self.wh_notice, True)
        page.pack_start(status, False, False, 0)
        self.slots(self.wh_grid, COLUMNS * 3)

        self.wh_pager = self.pager(lambda step: self.search(self.results["page"] + step))
        page.pack_start(self.wh_pager, False, False, 0)
        return page

    def toggle_filters(self):
        opening = not self.filter_revealer.get_reveal_child()
        self.filter_revealer.set_reveal_child(opening)
        self.filter_button.get_child().get_children()[-1].set_text(ICON["down" if opening else "right"])

    def choice_row(self, title, options, key=None):
        """A filter: one of the options (key), or without a key, each option
        an on/off filter of its own."""
        row = Gtk.Box(spacing=4)
        row.pack_start(label(title, ["muted", "small"], width=9), False, False, 0)
        buttons = {}

        def paint():
            for value, b in buttons.items():
                css(b, "yes", on=self.filters[value] if key is None else self.filters[key] == value)

        def pick(value):
            if key is None:
                self.filters[value] = not self.filters[value]
            else:
                self.filters[key] = value
            for p in self.paints:
                p()
            self.range_row.set_sensitive(self.filters["sorting"] == "toplist")
            self.search()

        for value, text in options:
            b = css(Gtk.Button(label=text), "filter")
            b.connect("clicked", lambda _, v=value: pick(v))
            row.pack_start(b, False, False, 0)
            buttons[value] = b
        self.paints.append(paint)
        paint()
        return row

    def color_row(self):
        row = Gtk.Box(spacing=4)
        row.pack_start(label("Color", ["muted", "small"], width=9, xalign=0.0), False, False, 0)
        grid = Gtk.Grid(row_spacing=2, column_spacing=2)
        buttons = {}

        def paint():
            for value, b in buttons.items():
                css(b, "yes", on=self.filters["color"] == value)

        def pick(value):
            self.filters["color"] = "" if self.filters["color"] == value else value
            paint()
            self.search()

        anyone = css(Gtk.Button(label="Any"), "filter")
        anyone.connect("clicked", lambda _: pick(""))
        buttons[""] = anyone
        grid.attach(anyone, 0, 0, 1, 2)
        for i, c in enumerate(wallpaper.COLORS):
            b = css(Gtk.Button(), "chip")
            b.add(Chip([c], 18, 12))
            b.set_tooltip_text(f"#{c}")
            b.connect("clicked", lambda _, v=c: pick(v))
            grid.attach(b, 1 + i % 15, i // 15, 1, 1)
            buttons[c] = b
        row.pack_start(grid, False, False, 0)
        self.paints.append(paint)
        paint()
        return row

    def search(self, page=1):
        self.query += 1
        query = self.query
        self.filters["q"] = self.entry.get_text().strip()
        f = dict(self.filters)
        seed = self.results.get("seed") if page != 1 else None
        self.loading(True)
        if not self.results["items"]:
            self.wh_pager.text.set_text("Searching Wallhaven…")

        def work():
            try:
                res, err = wallpaper.search(f, page, seed), None
            except OSError as e:
                res, err = None, str(getattr(e, "reason", e))
            GLib.idle_add(self.show_results, query, res, err)
        threading.Thread(target=work, daemon=True).start()

    def show_results(self, query, res, err):
        if query != self.query:
            return False  # an older search
        self.loading(False)
        if err:
            self.notice(f"Couldn't reach Wallhaven: {err}")
            self.wh_pager.text.set_text("")
            return False
        self.results = res
        self.fill(self.wh_grid, [(w["thumb"], ("wallhaven", w), self.in_use(wallpaper.file_of(w)))
                                 for w in res["items"]])
        if not res["items"]:
            self.slots(self.wh_grid, COLUMNS * 3)
        self.notice("" if res["items"] else "No wallpapers found")
        self.wh_pager.text.set_text(f"Page {res['page']} of {max(1, res['last'])} · {res['total']} wallpapers")
        self.wh_pager.prev.set_sensitive(res["page"] > 1)
        self.wh_pager.next.set_sensitive(res["page"] < res["last"])
        self.wh_scroll.get_vadjustment().set_value(0)
        return False

    def loading(self, on):
        """While a page loads: the spinner turns, and the pictures there
        fade until the new ones come."""
        pager = self.wh_pager
        (pager.spinner.start if on else pager.spinner.stop)()
        css(self.wh_scroll, "loading", on=on)
        self.wh_scroll.set_sensitive(not on)
        pager.prev.set_sensitive(not on and self.results["page"] > 1)
        pager.next.set_sensitive(not on and self.results["page"] < self.results["last"])
        if on:
            self.wh_notice.hide()

    def notice(self, text):
        self.wh_status.set_text(text)
        self.wh_notice.set_visible(bool(text))

    # -------------------------------------------------------- downloaded

    def local_page_box(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.pack_start(label("In ~/Pictures/Wallpapers, and the ones that come with the dotfiles",
                              ["muted", "small"]), False, False, 0)
        self.local_grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        self.local_grid.set_size_request(-1, THUMB_H * 3 + 4 * 3 + 12)
        self.local_grid.set_valign(Gtk.Align.START)
        page.pack_start(self.local_grid, True, True, 0)
        self.local_pager = self.pager(self.local_step)
        page.pack_end(self.local_pager, False, False, 0)
        return page

    def local_step(self, step):
        self.local_page += step
        self.show_local()

    def show_local(self):
        files = wallpaper.downloaded()
        pages = max(1, -(-len(files) // LOCAL_PAGE))
        self.local_page = max(0, min(self.local_page, pages - 1))
        shown = files[self.local_page * LOCAL_PAGE:(self.local_page + 1) * LOCAL_PAGE]
        self.fill(self.local_grid, [(str(p), ("local", str(p)), self.in_use(p)) for p in shown])
        self.local_pager.text.set_text(f"Page {self.local_page + 1} of {pages} · "
                                       f"{len(files)} wallpaper{'s' if len(files) != 1 else ''}")
        self.local_pager.prev.set_sensitive(self.local_page > 0)
        self.local_pager.next.set_sensitive(self.local_page < pages - 1)

    # ------------------------------------------------------------ colors

    def colors_page(self):
        page = Gtk.Box(spacing=20)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        modes = Gtk.Box(spacing=4, homogeneous=True)
        self.mode_buttons = {}
        for mode, text in (("theme", "Theme colors"), ("wallpaper", "From the wallpaper")):
            b = css(Gtk.Button(label=text), "choice")
            b.connect("clicked", lambda _, m=mode: self.set_mode(m))
            modes.pack_start(b, True, True, 0)
            self.mode_buttons[mode] = b
        left.pack_start(modes, False, False, 0)

        self.tuning = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "tuning")
        self.tuning.pack_start(label("ACCENT", ["heading"]), False, False, 0)
        self.accent_row = Gtk.Box(spacing=4)
        self.tuning.pack_start(self.accent_row, False, False, 0)
        self.tuning.pack_start(label("STYLE", ["heading"]), False, False, 4)
        presets = Gtk.Box(spacing=4, homogeneous=True)
        self.preset_chips = []
        for name, values in wallpaper.PRESETS:
            b = css(Gtk.Button(), "choice")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            chip = Chip([], 44, 10)
            chip.set_halign(Gtk.Align.CENTER)
            inner.pack_start(chip, False, False, 0)
            inner.pack_start(label(name, ["small"], xalign=0.5), False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _, v=values: self.set_style(v))
            presets.pack_start(b, True, True, 0)
            self.preset_chips.append((chip, values))
        self.tuning.pack_start(presets, False, False, 0)
        self.tint_row = slider_row("Tint", 0, 40, self.style["tint"] * 100,
                                   lambda v: self.tune("tint", v / 100), "%")
        self.shade_row = slider_row("Background", -6, 6, self.style["shade"] * 100,
                                    lambda v: self.tune("shade", v / 100))
        self.light_row = slider_row("Accent", 55, 92, self.style["light"] * 100,
                                    lambda v: self.tune("light", v / 100), "%")
        for row in (self.tint_row, self.shade_row, self.light_row):
            self.tuning.pack_start(row, False, False, 0)
        left.pack_start(self.tuning, False, False, 0)

        left.pack_start(label("PICTURE", ["heading"]), False, False, 4)
        if wallpaper.has_magick():
            self.edit_rows = {
                "brightness": slider_row("Brightness", 40, 130, 100, lambda v: self.set_edit("brightness", v), "%"),
                "saturation": slider_row("Saturation", 0, 150, 100, lambda v: self.set_edit("saturation", v), "%"),
                "blur": slider_row("Blur", 0, 20, 0, lambda v: self.set_edit("blur", v)),
            }
            for row in self.edit_rows.values():
                left.pack_start(row, False, False, 0)
        else:
            self.edit_rows = {}
            left.pack_start(label("Install ImageMagick to edit the picture", ["muted", "small"]), False, False, 0)
        page.pack_start(left, True, True, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.pack_start(label("PREVIEW", ["heading"]), False, False, 0)
        self.mock = Mock()
        right.pack_start(self.mock, False, False, 0)
        self.picture_name = label(css=["muted", "small"], ellipsize=True)
        self.picture_name.set_max_width_chars(30)
        right.pack_start(self.picture_name, False, False, 0)
        page.pack_end(right, False, False, 0)
        return page

    def load_colors(self, then=None):
        """Swatches of the picture the Colors page works on."""
        source = self.source
        self.mock.set_picture(source)

        def work():
            found = wallpaper.swatches(source)
            GLib.idle_add(self.got_colors, source, found, then)
        threading.Thread(target=work, daemon=True).start()

    def got_colors(self, source, found, then):
        if source != self.source:
            return False
        self.found = found
        for c in self.accent_row.get_children():
            c.destroy()
        for i, (color, share) in enumerate(found):
            b = css(Gtk.Button(), "chip")
            b.add(Chip([color], 36, 22))
            b.set_tooltip_text(f"#{color} · {share:.0%} of the picture")
            b.connect("clicked", lambda _, i=i: self.set_accent(i))
            self.accent_row.pack_start(b, False, False, 0)
        self.accent_row.show_all()
        for chip, values in self.preset_chips:
            d = {**self.base, **wallpaper.derive(self.base, found, self.accent, **values)}
            chip.set_colors([d[k] for k in ("bg0", "bg2", "mute", "fg", "accent")])
        self.refresh_colors()
        if then:
            then()
        return False

    def refresh_colors(self):
        for m, b in self.mode_buttons.items():
            css(b, "yes", on=m == self.mode)
        self.tuning.set_sensitive(self.mode == "wallpaper")
        pick = self.accent if self.accent is not None else wallpaper.vivid(self.found)
        for i, b in enumerate(self.accent_row.get_children()):
            css(b, "yes", on=i == pick and self.override is None)
        set_slider(self.tint_row, self.style["tint"] * 100)
        set_slider(self.shade_row, self.style["shade"] * 100)
        set_slider(self.light_row, self.style["light"] * 100)
        for key, row in self.edit_rows.items():
            set_slider(row, self.edits[key])
        self.mock.update({**self.base, **self.colors()}, self.edits["brightness"] / 100)
        self.picture_name.set_text(os.path.basename(self.source))
        self.show_bar()

    def touched(self):
        self.override = None
        self.refresh_colors()

    def set_mode(self, mode):
        self.mode = mode
        self.touched()

    def set_accent(self, i):
        self.accent = i
        self.touched()

    def set_style(self, values):
        self.style = dict(values)
        self.touched()

    def tune(self, key, value):
        self.style[key] = value
        self.touched()

    def set_edit(self, key, value):
        self.edits[key] = value
        self.refresh_colors()

    def as_saved(self):
        old = self.source
        self.load_saved()
        if self.source != old:
            self.load_colors()
        self.refresh_colors()

    # ------------------------------------------------------- the bar

    def pick(self, what):
        self.picked = what
        self.asking = None
        for grid in (self.wh_grid, self.local_grid):
            for t in grid.get_children():
                css(t, "picked", on=t.what == what)
        self.show_bar()

    def about(self):
        kind, what = self.picked
        if kind == "wallhaven":
            return f"{what['resolution'].replace('x', '×')} · {what['size'] / 1e6:.1f} MB · {what['category']}"
        info = GdkPixbuf.Pixbuf.get_file_info(what)
        size = f" · {info[1]}×{info[2]}" if info and info[0] else ""
        return os.path.basename(what) + size + (" · in use" if self.in_use(what) else "")

    def show_bar(self):
        for c in self.bar.get_children():
            c.destroy()
        info = label(css=["muted"], ellipsize=True)
        info.set_valign(Gtk.Align.CENTER)
        self.bar.pack_start(info, True, True, 0)
        buttons = []

        def button(text, action, yes=False):
            b = Gtk.Button(label=text)
            if yes:
                css(b, "yes")
            b.connect("clicked", lambda _: action())
            buttons.append(b)

        # The Colors page works on what is being tried, not on the picked one
        picked_new = (self.picked and self.pages.get_visible_child_name() != "colors"
                      and not (self.picked[0] == "local" and self.picked[1] == self.source))
        if self.busy:
            info.set_text(self.busy)
        elif self.asking == "save":
            colors = " and these colors" if self.screen[2] else " with the theme colors"
            info.set_text(f"Keep this wallpaper{colors}?")
            info.get_style_context().remove_class("muted")
            button("No", lambda: self.ask(None))
            button("Save", self.save, yes=True)
        elif self.asking == "delete":
            info.set_text(f"Delete {os.path.basename(self.picked[1])}?")
            info.get_style_context().remove_class("muted")
            button("No", lambda: self.ask(None))
            button("Delete", self.delete, yes=True)
        elif self.trying() or self.wanted() != self.screen:
            if self.wanted() != self.screen:
                info.set_text("Changed: try it on the desktop before saving")
            else:
                info.set_text("Trying it on the desktop · not saved yet")
            if self.trying():
                button("Discard", self.discard)
            else:
                button("Undo", self.as_saved)
            if picked_new:
                button("Try this one", self.try_picked)
            if self.wanted() != self.screen:
                button("Try", self.apply, yes=True)
            elif self.trying():
                button("Preview", self.start_preview)
                button("Save…", lambda: self.ask("save"), yes=True)
        elif self.picked:
            info.set_text(self.about())
            kind, what = self.picked
            if kind == "wallhaven":
                button("Wallhaven", lambda: spawn("xdg-open", what["url"]))
            elif wallpaper.can_delete(what) and not self.in_use(what):
                button("Delete…", lambda: self.ask("delete"))
            if picked_new:
                button("Try it", self.try_picked, yes=True)
        else:
            info.set_text("Pick a wallpaper to try it on the desktop")
        for b in buttons:
            self.bar.pack_start(b, False, False, 0)
        self.bar.show_all()

    def ask(self, what):
        self.asking = what
        self.show_bar()

    def set_busy(self, text):
        self.busy = text
        self.show_bar()
        return False

    def fail(self, text):
        self.busy = None
        self.show_bar()
        self.bar.get_children()[0].set_text(text)
        return False

    # ----------------------------------------------------------- actions

    def try_picked(self):
        kind, what = self.picked
        if kind == "local" and not os.path.exists(what):
            # Deleted since the list was made
            self.picked = None
            self.show_local()
            self.fail(f"{os.path.basename(what)} is gone")
            return
        if kind == "local":
            self.use_source(what)
            return
        self.set_busy("Downloading…")

        def progress(f):
            GLib.idle_add(self.set_busy, f"Downloading… {int(f * 100)}%")

        def work():
            try:
                path = wallpaper.download(what, progress)
            except OSError as e:
                GLib.idle_add(self.fail, f"Couldn't download it: {getattr(e, 'reason', e)}")
                return
            GLib.idle_add(lambda: self.got_download(str(path)) or False)
        threading.Thread(target=work, daemon=True).start()

    def got_download(self, path):
        self.show_local()
        self.picked = ("local", path)
        self.use_source(path)

    def use_source(self, path):
        """A new picture: fresh edits and colors, then on the desktop."""
        self.source = path
        self.edits = dict(wallpaper.EDIT)
        self.accent = None
        self.override = None
        self.busy = "Reading its colors…"
        self.load_colors(then=self.apply)

    def apply(self):
        """Puts the picture, its edits and the colors on the desktop."""
        if self.busy and self.busy != "Reading its colors…":
            return
        wanted, colors, edits, source = self.wanted(), self.colors(), dict(self.edits), self.source
        self.set_busy("Editing the picture…" if edits != wallpaper.EDIT else "Applying…")
        same_colors = wanted[2] == self.screen[2]

        def work():
            path = str(wallpaper.edit(source, **edits))
            if same_colors:
                wallpaper.show(path, {**self.base, **colors}["bg1"])
            else:
                wallpaper.preview(path, colors)
            GLib.idle_add(self.applied, wanted, not same_colors)
        threading.Thread(target=work, daemon=True).start()

    def applied(self, wanted, restyled):
        self.screen = wanted
        self.busy = None
        if restyled:
            restyle()
        self.show_bar()
        return False

    def save(self):
        self.asking = None
        self.set_busy("Saving…")
        colors = dict(self.screen[2])
        path = str(wallpaper.edit(self.screen[0], **dict(zip(wallpaper.EDIT, self.screen[1]))))

        def work():
            wallpaper.save(path, colors)
            GLib.idle_add(self.saved, path, colors)
        threading.Thread(target=work, daemon=True).start()

    def saved(self, path, colors):
        self.saved_path, self.saved_colors = path, colors
        self.busy = None
        restyle()
        self.show_local()
        self.show_bar()
        self.bar.get_children()[0].set_text("Saved")
        return False

    def discard(self):
        self.asking = None
        same_colors = self.screen[2] == self.saved_key[2]
        self.set_busy("Putting it back…")

        def work():
            self.restore(same_colors)
            GLib.idle_add(self.discarded, same_colors)
        threading.Thread(target=work, daemon=True).start()

    def restore(self, same_colors):
        if same_colors:
            wallpaper.show(self.saved_path, {**self.base, **self.saved_colors}["bg1"])
        else:
            wallpaper.revert()

    def discarded(self, same_colors):
        self.as_saved()
        self.screen = self.saved_key
        self.busy = None
        if not same_colors:
            restyle()
        self.show_bar()
        return False

    def put_back(self):
        """On the way out: nothing tried stays on the desktop."""
        self.uncover()
        if self.trying():
            self.restore(self.screen[2] == self.saved_key[2])

    # ----------------------------------------------------------- preview

    def start_preview(self):
        self.cover()
        self.swap(lambda: self.show_slim(None))

    def end_preview(self, then=None):
        """Back to the full panel; then() runs once the desktop is back."""
        def back():
            self.uncover()
            self.slim.hide()
            css(self.get_parent(), "slim", on=False)
            self.full.show()
            self.show_bar()
            if then:
                then()
        self.swap(back)

    def swap(self, change):
        top = self.get_toplevel()
        top.swap(change) if hasattr(top, "swap") else change()

    def show_slim(self, asking):
        """The slim bar: what is being previewed, and what to do with it.
        Both of its questions are made at once, side by side in a stack, so
        it has the width of the longer one and doesn't change size."""
        if asking:
            self.slim_stack.set_visible_child_name("save")
            return
        self.full.hide()
        css(self.get_parent(), "slim")
        for c in self.slim.get_children():
            c.destroy()
        self.slim.pack_start(label(ICON["image"], ["icon", "muted"]), False, False, 0)
        self.terminal_button = icon_button("terminal", css=["tab"], on_click=lambda: self.show_examples(
            not self.with_examples))
        self.terminal_button.set_tooltip_text("Examples: a terminal with ufetch and a notification")
        css(self.terminal_button, "on", on=self.with_examples)
        self.slim.pack_start(self.terminal_button, False, False, 0)
        name = os.path.basename(self.source)
        name = name if len(name) <= 28 else name[:27] + "…"
        colors = " · wallpaper colors" if self.screen[2] else " · theme colors"
        self.slim_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
        for page, text, buttons in (
                ("preview", f"Previewing {name}{colors}",
                 (("Adjust", self.end_preview, False),
                  ("Don't keep", lambda: self.end_preview(self.discard), False),
                  ("Keep…", lambda: self.show_slim("save"), True))),
                ("save", f"Keep {name}{colors}?",
                 (("No", lambda: self.slim_stack.set_visible_child_name("preview"), False),
                  ("Save", lambda: self.end_preview(self.save), True)))):
            row = Gtk.Box(spacing=8)
            question = label(text, ["muted"] if page == "preview" else [])
            question.set_valign(Gtk.Align.CENTER)
            row.pack_start(question, True, True, 12)
            for t, action, yes in buttons:
                b = Gtk.Button(label=t)
                if yes:
                    css(b, "yes")
                b.connect("clicked", lambda _, a=action: a())
                row.pack_start(b, False, False, 0)
            self.slim_stack.add_named(row, page)
        self.slim.pack_start(self.slim_stack, True, True, 0)
        self.slim.set_no_show_all(False)
        self.slim.show_all()
        self.slim_stack.set_visible_child_name("preview")

    def before_close(self):
        """Esc while previewing: back to adjusting it."""
        if self.previewing and self.slim.get_visible():
            self.end_preview()
            return True
        return False

    def click_outside(self):
        """While previewing, clicks on the desktop do nothing: it is only to
        look at (the terminal there can't be used either, since the panel
        has the keyboard and its backdrop takes the clicks)."""
        return bool(self.previewing)

    def cover(self):
        """Hides the windows (an empty workspace on every display) and the bar."""
        if self.previewing:
            return
        spaces = json.loads(run("swaymsg", "-t", "get_workspaces") or "[]")
        focused = next((w for w in spaces if w["focused"]), None)
        self.previewing = {"shown": {w["output"]: w["name"] for w in spaces if w["visible"]},
                           "focus": focused and focused["name"], "output": focused and focused["output"]}
        for i, output in enumerate(self.previewing["shown"]):
            run("swaymsg", f"focus output {output}; workspace {self.PREVIEW}-{i}")
        if self.previewing["output"]:
            run("swaymsg", f"focus output {self.previewing['output']}")
        run("pkill", "-USR1", "-x", "waybar")  # toggles: hidden
        if self.with_examples:
            self.show_examples(True)

    def show_examples(self, on):
        """Things that show the colors: a terminal with ufetch and two
        notifications, one with a picture (mako keeps them until the preview
        ends, out of the history: mako config)."""
        self.with_examples = on
        if hasattr(self, "terminal_button"):
            css(self.terminal_button, "on", on=on)
        if on and not self.sample_notes and self.previewing:
            picture = wallpaper.square(self.source)
            notes = [["Wallpaper preview", "A notification, with these colors"],
                     ["-i", str(picture), os.path.basename(self.source), "And one with a picture"]
                     if picture else None]
            self.sample_notes = [run("notify-send", "-a", "Wallpaper", "-c", "preview", "-p", *n)
                                 for n in notes if n]
        elif not on:
            for note in self.sample_notes:
                run("makoctl", "dismiss", "-n", note)
            self.sample_notes = []
        if on and not self.terminal and self.previewing:
            # Just the size of what it prints: ufetch and the two rows of
            # colors, with a cell of room around
            fetch = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\(B", "", run(os.path.expanduser("~/.local/bin/ufetch")))
            lines = fetch.splitlines() or [""]
            columns = max(max(len(l) for l in lines), 2 + 8 * 4) + 2
            self.terminal = subprocess.Popen(
                ["alacritty", "--class", self.TERMINAL,
                 "-o", f"window.dimensions.columns={columns}", "-o", f"window.dimensions.lines={len(lines) + 3}",
                 "-e", "sh", "-c", self.FETCH],
                start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.place_terminal(time.monotonic())
        elif not on and self.terminal:
            self.terminal.terminate()
            self.terminal = None

    def place_terminal(self, started):
        """Down in the corner, out of the way of the picture. It opens
        invisible (sway config) and shows up once there, so it doesn't jump."""
        def find(node):
            for c in node.get("nodes", []) + node.get("floating_nodes", []):
                if c.get("app_id") == self.TERMINAL:
                    return c
                found = find(c)
                if found:
                    return found
            return None

        def check():
            if not self.terminal:
                return False
            win = find(json.loads(run("swaymsg", "-t", "get_tree") or "{}"))
            if not win or not win["rect"]["width"]:
                return time.monotonic() - started < 3  # keep looking
            outputs = json.loads(run("swaymsg", "-t", "get_outputs") or "[]")
            out = next((o["rect"] for o in outputs if o.get("focused")), None)
            if out:
                margin = 24
                x = out["x"] + out["width"] - win["rect"]["width"] - margin
                y = out["y"] + out["height"] - win["rect"]["height"] - margin
                run("swaymsg", f'[app_id="{self.TERMINAL}"] move absolute position {x} {y}, opacity 1')
            return False
        GLib.timeout_add(50, check)

    def uncover(self):
        if not self.previewing:
            return
        self.show_examples(False)
        self.with_examples = True
        shown, focus = self.previewing["shown"], self.previewing["focus"]
        self.previewing = None
        for output, ws in shown.items():
            run("swaymsg", f"focus output {output}; workspace {quote(ws)}")
        if focus:
            run("swaymsg", f"workspace {quote(focus)}")
        run("pkill", "-USR1", "-x", "waybar")  # shown again

    def delete(self):
        wallpaper.delete(self.picked[1])
        self.picked = None
        self.asking = None
        self.show_local()
        self.show_bar()


# ---------------------------------------------------------------- window

def transparent(window):
    visual = window.get_screen().get_rgba_visual()
    if visual:
        window.set_visual(visual)
    window.set_app_paintable(True)


class Backdrop(Gtk.Window):
    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "bar-panel-backdrop")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(self, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        transparent(self)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.on_click = Gtk.main_quit
        self.connect("button-press-event", lambda *_: self.on_click())


SLIDE_MS = 220
# Transparent room around the panel for its shadow (drawn by the CSS, so it
# slides with the panel; SwayFX would shadow the whole window instead)
SHADOW = 24


class Panel(Gtk.Window):
    def __init__(self, mode):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "bar-panel")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 6)
        if mode in ("menu", "network", "updates", "sound", "displays", "bluetooth"):
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 6 - SHADOW)

        transparent(self)

        frame = Gtk.Box()
        frame.get_style_context().add_class("panel")
        self.content = (Menu(mode) if mode in ("sound", "displays", "bluetooth") else
                        {"media": Media, "calendar": Calendar, "menu": Menu, "network": Network, "updates": Updates,
                         "wallpaper": Wallpapers}[mode]())
        frame.add(self.content)
        # Slides down from the bar when it opens, and back up when it closes
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=SLIDE_MS)
        room = Gtk.Box(margin_start=SHADOW, margin_end=SHADOW, margin_bottom=SHADOW)
        room.add(frame)
        self.revealer.add(room)
        self.add(self.revealer)
        self.closing = False
        # The window starts at its final size (transparent) and the content
        # slides inside it: sway won't follow a surface that grows every frame
        self.revealer.set_valign(Gtk.Align.START)
        room.show_all()
        # The size it settles at once released (open_up): its minimum width,
        # where long device names are cut with "…", not their full length
        width = room.get_preferred_width()[0]
        self.set_size_request(width, room.get_preferred_height_for_width(width)[1])

        if mode == "media":
            frame.show_all()
            screen = Gdk.Display.get_default().get_monitor(0).get_geometry().width
            center = (WORKSPACES_WIDTH + screen / 2 - CLOCK_WIDTH / 2) / 2
            width = frame.get_preferred_width()[1]
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, max(6, int(center - width / 2)) - SHADOW)

        self.connect("key-press-event", lambda _w, e: e.keyval == 0xff1b and self.close())
        self.connect("destroy", Gtk.main_quit)

    def open_up(self):
        self.revealer.set_reveal_child(True)
        # Once open, the panel may grow (Wi-Fi list, power tiles...)
        GLib.timeout_add(SLIDE_MS + 30, lambda: self.set_size_request(-1, -1) or False)
        return False

    def swap(self, change):
        """Slides up, changes the content, slides back down at its new size."""
        a = self.get_allocation()
        self.set_size_request(a.width, a.height)
        self.revealer.set_reveal_child(False)

        def middle():
            change()
            room = self.revealer.get_child()
            width = room.get_preferred_width()[1]
            self.set_size_request(width, room.get_preferred_height_for_width(width)[1])
            self.resize(1, 1)
            self.revealer.set_reveal_child(True)
            GLib.timeout_add(SLIDE_MS + 30, lambda: self.set_size_request(-1, -1) or False)
            return False
        GLib.timeout_add(SLIDE_MS + 20, middle)

    def click_outside(self):
        if not getattr(self.content, "click_outside", lambda: False)():
            self.close()

    def close(self, force=False):
        if not force and getattr(self.content, "before_close", lambda: False)():
            return True
        if not self.closing:
            self.closing = True
            # Same trick in reverse: freeze the size, slide the content up
            a = self.get_allocation()
            self.set_size_request(a.width, a.height)
            self.revealer.set_reveal_child(False)
            GLib.timeout_add(SLIDE_MS + 20, Gtk.main_quit)
        return True


STYLE = Gtk.CssProvider()


def restyle():
    """Loads the palette (`theme`) and the CSS, which uses @bg0, @fg,
    @accent...; again when the wallpaper panel tries new colors."""
    try:
        colors = open(os.path.expanduser("~/.config/waybar/colors.css"), "rb").read()
    except OSError:
        colors = b""
    STYLE.load_from_data(colors + CSS)


MODES = ("media", "calendar", "menu", "network", "updates", "sound", "displays", "bluetooth", "wallpaper")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        sys.exit("usage: panel.py " + "|".join(MODES))
    take_over(mode)

    restyle()
    Gtk.StyleContext.add_provider_for_screen(
        Gtk.Window().get_screen(), STYLE, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    backdrop = Backdrop()
    backdrop.show_all()
    panel = Panel(mode)
    backdrop.on_click = panel.click_outside
    # Closed by the bar (same button again): slide up first
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: panel.close(force=True) and False)
    panel.show_all()
    GLib.timeout_add(30, panel.open_up)
    Gtk.main()

    # Clear the pidfile only if it is still ours
    try:
        if open(PIDFILE).read().split()[0] == str(os.getpid()):
            os.remove(PIDFILE)
    except (OSError, IndexError):
        pass


if __name__ == "__main__":
    main()
