#!/usr/bin/env python3
"""A pretend media player on D-Bus (MPRIS), to try the bar's media island
and its popup (panel.py media) on a machine with nothing playing.

Plays a few made-up tracks: with cover art and without, a title far too
long, a live stream with no length. playerctl (and so the popup) controls
it like any player: play/pause, next/previous, seek, volume. Nothing is
heard. The covers are drawn into $XDG_RUNTIME_DIR.

Usage: dev/fake-player.py            until Ctrl+C
       dev/fake-player.py SECONDS    quits by itself after that long
"""
import os
import sys

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

NAME = "org.mpris.MediaPlayer2.fakeplayer"
PATH = "/org/mpris/MediaPlayer2"
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")

# title, artist, album, seconds (0: a stream), cover colors (None: no art)
TRACKS = [
    ("Northern Lights", "Aurora Fields", "Polar Nights", 214, ((40, 90, 160), (200, 120, 200))),
    ("A Title So Long It Can Never Fit In The Popup, Not Even Close", "Somebody With An Equally Long Name",
     "Album", 3725, ((180, 80, 40), (240, 200, 90))),
    ("No Cover", "Plain Band", "", 95, None),
    ("Radio Stream", "Live", "", 0, ((30, 120, 90), (20, 30, 40))),
]

XML = """<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/><method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/><method name="Previous"/><method name="Pause"/>
    <method name="PlayPause"/><method name="Stop"/><method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/><arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>"""


def cover(i, colors):
    """A diagonal gradient, so the art is easy to tell apart."""
    path = os.path.join(RUNTIME, f"fake-player-{i}.png")
    if not os.path.exists(path):
        (r1, g1, b1), (r2, g2, b2) = colors
        n = 256
        data = bytearray()
        for y in range(n):
            for x in range(n):
                t = (x + y) / (2 * n - 2)
                data += bytes((int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t)))
        pix = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB,
                                              False, 8, n, n, n * 3)
        pix.savev(path, "png", [], [])
    return "file://" + path


class Player:
    def __init__(self, bus):
        self.bus = bus
        self.track = 0
        self.playing = True
        self.volume = 0.6
        self.pos = 0.0  # seconds
        GLib.timeout_add(250, self.tick)

    def metadata(self):
        title, artist, album, length, colors = TRACKS[self.track]
        meta = {
            "mpris:trackid": GLib.Variant("o", f"/fake/track/{self.track}"),
            "xesam:title": GLib.Variant("s", title),
            "xesam:artist": GLib.Variant("as", [artist]),
        }
        if album:
            meta["xesam:album"] = GLib.Variant("s", album)
        if length:
            meta["mpris:length"] = GLib.Variant("x", length * 1_000_000)
        if colors:
            meta["mpris:artUrl"] = GLib.Variant("s", cover(self.track, colors))
        return GLib.Variant("a{sv}", meta)

    def props(self, iface):
        if iface == "org.mpris.MediaPlayer2":
            return {"CanQuit": GLib.Variant("b", True), "CanRaise": GLib.Variant("b", False),
                    "HasTrackList": GLib.Variant("b", False), "Identity": GLib.Variant("s", "Fake Player"),
                    "SupportedUriSchemes": GLib.Variant("as", []), "SupportedMimeTypes": GLib.Variant("as", [])}
        return {
            "PlaybackStatus": GLib.Variant("s", "Playing" if self.playing else "Paused"),
            "LoopStatus": GLib.Variant("s", "None"), "Rate": GLib.Variant("d", 1.0),
            "Shuffle": GLib.Variant("b", False), "Metadata": self.metadata(),
            "Volume": GLib.Variant("d", self.volume), "Position": GLib.Variant("x", int(self.pos * 1e6)),
            "MinimumRate": GLib.Variant("d", 1.0), "MaximumRate": GLib.Variant("d", 1.0),
            **{k: GLib.Variant("b", True) for k in ("CanGoNext", "CanGoPrevious", "CanPlay", "CanPause",
                                                    "CanSeek", "CanControl")},
        }

    def changed(self, *keys):
        iface = "org.mpris.MediaPlayer2.Player"
        props = self.props(iface)
        self.bus.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)", (iface, {k: props[k] for k in keys}, [])))

    def go(self, step):
        self.track = (self.track + step) % len(TRACKS)
        self.pos = 0.0
        self.changed("Metadata", "Position")

    def tick(self):
        length = TRACKS[self.track][3]
        if self.playing:
            self.pos += 0.25
            if length and self.pos >= length:
                self.go(1)
        return True

    def method(self, _bus, _sender, _path, _iface, name, args, call):
        length = TRACKS[self.track][3]
        if name in ("Next", "Previous"):
            self.go(1 if name == "Next" else -1)
        elif name in ("Play", "Pause", "PlayPause", "Stop"):
            self.playing = name == "Play" or (name == "PlayPause" and not self.playing)
            self.changed("PlaybackStatus")
        elif name in ("Seek", "SetPosition"):
            to = args.unpack()[-1] / 1e6 + (self.pos if name == "Seek" else 0)
            self.pos = max(0.0, min(to, length or 0))
            self.bus.emit_signal(None, PATH, "org.mpris.MediaPlayer2.Player", "Seeked",
                                 GLib.Variant("(x)", (int(self.pos * 1e6),)))
        elif name == "Quit":
            GLib.idle_add(loop.quit)
        call.return_value(None)

    def get(self, _bus, _sender, _path, iface, prop):
        return self.props(iface).get(prop)

    def set(self, _bus, _sender, _path, _iface, prop, value):
        if prop == "Volume":
            self.volume = max(0.0, min(1.0, value.unpack()))
            self.changed("Volume")
        return True


loop = GLib.MainLoop()


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    player = Player(bus)
    for iface in Gio.DBusNodeInfo.new_for_xml(XML).interfaces:
        bus.register_object(PATH, iface, player.method, player.get, player.set)
    Gio.bus_own_name_on_connection(bus, NAME, Gio.BusNameOwnerFlags.NONE, None,
                                   lambda *_: sys.exit("fake-player: another one is already running"))
    if sys.argv[1:]:
        GLib.timeout_add(int(float(sys.argv[1]) * 1000), loop.quit)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
