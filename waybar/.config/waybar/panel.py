#!/usr/bin/env python3
"""Bar popups: mini media player, calendar + notifications, general menu,
sound, displays, bluetooth.

Usage: panel.py media|calendar|menu|network|updates|sound|displays|bluetooth
Running it again with the same mode closes it; another mode replaces it.
"""
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
    "trash": "\uf1f8",
}

CSS = b"""
window { background: transparent; }
.panel {
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.55), 0 1px 4px rgba(0, 0, 0, 0.35);
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
        self.right.pack_start(label("CALENDAR", ["heading"]), False, False, 6)
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
        frame.add(Menu(mode) if mode in ("sound", "displays", "bluetooth") else
                  {"media": Media, "calendar": Calendar, "menu": Menu, "network": Network, "updates": Updates}[mode]())
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

    def close(self):
        if not self.closing:
            self.closing = True
            # Same trick in reverse: freeze the size, slide the content up
            a = self.get_allocation()
            self.set_size_request(a.width, a.height)
            self.revealer.set_reveal_child(False)
            GLib.timeout_add(SLIDE_MS + 20, Gtk.main_quit)
        return True


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("media", "calendar", "menu", "network", "updates", "sound", "displays", "bluetooth"):
        sys.exit("usage: panel.py media|calendar|menu|network|updates|sound|displays|bluetooth")
    take_over(mode)

    # Palette (`theme`) first, so the CSS can use @bg0, @fg, @accent...
    try:
        colors = open(os.path.expanduser("~/.config/waybar/colors.css"), "rb").read()
    except OSError:
        colors = b""
    provider = Gtk.CssProvider()
    provider.load_from_data(colors + CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gtk.Window().get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    backdrop = Backdrop()
    backdrop.show_all()
    panel = Panel(mode)
    backdrop.on_click = panel.close
    # Closed by the bar (same button again): slide up first
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: panel.close() and False)
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
