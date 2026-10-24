#!/usr/bin/env python3
"""Bar popups: mini media player, calendar + notifications, general menu.

Usage: panel.py media|calendar|menu
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
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

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
}

CSS = b"""
window { background: transparent; }
.panel {
    background: #1a1a1a;
    border-radius: 6px;
    padding: 16px;
    font-family: "JetBrains Mono", monospace;
    font-size: 13px;
    color: #d0d0d0;
}
.icon { font-family: "Font Awesome 6 Free"; font-weight: 900; }
.title { color: #ffffff; font-weight: bold; }
.muted { color: #777777; }
.heading { color: #777777; font-size: 11px; }
.art { background: #222222; border-radius: 4px; color: #777777; font-size: 22px; }

button {
    background: transparent;
    border: none;
    border-radius: 4px;
    box-shadow: none;
    padding: 6px 10px;
    color: #d0d0d0;
}
button:hover { background: #2c2c2c; color: #ffffff; }
button.yes { background: #e8e8e8; color: #121212; }
button.ctl { min-width: 40px; min-height: 32px; padding: 0; font-size: 14px; }
button.ctl.main { min-width: 48px; font-size: 18px; }
scale { padding: 0; margin: 0; }

scale.pill trough { border-radius: 8px; background: #2c2c2c; }
scale.pill highlight { border-radius: 8px; background: #e8e8e8; }
scale.horizontal-pill trough { min-height: 28px; }
scale.horizontal-pill highlight { min-height: 28px; min-width: 34px; }
scale.vertical-pill trough { min-width: 28px; }
scale.vertical-pill highlight { min-width: 28px; min-height: 34px; }
scale.pill.off highlight { background: #555555; }
scale.pill slider {
    min-width: 0;
    min-height: 0;
    margin: 0;
    background: transparent;
}
.pill-icon { color: #121212; font-size: 12px; margin-left: 11px; }
.pill-icon.bottom { margin: 0 0 10px 0; }

scale trough {
    background: #2c2c2c;
    border: none;
    border-radius: 2px;
    min-height: 4px;
}
scale highlight { background: #d0d0d0; border: none; border-radius: 2px; }
scale slider {
    background: #e8e8e8;
    border: none;
    border-radius: 6px;
    box-shadow: none;
    min-width: 12px;
    min-height: 12px;
    margin: -4px;
}

combobox button, combobox box {
    background: #222222;
    border: none;
    box-shadow: none;
}

.notif { background: #222222; border-radius: 4px; padding: 8px 10px; }

calendar {
    background: transparent;
    border: none;
    color: #d0d0d0;
    padding: 2px;
}
calendar.header { background: transparent; border: none; }
calendar.button { color: #777777; background: transparent; border: none; }
calendar:selected {
    background: #e8e8e8;
    color: #121212;
    border-radius: 3px;
}
calendar.highlight { color: #777777; }
calendar:indeterminate { color: #444444; }
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


class Calendar(Gtk.Box):
    def __init__(self):
        super().__init__(spacing=20)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(300, -1)
        left.pack_start(label("NOTIFICATIONS", ["heading"]), False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 220)
        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        notes = notifications()
        if not notes:
            items.pack_start(label("No notifications", ["muted"]), False, False, 0)
        for n in notes:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.get_style_context().add_class("notif")
            card.pack_start(label(n.get("app_name") or n.get("app-name") or "", ["muted"], ellipsize=True), False, False, 0)
            card.pack_start(label(n.get("summary") or "", ["title"], ellipsize=True), False, False, 0)
            body = n.get("body") or ""
            if body:
                b = label(body)
                b.set_line_wrap(True)
                b.set_max_width_chars(34)
                card.pack_start(b, False, False, 0)
            items.pack_start(card, False, False, 0)
        scroll.add(items)
        left.pack_start(scroll, True, True, 0)
        self.pack_start(left, True, True, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.pack_start(label("CALENDAR", ["heading"]), False, False, 0)
        right.pack_start(Gtk.Calendar(), False, False, 0)
        self.pack_start(right, False, False, 0)


# ---------------------------------------------------------- general menu

def devices(kind):
    """[(name, description)] for 'sinks' or 'sources', without monitors."""
    try:
        items = json.loads(run("pactl", "--format=json", "list", kind) or "[]")
    except json.JSONDecodeError:
        return []
    return [(d["name"], d.get("description") or d["name"]) for d in items
            if not d["name"].endswith(".monitor")]


class AudioRow(Gtk.Box):
    """Device picker + volume pill (icon toggles mute) for the sink or source."""

    def __init__(self, kind, heading, icon_on, icon_off):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.kind = kind  # "sink" or "source"
        self.icons = (icon_on, icon_off)
        target = f"@DEFAULT_{kind.upper()}@"
        self.pack_start(label(heading, ["heading"]), False, False, 0)

        combo = Gtk.ComboBoxText()
        cell = combo.get_cells()[0]
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        cell.set_property("width-chars", 30)
        default = run("pactl", f"get-default-{kind}")
        for name, desc in devices(kind + "s"):
            combo.append(name, desc)
        combo.set_active_id(default)
        combo.connect("changed", lambda c: run("pactl", f"set-default-{kind}", c.get_active_id()) or self.refresh())
        self.pack_start(combo, False, False, 0)

        self.pill = Pill(icon_on, lambda v: run("pactl", f"set-{kind}-volume", target, f"{int(v)}%"),
                         lambda: run("pactl", f"set-{kind}-mute", target, "toggle") or self.refresh())
        self.pack_start(self.pill, False, False, 0)
        self.refresh()

    def refresh(self):
        target = f"@DEFAULT_{self.kind.upper()}@"
        m = re.search(r"(\d+)%", run("pactl", f"get-{self.kind}-volume", target))
        muted = run("pactl", f"get-{self.kind}-mute", target).endswith("yes")
        self.pill.set(int(m.group(1)) if m else 0, self.icons[muted], muted)


class Menu(Gtk.Box):
    POWER = [
        ("lock", "Lock", ["swaylock", "-f"]),
        ("logout", "Log out", ["swaymsg", "exit"]),
        ("reboot", "Reboot", ["systemctl", "reboot"]),
        ("power", "Power off", ["systemctl", "poweroff"]),
    ]

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.set_size_request(320, -1)
        self.pack_start(AudioRow("sink", "OUTPUT", "volume", "muted"), False, False, 0)
        self.pack_start(AudioRow("source", "INPUT", "mic", "mic-off"), False, False, 0)

        # Power buttons, swapped for a confirmation when one is picked
        # Not homogeneous, so the panel shrinks to the confirmation
        self.stack = Gtk.Stack(vhomogeneous=False, interpolate_size=True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        buttons.pack_start(label("SYSTEM", ["heading"]), False, False, 4)
        buttons.pack_start(icon_button("keyboard", "Keybindings", lambda: self.run_and_quit(
            [os.path.expanduser("~/.config/sway/keys.sh")])), False, False, 0)
        for icon, text, cmd in self.POWER:
            buttons.pack_start(icon_button(icon, text, lambda t=text, c=cmd: self.confirm(t, c)), False, False, 0)
        self.stack.add_named(buttons, "buttons")
        self.confirm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.stack.add_named(self.confirm_box, "confirm")
        self.pack_start(self.stack, False, False, 0)

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
        Gtk.main_quit()


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
        self.connect("button-press-event", lambda *_: Gtk.main_quit())


class Panel(Gtk.Window):
    def __init__(self, mode):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "bar-panel")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 6)
        if mode == "menu":
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 6)

        transparent(self)

        frame = Gtk.Box()
        frame.get_style_context().add_class("panel")
        frame.add({"media": Media, "calendar": Calendar, "menu": Menu}[mode]())
        self.add(frame)

        if mode == "media":
            frame.show_all()
            screen = Gdk.Display.get_default().get_monitor(0).get_geometry().width
            center = (WORKSPACES_WIDTH + screen / 2 - CLOCK_WIDTH / 2) / 2
            width = frame.get_preferred_width()[1]
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, max(6, int(center - width / 2)))

        self.connect("key-press-event", lambda _w, e: e.keyval == 0xff1b and Gtk.main_quit())
        self.connect("destroy", Gtk.main_quit)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("media", "calendar", "menu"):
        sys.exit("usage: panel.py media|calendar|menu")
    take_over(mode)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gtk.Window().get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    Backdrop().show_all()
    Panel(mode).show_all()
    Gtk.main()

    # Clear the pidfile only if it is still ours
    try:
        if open(PIDFILE).read().split()[0] == str(os.getpid()):
            os.remove(PIDFILE)
    except (OSError, IndexError):
        pass


if __name__ == "__main__":
    main()
