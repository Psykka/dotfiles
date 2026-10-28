#!/usr/bin/env python3
"""Notifications: the desktop's notification server (in place of mako), in
the look of the bar popups.

Cards on the top right, newest first, all of the same size whatever they
say: the title on one line, the body on two (one when there are buttons or
a progress bar), the picture in a square. A thin bar along the bottom of a
card shows the time left, and stops while the mouse is on it. Click: the
notification's own action, and it goes; right click: it goes. They slide
in and out; the others slide to make room.

Volume and the like (category "osd") show as a small bar at the bottom of
the screen instead, one at a time. Category "preview" (the wallpaper
preview) never goes: its time bar starts over.

Keeps the last 30 (the calendar panel lists them) while it runs. Colors:
~/.config/waybar/colors.css (`theme`), reloaded when it changes.

Usage: notifications.py daemon          the server (sway starts it)
       notifications.py history         the kept ones, as JSON
       notifications.py dismiss ID|all  close them on screen
       notifications.py clear           forget the kept ones
       notifications.py layout          sizes on screen, as JSON
                                        (dev/notification-sizes.py)
"""
import html
import json
import math
import os
import re
import sys
import time
import warnings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
import cairo  # noqa: E402
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

NAME = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
OWN = "org.dotfiles.Notifications"  # history and the like, for the panels
COLORS = os.path.expanduser("~/.config/waybar/colors.css")

# Room for the tallest card (one body line and a progress bar); the rest
# are centered in it
CARD_W, CARD_H = 340, 84
GAP = 8
MAX = 5  # on screen at once; the rest wait their turn
MARGIN = 8  # from the screen's edges (below the bar)
SHADOW = 24  # transparent room for the shadow, as in panel.py
ICON = 48
TIMEOUT = 5000  # when the app leaves it to the server
KEEP = 30
OSD_W, OSD_H, OSD_TIMEOUT = 240, 48, 1500

XML = f"""
<node>
  <interface name="{NAME}">
    <method name="GetCapabilities"><arg direction="out" type="as"/></method>
    <method name="Notify">
      <arg direction="in" type="s"/><arg direction="in" type="u"/><arg direction="in" type="s"/>
      <arg direction="in" type="s"/><arg direction="in" type="s"/><arg direction="in" type="as"/>
      <arg direction="in" type="a{{sv}}"/><arg direction="in" type="i"/>
      <arg direction="out" type="u"/>
    </method>
    <method name="CloseNotification"><arg direction="in" type="u"/></method>
    <method name="GetServerInformation">
      <arg direction="out" type="s"/><arg direction="out" type="s"/>
      <arg direction="out" type="s"/><arg direction="out" type="s"/>
    </method>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
  </interface>
  <interface name="{OWN}">
    <method name="History"><arg direction="out" type="s"/></method>
    <method name="DismissAll"/>
    <method name="Clear"/>
    <method name="Layout"><arg direction="out" type="s"/></method>
  </interface>
</node>
"""

# Why a notification closed (the spec's numbers)
EXPIRED, DISMISSED, CLOSED = 1, 2, 3

CSS = b"""
window { background: transparent; }
.card {
    background: @surface;
    border-radius: 6px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.32);
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    color: @fg;
    padding: 12px;
}
.osd { padding: 10px; }
.card.critical { box-shadow: inset 3px 0 0 @accent, 0 6px 18px rgba(0, 0, 0, 0.32); }
.title { color: @hi; font-weight: bold; }
.app { color: @mute; font-size: 10px; }
button {
    background: @bg2;
    border: none;
    border-radius: 4px;
    box-shadow: none;
    padding: 2px 10px;
    min-height: 0;
    font-size: 11px;
    color: @fg;
}
button:hover { background: @line; color: @hi; }
levelbar trough { background: @line; border: none; border-radius: 2px; min-height: 4px; padding: 0; }
levelbar block { border: none; border-radius: 2px; min-height: 4px; }
levelbar block.filled { background: @accent; }
levelbar block.empty { background: transparent; }
"""


# ------------------------------------------------------------------ helpers

def markup(text):
    """The body as Pango markup: links and images are left out, and text
    that isn't valid markup is shown as it is."""
    text = re.sub(r"</?(?:a|img)\b[^>]*>", "", text or "")
    try:
        Pango.parse_markup(text, -1, "\0")
        return text
    except GLib.Error:
        return GLib.markup_escape_text(text)


def plain(text):
    return html.unescape(re.sub(r"<[^>]*>", "", text or ""))


def hint_values(variant):
    """The hints as Python values; pictures stay as raw bytes (unpacking
    them makes a list of every byte)."""
    hints = {}
    for i in range(variant.n_children()):
        entry = variant.get_child_value(i)
        key = entry.get_child_value(0).get_string()
        value = entry.get_child_value(1).get_variant()
        if key in ("image-data", "image_data", "icon_data"):
            w, h, stride, alpha, bits, _channels = (value.get_child_value(n).unpack() for n in range(6))
            hints["image-data"] = (w, h, stride, alpha, bits, value.get_child_value(6).get_data_as_bytes())
        else:
            hints[key] = value.unpack()
    return hints


def picture(icon, hints):
    """(pixbuf, is a photo) for the notification, or (None, False).
    Photos fill the square; icons fit inside it."""
    try:
        if "image-data" in hints:
            w, h, stride, alpha, bits, data = hints["image-data"]
            return GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, alpha, bits, w, h, stride), True
        for name in (hints.get("image-path") or hints.get("image_path"), icon):
            if not name:
                continue
            if name.startswith("file://"):
                name = GLib.filename_from_uri(name)[0]
            if name.startswith("/"):
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(name, ICON * 4, ICON * 4, True), True
            theme = Gtk.IconTheme.get_default()
            if theme.has_icon(name):
                return theme.load_icon(name, ICON, Gtk.IconLookupFlags.FORCE_SIZE), False
    except GLib.Error:
        pass
    return None, False


def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def color(widget, name, fallback=(0.5, 0.5, 0.5)):
    found, c = widget.get_style_context().lookup_color(name)
    return (c.red, c.green, c.blue) if found else fallback


def label(text="", css=(), use_markup=False):
    w = Gtk.Label(xalign=0.0)
    (w.set_markup if use_markup else w.set_text)(text)
    for c in css:
        w.get_style_context().add_class(c)
    # Never wider than the card gives it: long text is cut with "…"
    w.set_max_width_chars(1)
    w.set_hexpand(True)
    w.set_ellipsize(Pango.EllipsizeMode.END)
    return w


def transparent(window):
    visual = window.get_screen().get_rgba_visual()
    if visual:
        window.set_visual(visual)
    window.set_app_paintable(True)


# ------------------------------------------------------------------- cards

class Sized(Gtk.Box):
    """A box that is always w×h to GTK, whatever it holds: no text or
    picture can make a card bigger."""

    def __init__(self, w, h, **props):
        super().__init__(**props)
        self.w, self.h = w, h

    def do_get_preferred_width(self):
        return self.w, self.w

    def do_get_preferred_height(self):
        return self.h, self.h

    def do_get_preferred_width_for_height(self, _h):
        return self.w, self.w

    def do_get_preferred_height_for_width(self, _w):
        return self.h, self.h


class Picture(Gtk.DrawingArea):
    """The picture in its square, with rounded corners."""

    def __init__(self, pix, photo):
        super().__init__()
        self.set_size_request(ICON, ICON)
        self.set_valign(Gtk.Align.CENTER)
        self.pix, self.photo = pix, photo
        self.connect("draw", self.draw)

    def draw(self, _w, cr):
        pix = self.pix
        k = (max if self.photo else min)(ICON / pix.get_width(), ICON / pix.get_height())
        w, h = pix.get_width() * k, pix.get_height() * k
        rounded(cr, 0, 0, ICON, ICON, 4)
        cr.clip()
        cr.translate((ICON - w) / 2, (ICON - h) / 2)
        cr.scale(k, k)
        Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
        cr.paint()
        return False


class Card(Gtk.EventBox):
    def __init__(self, server, nid):
        super().__init__()
        self.server, self.id = server, nid
        self.x = self.y = None  # where it is now (it slides to its place)
        self.opacity = 0.0
        self.leaving = False
        self.hovered = False
        self.total = self.left = 0
        self.actions = []
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("enter-notify-event", lambda *_: self.set_hover(True))
        self.connect("leave-notify-event", lambda _w, e: e.detail != Gdk.NotifyType.INFERIOR
                     and self.set_hover(False))
        self.connect("button-press-event", self.click)
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.bar = Gtk.DrawingArea()
        self.bar.connect("draw", self.draw_bar)
        self.bar.set_size_request(CARD_W, CARD_H)
        self.overlay.add(self.bar)
        self.box = None

    def fill(self, app, icon, summary, body, actions, hints, timeout):
        """(Re)writes the card: a replaced notification keeps its place."""
        if self.box:
            self.overlay.remove(self.box)
        self.category = hints.get("category", "")
        self.actions = [(actions[i], actions[i + 1]) for i in range(0, len(actions) - 1, 2)]
        urgency = hints.get("urgency", 1)
        self.total = 0 if (timeout == 0 or (urgency == 2 and timeout < 0)) else (timeout if timeout > 0 else TIMEOUT)
        self.left = self.total

        # Its padding is inside these sizes (CSS)
        box = Sized(CARD_W, CARD_H, spacing=12)
        ctx = box.get_style_context()
        ctx.add_class("card")
        if urgency == 2:
            ctx.add_class("critical")
        pix, photo = picture(icon, hints)
        if pix:
            box.pack_start(Picture(pix, photo), False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_valign(Gtk.Align.CENTER)
        top = Gtk.Box(spacing=8)
        top.pack_start(label(summary or app, ["title"]), True, True, 0)
        if app and summary:
            name = Gtk.Label(label=app, xalign=1.0, max_width_chars=14, ellipsize=Pango.EllipsizeMode.END)
            name.get_style_context().add_class("app")
            top.pack_end(name, False, False, 0)
        text.pack_start(top, False, False, 0)

        buttons = [(k, t) for k, t in self.actions if k != "default"][:3]
        value = hints.get("value")
        extra = bool(buttons) or value is not None
        if body:
            b = label(markup(body), use_markup=True)
            b.set_line_wrap(True)
            b.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            b.set_lines(1 if extra else 2)
            text.pack_start(b, False, False, 0)
        if value is not None:
            level = Gtk.LevelBar(min_value=0, max_value=100, value=max(0, min(100, int(value))))
            for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
                level.remove_offset_value(offset)
            level.set_margin_top(4)
            text.pack_start(level, False, False, 0)
        if buttons:
            row = Gtk.Box(spacing=6, margin_top=2)
            for key, title in buttons:
                bt = Gtk.Button(label=title)
                bt.connect("clicked", lambda _, k=key: self.server.invoke(self.id, k))
                row.pack_start(bt, False, False, 0)
            text.pack_start(row, False, False, 0)
        box.pack_start(text, True, True, 0)
        # The box is drawn under the time bar
        self.overlay.remove(self.bar)
        self.overlay.add(box)
        self.overlay.add_overlay(self.bar)
        self.overlay.set_overlay_pass_through(self.bar, True)
        self.box = box
        self.show_all()

    def set_hover(self, on):
        self.hovered = on
        return False

    def click(self, _w, e):
        if self.category == "preview":
            return True  # only to look at
        if e.button == 1 and any(k == "default" for k, _ in self.actions):
            self.server.invoke(self.id, "default")
        else:
            self.server.close(self.id, DISMISSED)
        return True

    def tick(self, ms):
        """Time passes; False once it is up."""
        if not self.total or self.hovered or self.leaving:
            return True
        self.left -= ms
        self.bar.queue_draw()
        if self.left > 0:
            return True
        if self.category == "preview":
            self.left = self.total
            return True
        return False

    def draw_bar(self, _w, cr):
        """The time left: a thin line along the bottom, inside the corners."""
        if not self.total:
            return False
        rounded(cr, 0, 0, CARD_W, CARD_H, 6)
        cr.clip()
        cr.set_source_rgba(*color(self, "accent"), 0.85)
        cr.rectangle(0, CARD_H - 2, CARD_W * max(0.0, self.left / self.total), 2)
        cr.fill()
        return False


class Stack(Gtk.Window):
    """Every card, in one window of a fixed size: the cards slide inside it,
    and only they take clicks."""

    W = CARD_W + 2 * SHADOW
    H = MAX * (CARD_H + GAP) - GAP + 2 * SHADOW

    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "notifications")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, MARGIN - SHADOW)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, MARGIN - SHADOW)
        transparent(self)
        # A Gtk.Fixed grows to hold a card sliding past its edge; inside a
        # box of a fixed size it can't, and the card is just cut there
        room = Sized(self.W, self.H)
        self.fixed = Gtk.Fixed()
        room.pack_start(self.fixed, True, True, 0)
        self.add(room)
        room.show_all()
        self.moving = False
        self.last = None

    def place(self, cards):
        """Where each card goes; then they slide there."""
        for i, card in enumerate(cards):
            if card.x is None:
                # A new one comes in from the edge of the screen
                card.x, card.y = self.W, SHADOW + i * (CARD_H + GAP)
                self.fixed.put(card, int(card.x), int(card.y))
                card.set_opacity(0)
            card.target = (SHADOW, SHADOW + i * (CARD_H + GAP))
        if cards or self.fixed.get_children():
            self.show()
        self.animate()

    def animate(self):
        if not self.moving:
            self.moving = True
            self.last = None
            self.add_tick_callback(self.step)

    def step(self, _w, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0.016 if self.last is None else min(0.05, now - self.last)
        self.last = now
        k = 1 - math.exp(-dt / 0.06)
        busy = False
        for card in self.fixed.get_children():
            tx, ty = card.target
            card.x += (tx - card.x) * k
            card.y += (ty - card.y) * k
            want = 0.0 if card.leaving else 1.0
            card.opacity += (want - card.opacity) * k
            done = abs(tx - card.x) < 0.5 and abs(ty - card.y) < 0.5 and abs(want - card.opacity) < 0.02
            if done:
                card.x, card.y, card.opacity = tx, ty, want
                if card.leaving:
                    card.destroy()
                    continue
            else:
                busy = True
            self.fixed.move(card, round(card.x), round(card.y))
            card.set_opacity(card.opacity)
        self.clickable()
        if not busy:
            self.moving = False
            if not self.fixed.get_children():
                self.hide()
        return busy

    def clickable(self):
        """Clicks go through the empty room around the cards."""
        win = self.get_window()
        if not win:
            return
        region = cairo.Region()
        for card in self.fixed.get_children():
            if not card.leaving:
                region.union(cairo.RectangleInt(round(card.x), round(card.y), CARD_W, CARD_H))
        win.input_shape_combine_region(region, 0, 0)


class Osd(Gtk.Window):
    """Volume and the like: one small bar at the bottom of the screen; a new
    one replaces it."""

    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "osd")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 72 - SHADOW)
        transparent(self)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=SHADOW)
        card = Sized(OSD_W, OSD_H, orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("card")
        card.get_style_context().add_class("osd")
        self.text = label(css=["title"])
        self.level = Gtk.LevelBar(min_value=0, max_value=100)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.level.remove_offset_value(offset)
        card.pack_start(self.text, False, False, 0)
        card.pack_start(self.level, False, False, 0)
        box.add(card)
        self.add(box)
        box.show_all()
        self.card = card
        self.timer = None
        # Clicks go through it
        self.connect("realize", lambda _: self.get_window().input_shape_combine_region(cairo.Region(), 0, 0))

    def show_value(self, text, value):
        self.text.set_text(text)
        self.level.set_value(max(0, min(100, int(value or 0))))
        self.show()
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(OSD_TIMEOUT, self.done)

    def done(self):
        self.timer = None
        self.hide()
        return False


# ------------------------------------------------------------------ server

class Server:
    def __init__(self):
        self.next_id = 1
        self.cards = []  # newest first
        self.kept = []  # history, newest first
        self.osd = Osd()
        self.osd_id = None
        self.stack = Stack()
        self.info = Gio.DBusNodeInfo.new_for_xml(XML)
        self.bus = None
        self.style = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.style,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.restyle()
        self.monitor = Gio.File.new_for_path(COLORS).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", lambda *_: self.restyle())
        GLib.timeout_add(33, self.tick)

    def restyle(self):
        try:
            colors = open(COLORS, "rb").read()
        except OSError:
            colors = b""
        self.style.load_from_data(colors + CSS)
        for card in self.cards:
            card.queue_draw()

    # ------------------------------------------------------------- D-Bus

    def own(self):
        Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                         self.acquired, None, self.lost)

    def acquired(self, bus, _name):
        self.bus = bus
        with warnings.catch_warnings():
            # The newer call takes GClosures; this one still works
            warnings.simplefilter("ignore", DeprecationWarning)
            for iface in self.info.interfaces:
                bus.register_object(PATH, iface, self.call, None, None)

    def lost(self, _bus, _name):
        sys.exit("notifications: another notification server is running (mako?)")

    def call(self, _bus, _sender, _path, iface, method, params, invocation):
        reply = None
        if method == "GetCapabilities":
            reply = GLib.Variant("(as)", (["actions", "body", "body-markup", "icon-static"],))
        elif method == "GetServerInformation":
            reply = GLib.Variant("(ssss)", ("notifications", "dotfiles", "1.0", "1.2"))
        elif method == "Notify":
            app, replaces, icon, summary, body, actions = (params.get_child_value(i).unpack() for i in range(6))
            hints = hint_values(params.get_child_value(6))
            timeout = params.get_child_value(7).unpack()
            reply = GLib.Variant("(u)", (self.notify(app, replaces, icon, summary, body, actions, hints, timeout),))
        elif method == "CloseNotification":
            self.close(params.unpack()[0], CLOSED)
        elif method == "History":
            reply = GLib.Variant("(s)", (json.dumps(self.kept),))
        elif method == "DismissAll":
            for card in list(self.cards):
                self.close(card.id, DISMISSED)
        elif method == "Clear":
            self.kept = []
        elif method == "Layout":
            reply = GLib.Variant("(s)", (json.dumps(self.layout()),))
        invocation.return_value(reply)

    def signal(self, name, fmt, values):
        if self.bus:
            self.bus.emit_signal(None, PATH, NAME, name, GLib.Variant(fmt, values))

    # ----------------------------------------------------- notifications

    def notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
        if hints.get("category") == "osd":
            self.osd_id = self.osd_id or self.new_id()
            self.osd.show_value(summary, hints.get("value"))
            return self.osd_id
        card = next((c for c in self.cards if c.id == replaces and not c.leaving), None) if replaces else None
        if not card:
            card = Card(self, self.new_id())
            self.cards.insert(0, card)
        card.fill(app, icon, summary, body, actions, hints, timeout)
        if not hints.get("transient") and hints.get("category") != "preview":
            self.kept = [k for k in self.kept if k["id"] != card.id]
            self.kept.insert(0, {"id": card.id, "app_name": app, "summary": plain(summary),
                                 "body": plain(body), "category": hints.get("category", ""),
                                 "time": int(time.time())})
            del self.kept[KEEP:]
        self.relayout()
        return card.id

    def new_id(self):
        self.next_id += 1
        return self.next_id - 1

    def visible(self):
        return [c for c in self.cards if not c.leaving][:MAX]

    def relayout(self):
        self.stack.place(self.visible())

    def close(self, nid, reason):
        card = next((c for c in self.cards if c.id == nid and not c.leaving), None)
        if not card:
            return
        card.leaving = True
        self.cards.remove(card)
        # It slides back out where it came from
        card.target = (Stack.W, card.y)
        self.relayout()
        self.signal("NotificationClosed", "(uu)", (nid, reason))

    def invoke(self, nid, key):
        self.signal("ActionInvoked", "(us)", (nid, key))
        self.close(nid, DISMISSED)

    def tick(self):
        for card in self.visible():
            if not card.tick(33):
                self.close(card.id, EXPIRED)
        return True

    def layout(self):
        def size(w):
            a = w.get_allocation()
            return [a.width, a.height]
        out = {"window": size(self.stack) if self.stack.get_visible() else None,
               "cards": [{"id": c.id, "size": size(c), "box": size(c.box)} for c in self.visible()],
               "osd": size(self.osd.card) if self.osd.get_visible() else None}
        return out


# --------------------------------------------------------------- the CLI

def ask(method, *args):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    iface = NAME if method == "CloseNotification" else OWN
    params = GLib.Variant("(u)", args) if args else None
    out = bus.call_sync(NAME, PATH, iface, method, params, None, Gio.DBusCallFlags.NONE, 2000)
    return out.unpack()[0] if out and out.n_children() else None


def main():
    cmd = sys.argv[1:] or [""]
    if cmd[0] == "daemon":
        Server().own()
        Gtk.main()
    elif cmd[0] in ("history", "layout"):
        print(ask(cmd[0].capitalize()))
    elif cmd[0] == "dismiss" and len(cmd) == 2:
        ask("DismissAll") if cmd[1] == "all" else ask("CloseNotification", int(cmd[1]))
    elif cmd[0] == "clear":
        ask("Clear")
    else:
        sys.exit(__doc__.split("\n\n")[-1])


if __name__ == "__main__":
    main()
