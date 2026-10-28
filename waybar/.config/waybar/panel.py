#!/usr/bin/env python3
"""Bar popups: mini media player, calendar + notifications, general menu,
sound, displays, bluetooth, vpn, wallpaper.

Usage: panel.py media|calendar|menu|network|updates|sound|displays|bluetooth|vpn|wallpaper
Running it again with the same mode closes it; another mode replaces it.
"""
import atexit
import datetime
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
import vpn
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
    "vpn": "\uf3ed", "trash": "\uf1f8", "camera": "\uf030", "move": "\uf0ec", "image": "\uf03e", "terminal": "\uf120",
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
.device-card { background: @bg2; border-radius: 4px; }
.device-card.asking { padding: 0 8px 0 12px; }
button.device-main { padding: 0 12px; border-radius: 4px; }
button.device-side { padding: 0; min-width: 40px; color: @mute; border-radius: 4px; }
button.device-side:hover { color: @red; }
.error { color: @red; }
button.small.danger { background: @red; color: @bg0; }
button.small.yes { color: @bg0; }
.device-title { color: @hi; }
button.device-card.picked { box-shadow: inset 0 0 0 1px @accent; }
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
button.ctl:disabled label { color: @faint; }
scale { padding: 0; margin: 0; }
levelbar trough { background: @line; border: none; border-radius: 3px; min-height: 6px; padding: 0; }
levelbar block { border: none; border-radius: 3px; min-height: 6px; }
levelbar block.filled { background: @accent; }
levelbar block.empty { background: transparent; }
levelbar.thin trough, levelbar.thin block { min-height: 3px; }

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
/* Thin, in the volume pills' colors: accent, grey when muted */
scale.thin highlight { background: @accent; }
scale.thin.off highlight { background: @off; }
scale.thin.off slider { background: @off; }
button.vol-icon { padding: 0; min-width: 18px; color: @mute; font-size: 11px; }
button.vol-icon:hover { background: transparent; color: @hi; }
scale:disabled slider, scale:disabled highlight { background: transparent; }


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

.today-big { color: @hi; font-size: 18px; font-weight: bold; }
.month { color: @hi; }
.weekday { color: @mute; font-size: 11px; }
.day { border-radius: 6px; }
.day.other { color: @faint; }
.day.today { background: @accent; color: @bg0; font-weight: bold; }
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

# The player the popup shows and controls (dev/panel-sizes.py points it at
# its pretend player, so a real one is never touched)
PLAYERCTL = ["playerctl"]

class Cover(Gtk.DrawingArea):
    """The album art in a rounded square; a music note while there is none."""

    SIZE = 96

    def __init__(self):
        super().__init__()
        self.set_size_request(self.SIZE, self.SIZE)
        self.set_valign(Gtk.Align.START)
        self.pix = None
        self.connect("draw", self.draw)

    def load(self, path):
        scale = self.get_scale_factor()
        try:
            self.pix = cover(GdkPixbuf.Pixbuf.new_from_file(path), self.SIZE * scale, self.SIZE * scale)
        except (GLib.Error, TypeError):
            self.pix = None
        self.queue_draw()

    def draw(self, _w, cr):
        n = self.SIZE
        rounded(cr, 0, 0, n, n, 6)
        cr.clip()
        if self.pix:
            k = 1 / self.get_scale_factor()
            cr.scale(k, k)
            Gdk.cairo_set_source_pixbuf(cr, self.pix, 0, 0)
            cr.paint()
            return False
        ctx = self.get_style_context()
        for name in ("bg2", "mute"):
            found, c = ctx.lookup_color(name)
            cr.set_source_rgb(*((c.red, c.green, c.blue) if found else (0.5, 0.5, 0.5)))
            if name == "bg2":
                cr.paint()
        layout = self.create_pango_layout(ICON["music"])
        layout.set_font_description(Pango.FontDescription("Font Awesome 6 Free Heavy 22px"))
        w, h = layout.get_pixel_size()
        cr.move_to((n - w) / 2, (n - h) / 2)
        PangoCairo.show_layout(cr, layout)
        return False


class Media(Gtk.Box):
    """Art on the left; title, artist and the buttons beside it; the
    progress with both times in one line below. Every part keeps its room
    whatever plays (long titles, no art, a stream, nothing at all).

    The volume is a button like the others (scrolling on it changes it);
    clicked, the progress line turns into the volume for a while."""

    VOLUME_MS = 3000  # back to the progress after this long untouched

    FIELDS = ["status", "xesam:title", "xesam:artist", "mpris:artUrl",
              "mpris:length", "position", "volume", "playerName"]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.art_url = None

        top = Gtk.Box(spacing=14)
        self.cover = Cover()
        top.pack_start(self.cover, False, False, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.title = label(css=["title"], ellipsize=True, width=27)
        self.artist = label(ellipsize=True, width=27)
        self.player = label(css=["muted", "small"], ellipsize=True, width=27)
        for w in (self.title, self.artist, self.player):
            side.pack_start(w, False, False, 0)

        controls = Gtk.Box(spacing=2, valign=Gtk.Align.END, halign=Gtk.Align.CENTER)
        self.buttons = [icon_button("prev", css=["ctl"], on_click=lambda: run(*PLAYERCTL, "previous")),
                        icon_button("play", css=["ctl", "main"], on_click=lambda: run(*PLAYERCTL, "play-pause")),
                        icon_button("next", css=["ctl"], on_click=lambda: run(*PLAYERCTL, "next"))]
        self.play = self.buttons[1]
        for b in self.buttons:
            controls.pack_start(b, False, False, 0)
        # Players that have no volume (Firefox...) leave its room empty
        self.unmuted = 1.0  # back to this when unmuting
        self.back_timer = None
        self.volume = icon_button("volume", css=["ctl"], on_click=lambda: self.show_volume(
            self.lines.get_visible_child_name() != "volume"))
        self.volume.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.volume.connect("scroll-event", self.scrolled)
        controls.pack_start(self.volume, False, False, 0)
        side.pack_end(controls, True, True, 0)
        top.pack_start(side, True, True, 0)
        self.pack_start(top, False, False, 0)

        # Both lines in one stack: swapping them changes no size, and the
        # sliders line up (same room on each side)
        self.lines = Gtk.Stack(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=150)
        left, right = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL), Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        progress = Gtk.Box(spacing=10)
        self.pos = label(css=["muted", "small"], width=5, ellipsize=True)
        self.seek = css(hslider(0, 1, lambda v: run(*PLAYERCTL, "position", str(int(v)))), "thin")
        self.length = label(css=["muted", "small"], xalign=1.0, width=5, ellipsize=True)
        progress.pack_start(self.pos, False, False, 0)
        progress.pack_start(self.seek, True, True, 0)
        progress.pack_start(self.length, False, False, 0)
        volume = Gtk.Box(spacing=10)
        self.mute = icon_button("volume", css=["vol-icon"], on_click=self.toggle_mute)
        self.mute.set_halign(Gtk.Align.START)
        self.vol = css(hslider(0, 100, lambda v: self.set_volume(v / 100)), "thin")
        self.percent = label(css=["muted", "small"], xalign=1.0, width=5)
        volume.pack_start(self.mute, False, False, 0)
        volume.pack_start(self.vol, True, True, 0)
        volume.pack_start(self.percent, False, False, 0)
        left.add_widget(self.pos)
        left.add_widget(self.mute)
        right.add_widget(self.length)
        right.add_widget(self.percent)
        self.lines.add_named(progress, "progress")
        self.lines.add_named(volume, "volume")
        self.pack_start(self.lines, False, False, 0)

        self.refresh()
        GLib.timeout_add_seconds(1, self.refresh)

    def refresh(self):
        fmt = "\x1f".join("{{%s}}" % f for f in self.FIELDS)
        out = run(*PLAYERCTL, "metadata", "--format", fmt)
        status, title, artist, art, length, pos, vol, player = (out.split("\x1f") + [""] * 8)[:8]
        for b in self.buttons:
            b.set_sensitive(bool(out))
        self.title.set_text(title or ("Unknown" if out else "Nothing playing"))
        self.artist.set_text(artist)
        self.player.set_text(player.capitalize())
        length_s = int(length or 0) / 1e6
        pos_s = int(pos or 0) / 1e6
        if length_s:
            pos_s = min(pos_s, length_s)
        # A stream has no length: nothing to seek in
        self.seek.set_sensitive(bool(length_s))
        self.seek.set_range(0, max(length_s, 1))
        self.seek.set_value(pos_s if length_s else 0)
        self.pos.set_text(fmt_time(pos_s) if out else "")
        self.length.set_text(fmt_time(length_s) if length_s else ("live" if out else ""))
        self.volume.set_opacity(1 if vol else 0)
        self.volume.set_sensitive(bool(vol))
        if not vol:
            self.show_volume(False)
        else:
            level = float(vol)
            icon = ICON["volume" if level > 0 else "muted"]
            for b in (self.volume, self.mute):
                b.get_child().get_children()[0].set_text(icon)
            self.vol.set_value(level * 100)
            self.percent.set_text(f"{round(level * 100)}%")
            css(self.vol, "off", on=level == 0)
        self.play.get_child().get_children()[0].set_text(
            ICON["pause"] if status == "Playing" else ICON["play"])
        self.set_art(art or None)
        return True

    def show_volume(self, on):
        if self.back_timer:
            GLib.source_remove(self.back_timer)
            self.back_timer = None
        self.lines.set_visible_child_name("volume" if on else "progress")
        if on:
            self.back_timer = GLib.timeout_add(self.VOLUME_MS, lambda: self.show_volume(False))
        return False

    def scrolled(self, _w, event):
        ok, _dx, dy = event.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(event.get_scroll_direction()[1], 0)
        if dy:
            self.set_volume(max(0.0, min(1.0, self.vol.get_value() / 100 - dy * 0.05)))
            self.refresh()
        return True

    def set_volume(self, level):
        if level > 0:
            self.unmuted = level
        run(*PLAYERCTL, "volume", f"{level:.2f}")
        # Still being moved: stays on screen
        if self.lines.get_visible_child_name() == "volume":
            self.show_volume(True)

    def toggle_mute(self):
        level = self.vol.get_value() / 100
        if level > 0:
            self.unmuted = level
        self.set_volume(0 if level > 0 else self.unmuted)
        self.refresh()

    def set_art(self, url):
        if url == self.art_url:
            return
        self.art_url = url
        if not url:
            self.cover.load(None)
        elif url.startswith("file://"):
            self.cover.load(urllib.parse.unquote(url[7:]))
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
        GLib.idle_add(lambda: self.art_url == url and self.cover.load(path))


# ------------------------------------------------- calendar + notifications

NOTIFICATIONS = os.path.join(os.path.dirname(PANEL), "notifications.py")


def visible_notifications():
    """The ones the notification server kept (notifications.py), newest
    first; it leaves out volume and the like."""
    try:
        return json.loads(run(NOTIFICATIONS, "history") or "[]")
    except json.JSONDecodeError:
        return []


class Month(Gtk.Box):
    """Today in large, and a month at a time: always six weeks of cells of
    one size, so changing months moves nothing; today in the accent color.
    Scrolling over the days changes the month too."""

    MONTHS = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")
    WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")  # Sunday first
    CELL = 30  # a square: today's mark sits evenly around its number

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        today = self.today = datetime.date.today()
        self.pack_start(label(self.WEEKDAYS[today.weekday()], ["muted"]), False, False, 0)
        self.pack_start(label(f"{today.day} {self.MONTHS[today.month - 1]} {today.year}", ["today-big"]),
                        False, False, 0)

        nav = Gtk.Box(spacing=2, margin_top=10, margin_bottom=4)
        nav.pack_start(icon_button("left", css=["small"], on_click=lambda: self.move(-1)), False, False, 0)
        self.title = label(css=["month"], xalign=0.5, width=14)
        nav.pack_start(self.title, False, False, 0)
        nav.pack_start(icon_button("right", css=["small"], on_click=lambda: self.move(1)), False, False, 0)
        self.back = Gtk.Button(label="Today")
        css(self.back, "small")
        self.back.connect("clicked", lambda _: self.show(today.year, today.month))
        nav.pack_end(self.back, False, False, 0)
        self.pack_start(nav, False, False, 0)

        grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True, column_spacing=10, row_spacing=2)
        for col, name in enumerate(self.DAYS):
            grid.attach(label(name, ["weekday"], xalign=0.5), col, 0, 1, 1)
        self.cells = []
        for row in range(6):
            for col in range(7):
                cell = label(xalign=0.5)
                cell.set_size_request(self.CELL, self.CELL)
                css(cell, "day")
                grid.attach(cell, col, row + 1, 1, 1)
                self.cells.append(cell)
        days = Gtk.EventBox()
        days.add(grid)
        days.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        days.connect("scroll-event", self.scrolled)
        self.pack_start(days, False, False, 0)
        self.show(today.year, today.month)

    def show(self, year, month):
        self.year, self.month = year, month
        self.title.set_text(f"{self.MONTHS[month - 1]} {year}")
        self.back.set_sensitive((year, month) != (self.today.year, self.today.month))
        first = datetime.date(year, month, 1)
        start = first - datetime.timedelta(days=(first.weekday() + 1) % 7)
        for i, cell in enumerate(self.cells):
            day = start + datetime.timedelta(days=i)
            cell.set_text(str(day.day))
            css(cell, "other", on=day.month != month)
            css(cell, "today", on=day == self.today)

    def move(self, step):
        month = self.year * 12 + self.month - 1 + step
        self.show(month // 12, month % 12 + 1)

    def scrolled(self, _w, event):
        ok, _dx, dy = event.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(event.get_scroll_direction()[1], 0)
        if dy:
            self.move(1 if dy > 0 else -1)
        return True


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
        self.month = Month()
        self.right.pack_start(self.month, False, False, 0)
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
        run(NOTIFICATIONS, "clear")
        run(NOTIFICATIONS, "dismiss", "all")
        self.fill([])


# ---------------------------------------------------------- general menu

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


class VolumeLine(Gtk.Box):
    """A mute button, a thin slider and the percent, like the media
    popup's volume line. While it is dragged, the server's echo of the
    change is ignored, so the knob doesn't jump back under the pointer."""

    def __init__(self, icons, on_volume, on_mute):
        super().__init__(spacing=10)
        self.icons = icons  # (sound, muted)
        self.on_volume = on_volume
        self.touched = 0.0
        self.mute = icon_button(icons[0], css=["vol-icon"], on_click=on_mute)
        self.slider = css(hslider(0, 100, self.moved), "thin")
        self.percent = label(css=["muted", "small"], xalign=1.0, width=4)
        self.pack_start(self.mute, False, False, 0)
        self.pack_start(self.slider, True, True, 0)
        self.pack_start(self.percent, False, False, 0)

    def moved(self, value):
        self.touched = time.monotonic()
        self.percent.set_text(f"{int(value)}%")
        self.on_volume(value)

    def set(self, volume, muted):
        if time.monotonic() - self.touched > 1:
            self.slider.set_value(min(volume, 100))
            self.percent.set_text(f"{volume}%")
        self.mute.get_child().get_children()[0].set_text(ICON[self.icons[muted]])
        self.mute.set_tooltip_text("Unmute" if muted else "Mute")
        css(self.slider, "off", on=muted)


class SoundCard(Gtk.Box):
    """The output or the input in use, in a card of a fixed size: which
    one it is (clicked: the others to pick from) and its volume; the input
    also has a meter of what it hears."""

    def __init__(self, kind, on_pick):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        css(self, "device-card")
        self.kind = kind  # "sink" or "source"
        self.device = None
        pick = css(Gtk.Button(), "device-main")
        pick.set_size_request(-1, 44)
        pick.connect("clicked", lambda _: on_pick(kind))
        inner = Gtk.Box(spacing=10)
        self.icon = label(css=["icon"], xalign=0.5, width=2)
        inner.pack_start(self.icon, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.title = label(css=["device-title"], ellipsize=True)
        self.port = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.title, False, False, 0)
        names.pack_start(self.port, False, False, 0)
        inner.pack_start(names, True, True, 0)
        inner.pack_end(label(ICON["right"], ["icon", "muted"], xalign=1.0), False, False, 0)
        pick.add(inner)
        self.pack_start(pick, False, False, 0)

        self.volume = VolumeLine(("volume", "muted") if kind == "sink" else ("mic", "mic-off"),
                                 self.set_volume, self.toggle_mute)
        self.volume.set_margin_start(12)
        self.volume.set_margin_end(12)
        self.volume.set_margin_bottom(4 if kind == "source" else 10)
        self.pack_start(self.volume, False, False, 0)
        if kind == "source":
            self.meter = css(Gtk.LevelBar(min_value=0, max_value=1), "thin")
            for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
                self.meter.remove_offset_value(offset)
            self.meter.set_margin_start(12)
            self.meter.set_margin_end(12)
            self.meter.set_margin_bottom(10)
            self.pack_start(self.meter, False, False, 0)

    def update(self, d):
        self.device = d
        self.volume.set_sensitive(bool(d))
        if not d:
            self.icon.set_text(ICON["volume" if self.kind == "sink" else "mic"])
            self.title.set_text("No output found" if self.kind == "sink" else "No microphone found")
            self.port.set_text("Is it plugged in?")
            self.volume.set(0, True)
            return
        self.icon.set_text(ICON[d["icon"]])
        self.title.set_text(d["title"])
        self.port.set_text(d["port"])
        self.volume.set(d["volume"], d["mute"])

    def set_volume(self, value):
        if self.device:
            audio.set_volume(self.kind, self.device["name"], value)

    def toggle_mute(self):
        if self.device:
            self.device["mute"] = not self.device["mute"]
            audio.set_mute(self.kind, self.device["name"], self.device["mute"])
            self.volume.set(self.device["volume"], self.device["mute"])


class AppRow(Gtk.Box):
    """An app playing or recording: its volume, and a way to bring it to
    the output (or input) in use when it is on another one."""

    HEIGHT = 40

    def __init__(self):
        super().__init__(spacing=10)
        self.set_size_request(-1, self.HEIGHT)
        self.stream = None
        self.target = None
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.app = label(ellipsize=True, width=13)
        self.where = label(css=["muted", "small"], ellipsize=True, width=15)
        names.pack_start(self.app, False, False, 0)
        names.pack_start(self.where, False, False, 0)
        self.pack_start(names, False, False, 0)
        self.volume = VolumeLine(("volume", "muted"), self.set_volume, self.toggle_mute)
        self.pack_start(self.volume, True, True, 0)
        # Its room is kept when there is nothing to move
        self.move = icon_button("move", css=["vol-icon"], on_click=self.bring)
        self.pack_start(self.move, False, False, 0)

    def update(self, s, device, target):
        """device: the title of the one it is on; target: the device in use,
        when it is another one."""
        self.stream, self.target = s, target
        playing = s["kind"] == "sink-input"
        self.app.set_text(s["app"])
        # Where it is when that's not the device in use (the arrows bring it)
        self.where.set_text(device if target else "Playing" if playing else "Recording")
        self.where.set_tooltip_text(f"On {device}" if device else None)
        self.volume.icons = ("volume", "muted") if playing else ("mic", "mic-off")
        self.volume.set(s["volume"], s["mute"])
        self.move.set_opacity(1 if target else 0)
        self.move.set_sensitive(bool(target))
        self.move.set_tooltip_text(f"Move to {target['title']}" if target else None)

    def set_volume(self, value):
        audio.set_stream_volume(self.stream["kind"], self.stream["index"], value)

    def toggle_mute(self):
        self.stream["mute"] = not self.stream["mute"]
        audio.set_stream_mute(self.stream["kind"], self.stream["index"], self.stream["mute"])
        self.volume.set(self.stream["volume"], self.stream["mute"])

    def bring(self):
        if self.target:
            audio.move(self.stream["kind"], self.stream["index"], self.target["name"])


class GainRow(Gtk.Box):
    """One of the microphone's own capture volumes."""

    HEIGHT = 24

    def __init__(self, on_change):
        super().__init__(spacing=10)
        self.set_size_request(-1, self.HEIGHT)
        self.touched = 0.0
        self.on_change = on_change
        self.name = label(ellipsize=True, width=10)
        self.slider = css(hslider(0, 100, self.moved), "thin")
        self.percent = label(css=["muted", "small"], xalign=1.0, width=4)
        self.pack_start(self.name, False, False, 0)
        self.pack_start(self.slider, True, True, 0)
        self.pack_start(self.percent, False, False, 0)

    def moved(self, value):
        self.touched = time.monotonic()
        self.percent.set_text(f"{int(value)}%")
        self.on_change(self.key, value)

    def update(self, g):
        self.key = g["key"]
        self.name.set_text(g["name"])
        if time.monotonic() - self.touched > 1:
            self.slider.set_value(g["percent"])
            self.percent.set_text(f"{g['percent']}%")


def scroll_room(child, height):
    """A ScrolledWindow of a fixed height: what it holds can grow inside."""
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.add(child)
    scroll.set_min_content_height(height)
    scroll.set_max_content_height(height)
    return scroll


def section(title, side=None):
    """A heading (and something small on its right) over what follows."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    top = Gtk.Box(spacing=8)
    top.pack_start(label(title, ["heading"]), False, False, 0)
    if side:
        top.pack_end(side, False, False, 0)
    box.pack_start(top, False, False, 0)
    return box


class Sound(Gtk.Stack):
    """Sound page of the general menu (also opened by the speaker and mic on
    the bar): the output and input in use with their volumes, a meter of
    the microphone and its hardware gains, the volume of each app, and
    buttons that fix the usual problems.

    Everything has a room of its own: picking another device slides to a
    list of the same height, apps come and go in a room that scrolls, and
    what a fix did shows in place of its buttons. While on screen it
    follows the sound server (devices plugged, volume keys...) and the
    meter listens."""

    APP_ROWS = 3  # whole apps that fit before scrolling
    GAIN_ROWS = 2
    DONE_MS = 8000  # what a fix did, then the buttons again

    def __init__(self, on_back):
        super().__init__(homogeneous=True, transition_duration=200)
        self.set_size_request(320, -1)
        self.active = False
        self.queued = False
        self.unsubscribe = None
        self.meter_proc = None
        self.meter_for = None  # (source, muted) the meter listens to
        self.picking = "sink"
        self.found = {"sink": [], "source": []}
        self.apps_rows = {}  # (kind, index): AppRow
        self.gain_rows = []
        self.done_timer = None
        self.connect("destroy", lambda _: self.unsubscribe and self.unsubscribe())
        self.connect("destroy", lambda _: self.stop_meter())

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main.pack_start(page_title("SOUND", on_back), False, False, 0)
        test = css(Gtk.Button(label="Test"), "small")
        test.set_tooltip_text("Play a test sound")
        test.connect("clicked", lambda _: audio.test_sound())
        out = section("OUTPUT", test)
        self.output = SoundCard("sink", self.pick)
        out.pack_start(self.output, False, False, 0)
        main.pack_start(out, False, False, 0)

        self.signal = label(css=["muted", "small"], xalign=1.0, ellipsize=True)
        inp = section("INPUT", self.signal)
        self.input = SoundCard("source", self.pick)
        inp.pack_start(self.input, False, False, 0)
        main.pack_start(inp, False, False, 0)

        # The device's own capture volumes, under PipeWire's: one stuck at 0%
        # silences the microphone whatever the input volume says
        gain = section("MIC GAIN")
        self.gains = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.no_gain = label("This microphone has none of its own", ["muted", "small"])
        self.gains.pack_start(self.no_gain, False, False, 0)
        gain.pack_start(scroll_room(self.gains, self.GAIN_ROWS * (GainRow.HEIGHT + 4)), False, False, 0)
        main.pack_start(gain, False, False, 0)

        apps = section("APPS")
        self.apps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.no_apps = label("Nothing is playing or recording", ["muted", "small"])
        self.apps.pack_start(self.no_apps, False, False, 0)
        apps.pack_start(scroll_room(self.apps, self.APP_ROWS * (AppRow.HEIGHT + 4)), False, False, 0)
        main.pack_start(apps, False, False, 0)

        # The fixes, and in their place what they did
        self.fixes = Gtk.Stack(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=150)
        buttons = Gtk.Box(spacing=8, homogeneous=True)
        restart = Gtk.Button(label="Restart audio")
        restart.connect("clicked", lambda _: self.restart())
        buttons.pack_start(restart, True, True, 0)
        fix = css(Gtk.Button(label="Fix microphone"), "yes")
        fix.connect("clicked", lambda _: self.fix())
        buttons.pack_start(fix, True, True, 0)
        self.fixes.add_named(buttons, "buttons")
        working = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.spinner = Spinner()
        working.pack_start(self.spinner, False, False, 0)
        working.pack_start(label("Restarting the sound server…", ["muted"]), False, False, 0)
        self.fixes.add_named(working, "working")
        done = Gtk.Box(spacing=8)
        self.done = label(css=["small"], ellipsize=True)
        self.done.set_line_wrap(True)
        self.done.set_lines(2)
        self.done.set_valign(Gtk.Align.CENTER)
        done.pack_start(self.done, True, True, 0)
        ok = css(Gtk.Button(label="OK", valign=Gtk.Align.CENTER), "small")
        ok.connect("clicked", lambda _: self.fixes.set_visible_child_name("buttons"))
        done.pack_end(ok, False, False, 0)
        self.fixes.add_named(done, "done")
        main.pack_start(self.fixes, False, False, 0)
        self.add_named(main, "main")

        # Another device to use: a list in the page's whole height
        picker = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.pick_title = page_title("OUTPUT", lambda: self.show("main"))
        picker.pack_start(self.pick_title, False, False, 0)
        self.choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.choices_seen = None
        scroll = scroll_room(self.choices, 0)
        scroll.set_max_content_height(-1)
        scroll.set_vexpand(True)
        picker.pack_start(scroll, True, True, 0)
        self.add_named(picker, "pick")
        self.show_all()
        self.refresh()

    # ------------------------------------------------------------ on screen

    def activate(self):
        self.active = True
        self.unsubscribe = self.unsubscribe or audio.subscribe(lambda: GLib.idle_add(self.changed))
        self.refresh()

    def deactivate(self):
        self.active = False
        if self.unsubscribe:
            self.unsubscribe()
            self.unsubscribe = None
        self.stop_meter()
        self.show("main", animate=False)

    def changed(self):
        # A volume dragged sends a stream of events: one refresh for them
        if not self.queued:
            self.queued = True
            GLib.timeout_add(200, self.refresh)
        return False

    def show(self, page, animate=True):
        self.set_transition_type(Gtk.StackTransitionType.NONE if not animate else
                                 Gtk.StackTransitionType.SLIDE_LEFT if page == "pick" else
                                 Gtk.StackTransitionType.SLIDE_RIGHT)
        self.set_visible_child_name(page)

    def refresh(self):
        self.queued = False
        self.found = {kind: audio.devices(kind) for kind in ("sink", "source")}
        current = {kind: next((d for d in found if d["default"]), None) for kind, found in self.found.items()}
        self.output.update(current["sink"])
        self.input.update(current["source"])
        self.fill_choices()
        self.show_gains(current["source"])
        self.show_apps(current)
        source = current["source"]
        if self.active and (source and (source["name"], source["mute"])) != self.meter_for:
            self.start_meter(source)
        return False

    # ------------------------------------------------------------- devices

    def pick(self, kind):
        self.picking = kind
        self.pick_title.get_child().get_children()[1].set_text("OUTPUT" if kind == "sink" else "INPUT")
        self.choices_seen = None
        self.fill_choices()
        self.show("pick")

    def fill_choices(self):
        found = self.found[self.picking]
        seen = [(d["name"], d["title"], d["port"], d["default"]) for d in found]
        if seen == self.choices_seen:
            return
        self.choices_seen = seen
        for c in self.choices.get_children():
            self.choices.remove(c)
        if not found:
            self.choices.pack_start(label("None found", ["muted", "small"]), False, False, 0)
        for d in found:
            b = css(Gtk.Button(), "device-main", "device-card")
            b.set_size_request(-1, DeviceRow.HEIGHT)
            row = Gtk.Box(spacing=10)
            row.pack_start(label(ICON[d["icon"]], ["icon"], xalign=0.5, width=2), False, False, 0)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            title = label(d["title"], ellipsize=True)
            css(title, "device-title", on=d["default"])
            names.pack_start(title, False, False, 0)
            names.pack_start(label(d["port"], ["muted", "small"], ellipsize=True), False, False, 0)
            row.pack_start(names, True, True, 0)
            row.pack_end(label(ICON["check"] if d["default"] else "", ["icon"], xalign=1.0, width=2),
                         False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _, n=d["name"]: self.use(n))
            self.choices.pack_start(b, False, False, 0)
        self.choices.show_all()

    def use(self, name):
        audio.set_default(self.picking, name)
        self.refresh()
        self.show("main")

    # --------------------------------------------------------- gains, apps

    def show_gains(self, source):
        found = audio.gains(source)
        self.no_gain.set_visible(not found)
        while len(self.gain_rows) < len(found):
            row = GainRow(lambda key, v: self.input.device and audio.tune_gain(self.input.device, key, v))
            row.show_all()
            self.gains.pack_start(row, False, False, 0)
            self.gain_rows.append(row)
        while len(self.gain_rows) > len(found):
            self.gains.remove(self.gain_rows.pop())
        for row, g in zip(self.gain_rows, found):
            row.update(g)

    def show_apps(self, current):
        titles = {d["index"]: d["title"] for found in self.found.values() for d in found}
        streams = sorted(audio.streams(), key=lambda s: (s["kind"] != "sink-input", s["index"]))
        self.no_apps.set_visible(not streams)
        keep = set()
        for i, s in enumerate(streams):
            key = (s["kind"], s["index"])
            row = self.apps_rows.get(key)
            if not row:
                row = self.apps_rows[key] = AppRow()
                row.show_all()
                self.apps.pack_start(row, False, False, 0)
            self.apps.reorder_child(row, i + 1)
            target = current["sink" if s["kind"] == "sink-input" else "source"]
            elsewhere = target and s["device"] != target["index"]
            row.update(s, titles.get(s["device"], ""), target if elsewhere else None)
            keep.add(key)
        for key in set(self.apps_rows) - keep:
            self.apps.remove(self.apps_rows.pop(key))

    # -------------------------------------------------------- level meter

    def start_meter(self, source):
        self.stop_meter()
        self.meter_for = source and (source["name"], source["mute"])
        self.input.meter.set_value(0)
        if not source:
            self.signal.set_text("")
            return
        self.signal.set_text("Muted" if source["mute"] else "Listening…")
        self.meter_proc = proc = audio.level_stream(source["name"])
        threading.Thread(target=self.listen, args=(proc, source["mute"]), daemon=True).start()

    def stop_meter(self):
        self.meter_for = None
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
            GLib.idle_add(self.show_level, proc, level, silent, muted)

    def show_level(self, proc, level, silent, muted):
        if proc is not self.meter_proc:
            return False
        self.input.meter.set_value(level)
        if not muted:
            text = "Silent: check its gain" if silent else "Hearing you" if level > 0.3 else "Listening…"
            if self.signal.get_text() != text:
                self.signal.set_text(text)
        return False

    # --------------------------------------------------------------- fixes

    def tell(self, lines):
        """What a fix did, in place of the buttons for a while (all of it
        in the tooltip when it doesn't fit)."""
        self.done.set_text(" · ".join(lines))
        self.done.set_tooltip_text("\n".join(lines))
        self.fixes.set_visible_child_name("done")
        if self.done_timer:
            GLib.source_remove(self.done_timer)

        def back():
            self.done_timer = None
            self.fixes.set_visible_child_name("buttons")
        self.done_timer = GLib.timeout_add(self.DONE_MS, lambda: back() or False)

    def fix(self):
        self.tell(audio.fix())
        self.refresh()

    def restart(self):
        self.stop_meter()
        self.signal.set_text("")
        self.fixes.set_visible_child_name("working")
        self.spinner.start()

        def work():
            audio.restart()
            GLib.idle_add(finished)

        def finished():
            self.spinner.stop()
            self.refresh()
            self.tell(["Sound server restarted"])
            return False

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
        return "off or out of reach"
    if "profile-unavailable" in low:
        return "no sound profile (restart audio on the Sound page)"
    if "authentication" in low or "rejected" in low or "canceled" in low:
        return "pairing was refused or cancelled"
    return err


class DeviceRow(Gtk.Stack):
    """One device as a card of a fixed height. Forgetting it and pairing
    it (the code to check) happen inside the card, in place of its name,
    so nothing around it moves."""

    HEIGHT = 48

    def __init__(self, on_use, on_forget):
        super().__init__(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                         transition_duration=150)
        self.set_size_request(-1, self.HEIGHT)
        self.device = None
        self.reply = None

        card = css(Gtk.Box(), "device-card")
        self.main = css(Gtk.Button(), "device-main")
        inner = Gtk.Box(spacing=10)
        self.icon = label(css=["icon"], xalign=0.5, width=2)
        inner.pack_start(self.icon, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.name = label(ellipsize=True)
        self.status = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.name, False, False, 0)
        names.pack_start(self.status, False, False, 0)
        inner.pack_start(names, True, True, 0)
        self.main.add(inner)
        self.main.connect("clicked", lambda _: on_use(self.device))
        card.pack_start(self.main, True, True, 0)
        self.trash = icon_button("trash", css=["device-side"], on_click=lambda: self.set_visible_child_name("forget"))
        self.trash.set_tooltip_text("Forget this device")
        card.pack_end(self.trash, False, False, 0)
        self.add_named(card, "main")

        # "Forget X?" with a way out
        self.question = label(css=["title"], ellipsize=True)
        forget, _ = self.choice(self.question, "Forget", "danger",
                                lambda ok: on_forget(self.device) if ok else self.back())
        self.add_named(forget, "forget")
        # "Pair with X?" and the code both sides must show
        pair_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.pair_title = label(css=["title"], ellipsize=True)
        self.pair_code = label(css=["muted", "small"], ellipsize=True)
        pair_text.pack_start(self.pair_title, False, False, 0)
        pair_text.pack_start(self.pair_code, False, False, 0)
        pair, self.pair_ok = self.choice(pair_text, "Pair", "yes", self.answer)
        self.add_named(pair, "pair")

    def choice(self, text, yes, yes_css, on_answer):
        card = css(Gtk.Box(spacing=6), "device-card", "asking")
        card.pack_start(text, True, True, 0)
        no = css(Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER), "small")
        no.connect("clicked", lambda _: on_answer(False))
        ok = css(Gtk.Button(label=yes, valign=Gtk.Align.CENTER), "small", yes_css)
        ok.connect("clicked", lambda _: on_answer(True))
        card.pack_end(ok, False, False, 0)
        card.pack_end(no, False, False, 0)
        return card, ok

    def update(self, d, status, error=None):
        """status: the second line; error: the whole story, in its tooltip."""
        self.device = d
        self.icon.set_text(ICON[BT_ICON.get(d["icon"], "bluetooth")])
        self.name.set_text(d["name"])
        css(self.name, "device-title", on=d["connected"])
        self.status.set_text(status)
        self.status.set_tooltip_text(error)
        css(self.status, "error", on=bool(error))
        self.main.set_sensitive(not status.endswith("…"))
        self.trash.set_visible(d["paired"])
        self.question.set_text(f"Forget {d['name']}?")
        if not d["paired"] and self.get_visible_child_name() == "forget":
            self.back()

    def ask(self, kind, code, reply):
        """A pairing request for this device: a code to check (reply with
        True/False), or one to type on the device (reply is None)."""
        self.reply = reply
        self.pair_title.set_text(f"Pair with {self.device['name']}?" if kind == "confirm"
                                 else f"Type {code} on it")
        self.pair_code.set_text(f"Code {code} on both" if kind == "confirm" and code else
                                "then Enter" if kind == "show" else "It asks to pair")
        # Typing the code on the device: nothing to answer but Cancel
        self.pair_ok.set_visible(kind == "confirm")
        self.set_visible_child_name("pair")

    def answer(self, ok):
        if self.reply:
            self.reply(ok)
        elif not ok and self.device:
            bluetooth.cancel_pairing(self.device["path"])
        self.reply = None
        self.back()

    def back(self):
        self.set_visible_child_name("main")


class Bluetooth(Gtk.Box):
    """Bluetooth page of the general menu: turn it on and off, connect the
    paired devices (with their battery), and pair new ones nearby. Searches
    for devices, and answers pairing requests, only while the page is on
    screen.

    The devices sit in a room of a fixed height (it scrolls past that):
    devices found while searching, or one paired or forgotten, move
    nothing else on the page."""

    ROWS = 6  # whole cards that fit before scrolling

    def __init__(self, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_size_request(320, -1)
        self.on_back = on_back
        self.active = False
        self.agent = None
        self.busy = {}  # device path: "Connecting…"
        self.errors = {}  # device path: what went wrong last time
        self.rows = {}  # device path: DeviceRow
        self.queued = False

        self.pack_start(page_title("BLUETOOTH", on_back), False, False, 0)
        toggle = Gtk.Box(spacing=10)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        names.pack_start(label("Bluetooth"), False, False, 0)
        self.visible_as = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.visible_as, False, False, 0)
        toggle.pack_start(names, True, True, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", lambda s, _: self.set_power(s.get_active()))
        toggle.pack_end(self.switch, False, False, 0)
        self.pack_start(toggle, False, False, 0)

        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        lists.pack_start(label("MY DEVICES", ["heading"]), False, False, 0)
        self.paired = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.no_paired = label("No paired devices yet", ["muted", "small"])
        self.paired.pack_start(self.no_paired, False, False, 0)
        lists.pack_start(self.paired, False, False, 0)
        top = Gtk.Box(spacing=8, margin_top=10)
        top.pack_start(label("OTHER DEVICES", ["heading"]), False, False, 0)
        self.spinner = Spinner()
        top.pack_start(self.spinner, False, False, 0)
        lists.pack_start(top, False, False, 0)
        self.nearby = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.no_nearby = label("Put the device in pairing mode", ["muted", "small"])
        self.nearby.pack_start(self.no_nearby, False, False, 0)
        lists.pack_start(self.nearby, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(lists)
        height = 2 * 30 + self.ROWS * (DeviceRow.HEIGHT + 4)
        scroll.set_min_content_height(height)
        scroll.set_max_content_height(height)
        # Off: a word in the same room
        self.room = Gtk.Stack(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.room.add_named(scroll, "on")
        self.off_text = label(css=["muted"], xalign=0.5)
        self.room.add_named(self.off_text, "off")
        self.pack_start(self.room, False, False, 0)

        # A pairing request from a device that is not in the lists
        self.prompt = DeviceRow(lambda d: None, lambda d: None)
        self.prompt.set_no_show_all(True)
        self.pack_start(self.prompt, False, False, 0)

        bluetooth.watch(self.changed)
        self.connect("destroy", lambda _: self.deactivate())
        self.room.show_all()
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
        self.off_text.set_text("Bluetooth is off" if adapter else "No Bluetooth adapter")
        self.room.set_visible_child_name("on" if on else "off")
        (self.spinner.start if on and adapter.get("Discovering") else self.spinner.stop)()
        devices = bluetooth.devices() if on else []

        paired = sorted((d for d in devices if d["paired"]), key=lambda d: (not d["connected"], d["name"].lower()))
        # Only devices with a name: the rest are beacons and the like
        nearby = sorted((d for d in devices if not d["paired"] and d["named"]),
                        key=lambda d: -(d["rssi"] if d["rssi"] is not None else -999))[:8]
        keep = set()
        for box, found, empty in ((self.paired, paired, self.no_paired), (self.nearby, nearby, self.no_nearby)):
            empty.set_visible(not found)
            for i, d in enumerate(found):
                row = self.rows.get(d["path"])
                if not row:
                    row = self.rows[d["path"]] = DeviceRow(self.use, self.forget)
                    row.show_all()
                if row.get_parent() is not box:
                    if row.get_parent():
                        row.get_parent().remove(row)
                    box.pack_start(row, False, False, 0)
                box.reorder_child(row, i + 1)
                row.update(d, *self.status(d))
                keep.add(d["path"])
        for path in set(self.rows) - keep:
            row = self.rows.pop(path)
            row.get_parent().remove(row)
        return False

    def status(self, d):
        """The second line of a card, and what went wrong (or None)."""
        if d["path"] in self.busy:
            return self.busy[d["path"]], None
        if d["path"] in self.errors:
            reason, story = self.errors[d["path"]]
            return reason[0].upper() + reason[1:], story
        if d["connected"]:
            return "Connected" + (f" · {d['battery']}% battery" if d["battery"] is not None else ""), None
        return ("Not connected" if d["paired"] else "Click to pair"), None

    # ------------------------------------------------------------- actions

    def set_power(self, on):
        bluetooth.set_powered(on)
        if on and self.active:
            bluetooth.discover(True)
        self.refresh()

    def use(self, d):
        path, name = d["path"], d["name"]
        self.errors.pop(path, None)
        for row in self.rows.values():
            if row.get_visible_child_name() == "forget":
                row.back()
        if d["connected"]:
            self.busy[path] = "Disconnecting…"
            bluetooth.disconnect(path, lambda err: self.done(path, err, "disconnect"))
        elif d["paired"]:
            self.busy[path] = "Connecting…"
            bluetooth.connect(path, lambda err: self.done(path, err, "connect"))
        else:
            self.busy[path] = "Pairing…"
            bluetooth.pair(path, lambda err: self.done(path, err, "pair"))
        self.refresh()

    def done(self, path, err, verb):
        self.busy.pop(path, None)
        row = self.rows.get(path)
        if row and row.get_visible_child_name() == "pair":
            row.back()
        self.prompt.hide()
        if err:
            reason = bt_reason(err)
            self.errors[path] = reason, f"Couldn't {verb}: {reason}"
        self.refresh()

    def forget(self, d):
        self.errors.pop(d["path"], None)
        bluetooth.forget(d["path"])
        self.rows[d["path"]].back()
        self.refresh()

    # ------------------------------------------------------------- pairing

    def ask(self, kind, name, code, reply):
        if not kind:
            for row in list(self.rows.values()) + [self.prompt]:
                if row.get_visible_child_name() == "pair":
                    row.reply = None
                    row.back()
            self.prompt.hide()
            return
        row = next((r for r in self.rows.values() if r.device and r.device["name"] == name), None)
        if not row:
            row = self.prompt
            row.update({"path": "", "name": name, "icon": "", "paired": False, "connected": False}, "")
            row.set_no_show_all(False)
            row.show_all()
        row.ask(kind, code, reply)


# --------------------------------------------------------------------- VPN

def vpn_kind(p):
    if p["kind"] == "openconnect":
        return dict(vpn.PROTOCOLS).get(p.get("protocol"), "OpenConnect")
    return {"wireguard": "WireGuard", "openvpn": "OpenVPN"}.get(p["kind"], p["kind"])


def size_text(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class VpnRow(Gtk.Stack):
    """One VPN as a card of a fixed height: a click connects or disconnects
    it. Forgetting it asks first, inside the card."""

    HEIGHT = 48

    def __init__(self, on_use, on_forget):
        super().__init__(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                         transition_duration=150)
        self.set_size_request(-1, self.HEIGHT)
        self.profile = None

        card = css(Gtk.Box(), "device-card")
        self.main = css(Gtk.Button(), "device-main")
        inner = Gtk.Box(spacing=10)
        self.icon = label(ICON["vpn"], ["icon"], xalign=0.5, width=2)
        inner.pack_start(self.icon, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.name = label(ellipsize=True)
        self.status = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.name, False, False, 0)
        names.pack_start(self.status, False, False, 0)
        inner.pack_start(names, True, True, 0)
        self.main.add(inner)
        self.main.connect("clicked", lambda _: on_use(self.profile))
        card.pack_start(self.main, True, True, 0)
        self.trash = icon_button("trash", css=["device-side"], on_click=lambda: self.set_visible_child_name("forget"))
        self.trash.set_tooltip_text("Forget this VPN")
        card.pack_end(self.trash, False, False, 0)
        self.add_named(card, "main")

        self.question = label(css=["title"], ellipsize=True)
        forget, _ = DeviceRow.choice(self, self.question, "Forget", "danger",
                                     lambda ok: on_forget(self.profile) if ok else self.back())
        self.add_named(forget, "forget")

    def update(self, p, status, active, error=None):
        self.profile = p
        self.name.set_text(p["name"])
        css(self.name, "device-title", on=active)
        css(self.icon, "device-title", on=active)
        self.status.set_text(status)
        self.status.set_tooltip_text(error)
        css(self.status, "error", on=bool(error))
        self.question.set_text(f"Forget {p['name']}?")

    def back(self):
        self.set_visible_child_name("main")


class ChosenApp(Gtk.Box):
    """One of the apps that always use the VPN, as a card of a fixed height:
    a click opens it through the VPN; the trash takes it off the list."""

    def __init__(self, app_id, on_open, on_remove):
        super().__init__()
        css(self, "device-card")
        self.set_size_request(-1, VpnRow.HEIGHT)
        self.app_id = app_id
        self.main = css(Gtk.Button(), "device-main")
        inner = Gtk.Box(spacing=10)
        self.icon = Gtk.Image(pixel_size=20)
        inner.pack_start(self.icon, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.name = label(ellipsize=True)
        self.status = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.name, False, False, 0)
        names.pack_start(self.status, False, False, 0)
        inner.pack_start(names, True, True, 0)
        self.main.add(inner)
        self.main.connect("clicked", lambda _: on_open(app_id))
        self.pack_start(self.main, True, True, 0)
        trash = icon_button("trash", css=["device-side"], on_click=lambda: on_remove(app_id))
        trash.set_tooltip_text("Stop using the VPN for it")
        self.pack_end(trash, False, False, 0)

    def update(self, status):
        """status: the VPN's, to tell where the app is."""
        info = vpn.app_info(self.app_id)
        name, icon, exe = info or (self.app_id.removesuffix(".desktop"), None, "")
        self.name.set_text(name)
        if icon:
            self.icon.set_from_gicon(icon, Gtk.IconSize.LARGE_TOOLBAR)
        else:
            self.icon.set_from_icon_name("application-x-executable", Gtk.IconSize.LARGE_TOOLBAR)
        on = bool(status) and status["state"] in ("on", "connecting")
        inside = bool(exe) and any(a["name"] == exe[:15] for a in (status or {}).get("apps", []))
        out = not inside and bool(exe) and bool(vpn.outside(exe))
        text = ("Not installed anymore" if not info else
                "Open, in the VPN" if inside else
                "Open outside the VPN: close it and open it here" if out else
                "Click to open it through the VPN" if on else
                "Opens through the VPN once one is on")
        self.status.set_text(text)
        self.status.set_tooltip_text(text)
        css(self.status, "error", on=out)
        css(self.name, "device-title", on=inside)


class VpnForm(Gtk.Box):
    """Adding a VPN: a file (WireGuard .conf, OpenVPN .ovpn) or one from
    GNOME's settings, or an OpenConnect server. Everything has its room up
    front: the login fields are there, greyed out, when a file needs none."""

    def __init__(self, on_done):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.on_done = on_done
        self.source = None
        self.auto_name = ""

        tabs = Gtk.Box(spacing=4, homogeneous=True)
        self.tabs = {}
        for key, text in (("file", "From a file"), ("openconnect", "OpenConnect")):
            b = css(Gtk.Button(label=text), "tab")
            b.connect("clicked", lambda _, k=key: self.show_tab(k))
            tabs.pack_start(b, True, True, 0)
            self.tabs[key] = b
        self.pack_start(tabs, False, False, 0)
        self.pages = Gtk.Stack(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE)

        # A file: the ones found (3 slots), or any path
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.found = []
        for _ in range(3):
            b = css(Gtk.Button(), "device-main", "device-card")
            b.add(label(ellipsize=True))
            b.connect("clicked", lambda btn: self.pick(btn.source))
            page.pack_start(b, False, False, 0)
            self.found.append(b)
        self.path = self.entry("File: ~/Downloads/vpn.conf")
        self.path.connect("changed", lambda e: self.typed_path(e.get_text()))
        page.pack_start(self.path, False, False, 0)
        self.file_name = self.entry("Name")
        page.pack_start(self.file_name, False, False, 0)
        self.file_user, self.file_password, login = self.login()
        page.pack_start(login, False, False, 0)
        self.pages.add_named(page, "file")

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.oc_name = self.entry("Name")
        page.pack_start(self.oc_name, False, False, 0)
        self.server = self.entry("Server: vpn.example.com")
        page.pack_start(self.server, False, False, 0)
        self.protocol = Gtk.ComboBoxText()
        for key, text in vpn.PROTOCOLS:
            self.protocol.append(key, text)
        self.protocol.set_active_id("anyconnect")
        page.pack_start(self.protocol, False, False, 0)
        self.oc_user, self.oc_password, login = self.login()
        page.pack_start(login, False, False, 0)
        self.pages.add_named(page, "openconnect")
        self.pack_start(self.pages, True, True, 0)

        bottom = Gtk.Box(spacing=6)
        self.error = label(css=["error", "small"], ellipsize=True)
        bottom.pack_start(self.error, True, True, 0)
        cancel = css(Gtk.Button(label="Cancel"), "small")
        cancel.connect("clicked", lambda _: self.on_done())
        add = css(Gtk.Button(label="Add"), "small", "yes")
        add.connect("clicked", lambda _: self.add())
        bottom.pack_end(add, False, False, 0)
        bottom.pack_end(cancel, False, False, 0)
        self.pack_start(bottom, False, False, 0)
        self.show_tab("file")

    def entry(self, hint):
        e = css(Gtk.Entry(placeholder_text=hint), "search")
        e.connect("activate", lambda _: self.add())
        return e

    def login(self):
        row = Gtk.Box(spacing=6, homogeneous=True)
        user = self.entry("Username")
        password = self.entry("Password")
        password.set_visibility(False)
        row.pack_start(user, True, True, 0)
        row.pack_start(password, True, True, 0)
        return user, password, row

    def show_tab(self, key):
        self.tab = key
        for k, b in self.tabs.items():
            css(b, "on", on=k == key)
        self.pages.set_visible_child_name(key)
        self.error.set_text("")

    def reset(self):
        """Fresh, with what there is to import now."""
        self.source = None
        self.auto_name = ""
        for e in (self.path, self.file_name, self.file_user, self.file_password,
                  self.oc_name, self.server, self.oc_user, self.oc_password):
            e.set_text("")
        self.needs_login(False)
        found = vpn.candidates(len(self.found))
        for b, item in zip(self.found, found + [None] * len(self.found)):
            b.source = item[2] if item else None
            b.get_child().set_text(f"{item[0]}  ·  {item[1]}" if item else "")
            b.set_sensitive(bool(item))
            b.set_opacity(1 if item else 0)
        self.show_tab("file")

    def needs_login(self, on):
        for e in (self.file_user, self.file_password):
            e.set_sensitive(on)

    def pick(self, source):
        if not source:
            return
        kind, login = vpn.kind_of(source)
        self.source = source if kind else None
        self.needs_login(login)
        self.error.set_text("" if kind else "Not a WireGuard or OpenVPN config")
        name = os.path.splitext(os.path.basename(source[1]))[0]
        # The name follows the pick, unless one was typed
        if self.file_name.get_text() in ("", self.auto_name):
            self.file_name.set_text(name)
        self.auto_name = name
        for b in self.found:
            css(b, "picked", on=b.source == source)

    def typed_path(self, text):
        path = os.path.expanduser(text.strip())
        if os.path.isfile(path):
            self.pick(("file", path))

    def add(self):
        if self.tab == "file":
            if not self.source:
                self.error.set_text("Pick a file first")
                return
            err = vpn.import_source(self.source, self.file_name.get_text().strip(),
                                    self.file_user.get_text().strip(), self.file_password.get_text())
        else:
            err = vpn.add_openconnect(self.oc_name.get_text().strip(), self.server.get_text().strip(),
                                      self.protocol.get_active_id(), self.oc_user.get_text().strip(),
                                      self.oc_password.get_text())
        if err:
            self.error.set_text(err[0].upper() + err[1:])
            self.error.set_tooltip_text(err)
        else:
            self.on_done()


class Vpn(Gtk.Box):
    """VPN page of the general menu: whether one is on and its traffic, the
    switch, whether the whole system or just chosen apps use it, and the
    VPNs (a click connects one; adding and forgetting happen in place).

    The VPNs sit in a room of a fixed height, which the form to add one
    takes over: nothing else on the page moves."""

    ROWS = 4

    def __init__(self, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_size_request(320, -1)
        self.status = None
        self.rows = {}
        self.active = False
        self.ticking = False

        self.pack_start(page_title("VPN", on_back), False, False, 0)
        top = Gtk.Box(spacing=10)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title = label(ellipsize=True)
        self.detail = label(css=["muted", "small"], ellipsize=True)
        names.pack_start(self.title, False, False, 0)
        names.pack_start(self.detail, False, False, 0)
        top.pack_start(names, True, True, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", lambda s, _: self.toggle(s.get_active()))
        top.pack_end(self.switch, False, False, 0)
        self.pack_start(top, False, False, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(label("USE IT FOR", ["heading"]), False, False, 0)
        modes = Gtk.Box(spacing=4, homogeneous=True)
        self.modes = {}
        for key, text in (("full", "The whole system"), ("apps", "Chosen apps")):
            b = css(Gtk.Button(label=text), "tab")
            b.connect("clicked", lambda _, k=key: self.set_mode(k))
            modes.pack_start(b, True, True, 0)
            self.modes[key] = b
        box.pack_start(modes, False, False, 0)
        # What the mode means, with a way to open apps in apps mode
        self.mode_line = Gtk.Stack(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.mode_line.add_named(label("Every app goes through it", ["muted", "small"]), "full")
        line = Gtk.Box(spacing=6)
        self.apps = label(css=["muted", "small"], ellipsize=True)
        line.pack_start(self.apps, True, True, 0)
        # Swaps the VPNs for the chosen apps, in the same room
        self.opener = css(Gtk.Button(label="Choose apps"), "small")
        self.opener.connect("clicked", lambda _: self.show_apps(self.room.get_visible_child_name() != "apps"))
        line.pack_end(self.opener, False, False, 0)
        self.mode_line.add_named(line, "apps")
        box.pack_start(self.mode_line, False, False, 0)
        self.pack_start(box, False, False, 0)

        head = Gtk.Box()
        self.heading = label("MY VPNS", ["heading"])
        head.pack_start(self.heading, False, False, 0)
        self.add_button = css(Gtk.Button(label="Add"), "small")
        self.add_button.connect("clicked", lambda _: self.add_app() if self.room.get_visible_child_name() == "apps"
                                else self.show_form(True))
        head.pack_end(self.add_button, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.empty = label("No VPNs yet: add one", ["muted", "small"])
        self.list.pack_start(self.empty, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        height = self.ROWS * (VpnRow.HEIGHT + 4)
        scroll.set_min_content_height(height)
        scroll.set_max_content_height(height)
        self.room = Gtk.Stack(homogeneous=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.room.add_named(scroll, "list")
        self.form = VpnForm(on_done=lambda: self.show_form(False))
        self.room.add_named(self.form, "add")
        self.away = label(css=["muted"], xalign=0.5)
        self.away.set_line_wrap(True)
        self.room.add_named(self.away, "away")
        # The apps that always use the VPN (apps mode)
        self.app_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.no_apps = label("None yet. Add the apps that should always use the VPN: they open "
                             "through it from the launcher too", ["muted", "small"])
        self.no_apps.set_line_wrap(True)
        self.app_list.pack_start(self.no_apps, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.app_list)
        self.room.add_named(scroll, "apps")
        self.app_rows = {}
        self.pack_start(self.room, False, False, 0)

        self.room.show_all()
        vpn.watch(self.changed)
        if not self.status:
            self.changed(vpn.status())

    # ------------------------------------------------------------ on screen

    def activate(self):
        self.active = True
        if not self.ticking:
            self.ticking = True
            GLib.timeout_add(1000, self.tick)

    def deactivate(self):
        self.active = False

    def tick(self):
        """The traffic, every second while the page is on screen."""
        if not self.active:
            self.ticking = False
            return False
        if self.status and self.status["state"] == "on":
            s = vpn.status()
            if s:
                self.status = s
                self.top_line()
        return True

    # --------------------------------------------------------------- state

    def changed(self, s):
        self.status = s
        self.top_line()
        if not s:
            self.away.set_text("The VPN service isn't running.\nsudo systemctl start vpnd")
            if self.room.get_visible_child_name() != "add":
                self.room.set_visible_child_name("away")
            for b in self.modes.values():
                b.set_sensitive(False)
            self.add_button.set_sensitive(False)
            return
        for k, b in self.modes.items():
            b.set_sensitive(True)
            css(b, "on", on=k == s["mode"])
        self.add_button.set_sensitive(True)
        self.mode_line.set_visible_child_name(s["mode"])
        n = len(vpn.chosen())
        self.apps.set_text(f"{n} app{'s' if n != 1 else ''} always use{'s' if n == 1 else ''} it" if n else
                           "Only the apps you choose")
        if s["mode"] != "apps" and self.room.get_visible_child_name() == "apps":
            self.show_apps(False)
        if self.room.get_visible_child_name() == "away":
            self.room.set_visible_child_name("list")
        self.fill(s)
        self.fill_apps()

    def top_line(self):
        s = self.status
        with self.switch.handler_block(self.switch_handler):
            self.switch.set_active(bool(s) and s["state"] in ("on", "connecting", "dropped"))
        self.switch.set_sensitive(bool(s and s["profiles"]))
        css(self.detail, "error", on=bool(s) and s["state"] in ("failed", "dropped"))
        self.detail.set_tooltip_text(s["error"] if s and s["error"] else
                                     ", ".join(s["routes"]) if s and s["state"] == "on" else None)
        if not s:
            title, detail = "VPN", "The service isn't running"
        elif s["state"] == "on":
            nets = "the internet" if any(r in ("0.0.0.0/0", "::/0") for r in s["routes"]) else ", ".join(s["routes"])
            title = f"Connected to {s['profile']}"
            detail = f"↓ {size_text(s['rx'])}  ↑ {size_text(s['tx'])}  ·  {nets}"
        elif s["state"] == "connecting":
            title, detail = f"Connecting to {s['profile']}…", vpn_kind(s) if s["kind"] else ""
        elif s["state"] == "dropped":
            title, detail = f"{s['profile']} dropped", "Its traffic is blocked until it's back or off"
        elif s["state"] == "failed":
            title, detail = f"Couldn't connect to {s['profile']}", s["error"]
        else:
            title = "Not connected"
            detail = "Pick a VPN below" if s["profiles"] else "Add a VPN below"
        self.title.set_text(title)
        css(self.title, "device-title", on=bool(s) and s["state"] == "on")
        self.detail.set_text(detail)

    def fill(self, s):
        keep = set()
        for i, p in enumerate(s["profiles"]):
            row = self.rows.get(p["name"])
            if not row:
                row = self.rows[p["name"]] = VpnRow(self.use, self.forget)
                row.show_all()
                self.list.pack_start(row, False, False, 0)
            self.list.reorder_child(row, i + 1)
            mine = p["name"] == s["profile"]
            state = s["state"] if mine else "off"
            error = s["error"] if mine and state in ("failed", "dropped") else None
            text = {"on": "Connected", "connecting": "Connecting…", "dropped": "Dropped: traffic blocked",
                    "failed": f"Failed: {error}"}.get(state, f"{vpn_kind(p)} · {p.get('server', '')}")
            row.update(p, text, state in ("on", "connecting", "dropped"), error)
            keep.add(p["name"])
        for name in set(self.rows) - keep:
            self.list.remove(self.rows.pop(name))
        self.empty.set_visible(not s["profiles"])

    # ------------------------------------------------------------- actions

    def toggle(self, on):
        s = self.status
        if not s:
            return
        if not on:
            vpn.down()
        else:
            names = [p["name"] for p in s["profiles"]]
            name = s["last"] if s["last"] in names else names[0] if names else None
            if name:
                self.report(vpn.up(name))

    def use(self, p):
        s = self.status
        for row in self.rows.values():
            row.back()
        if s and s["profile"] == p["name"] and s["state"] in ("on", "connecting", "dropped"):
            vpn.down()
        else:
            self.report(vpn.up(p["name"]))

    def forget(self, p):
        self.report(vpn.remove(p["name"]))

    def set_mode(self, mode):
        self.report(vpn.set_mode(mode))

    def report(self, err):
        """Errors the daemon answers at once (most come later, in the status)."""
        if err:
            self.title.set_text("Couldn't do it")
            self.detail.set_text(err)
            css(self.detail, "error")

    def show_form(self, on):
        if on:
            self.form.reset()
        self.room.set_visible_child_name("add" if on else "list" if self.status else "away")
        self.add_button.set_sensitive(not on and bool(self.status))
        self.opener.set_sensitive(not on)

    def fill_apps(self):
        ids = vpn.chosen()
        for i, app_id in enumerate(ids):
            row = self.app_rows.get(app_id)
            if not row:
                row = self.app_rows[app_id] = ChosenApp(app_id, self.open_chosen, self.unchoose)
                row.show_all()
                self.app_list.pack_start(row, False, False, 0)
            self.app_list.reorder_child(row, i + 1)
            row.update(self.status)
        for app_id in set(self.app_rows) - set(ids):
            self.app_list.remove(self.app_rows.pop(app_id))
        self.no_apps.set_visible(not ids)

    def show_apps(self, on):
        self.heading.set_text("APPS THAT USE IT" if on else "MY VPNS")
        self.opener.set_label("Done" if on else "Choose apps")
        if on:
            self.fill_apps()
        self.room.set_visible_child_name("apps" if on else "list" if self.status else "away")

    def open_chosen(self, app_id):
        s = self.status
        if not s or s["state"] not in ("on", "connecting"):
            self.report("Turn a VPN on first: it only opens through one")
            return
        vpn.open_chosen(app_id)
        GLib.timeout_add(1500, lambda: self.fill_apps() or False)

    def unchoose(self, app_id):
        vpn.unchoose(app_id)
        self.changed(self.status)

    def add_app(self):
        """The launcher on this panel's display (not the focused one), once
        the panel has closed: what is picked there always uses the VPN."""
        top = self.get_toplevel()
        output = None
        window = top.get_window()
        if window:
            area = Gdk.Display.get_default().get_monitor_at_window(window).get_geometry()
            output = next((o["name"] for o in displays.outputs()
                           if (o["rect"]["x"], o["rect"]["y"]) == (area.x, area.y)), None)
        vpn.add_app(output, os.getpid())
        top.close() if hasattr(top, "revealer") else Gtk.main_quit()


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
        # The main page, and sub pages (Sound, Displays, Bluetooth, VPN) that slide in from the right
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
        self.vpn = None
        if vpn.available():
            self.vpn = Vpn(on_back=lambda: self.show_page("main"))
            self.pages.add_named(self.vpn, "vpn")

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
        if self.vpn:
            v = icon_button("vpn", "VPN", lambda: self.show_page("vpn"))
            v.get_child().pack_end(label(ICON["right"], ["icon", "muted"], xalign=1.0), True, True, 0)
            buttons.pack_start(v, False, False, 0)
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
        if self.vpn:
            (self.vpn.activate if page == "vpn" else self.vpn.deactivate)()

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
        notifications, one with a picture (category "preview": the server
        keeps them, time bar going round, until the preview ends, and out of
        its history)."""
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
                run(NOTIFICATIONS, "dismiss", note)
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
    """Takes the clicks outside the panel, one on each display; the one the
    pointer enters says which display the panel opens on."""

    def __init__(self, monitor):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "bar-panel-backdrop")
        GtkLayerShell.set_monitor(self, monitor)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(self, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        transparent(self)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK)
        self.on_click = Gtk.main_quit
        self.on_enter = lambda _monitor: None
        self.connect("button-press-event", lambda *_: self.on_click())
        self.connect("enter-notify-event", lambda *_: self.on_enter(monitor))


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
        if mode in ("menu", "network", "updates", "sound", "displays", "bluetooth", "vpn"):
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 6 - SHADOW)

        transparent(self)

        self.mode = mode
        self.frame = frame = Gtk.Box()
        frame.get_style_context().add_class("panel")
        self.content = (Menu(mode) if mode in ("sound", "displays", "bluetooth", "vpn") else
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

        self.connect("key-press-event", lambda _w, e: e.keyval == 0xff1b and self.close())
        self.connect("destroy", Gtk.main_quit)

    def place(self, monitor):
        """Puts the panel on the display it was opened from (None: the
        focused one, the compositor's pick)."""
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)
        if self.mode == "media":
            self.frame.show_all()
            monitor = monitor or Gdk.Display.get_default().get_monitor(0)
            screen = monitor.get_geometry().width
            center = (WORKSPACES_WIDTH + screen / 2 - CLOCK_WIDTH / 2) / 2
            width = self.frame.get_preferred_width()[1]
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, max(6, int(center - width / 2)) - SHADOW)

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


MODES = ("media", "calendar", "menu", "network", "updates", "sound", "displays", "bluetooth", "vpn", "wallpaper")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        sys.exit("usage: panel.py " + "|".join(MODES))
    take_over(mode)

    restyle()
    Gtk.StyleContext.add_provider_for_screen(
        Gtk.Window().get_screen(), STYLE, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    panel = Panel(mode)
    # Closed by the bar (same button again): slide up first
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: panel.close(force=True) and False)

    def show(monitor):
        if not panel.get_visible():
            panel.place(monitor)
            panel.show_all()
            GLib.timeout_add(30, panel.open_up)

    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        backdrop = Backdrop(display.get_monitor(i))
        backdrop.on_click = panel.click_outside
        backdrop.on_enter = show
        backdrop.show_all()

    # Opens on the display that was clicked, not the focused one. The
    # pointer only enters a backdrop when it moves, so it gets moved by
    # nothing until it does; no answer, the focused display it is
    started = time.monotonic()

    def nudge():
        if panel.get_visible():
            return False
        if time.monotonic() - started > 0.3:
            show(None)
            return False
        run("swaymsg", "seat - cursor move 0 0")
        return True
    GLib.timeout_add(20, nudge)
    Gtk.main()

    # Clear the pidfile only if it is still ours
    try:
        if open(PIDFILE).read().split()[0] == str(os.getpid()):
            os.remove(PIDFILE)
    except (OSError, IndexError):
        pass


if __name__ == "__main__":
    main()
