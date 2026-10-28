"""A pretend sound server, with the same calls the Sound page uses from
waybar/.config/waybar/audio.py, to see and test the page with many
devices and apps. dev/panel-sizes.py puts it in place of the real one;
nothing reaches PipeWire (the real apps playing are left alone).

Outputs: speakers, Bluetooth headphones, a monitor with a long name.
Inputs: a built-in mic, a USB mic with two hardware gains, a muted webcam.
Apps: more than fit, one playing on the monitor and one recording from the
webcam (so they can be moved). plug() and unplug(), start() and stop()
make devices and apps come and go, like the real thing.
"""
import subprocess
import sys
import time

from gi.repository import GLib

from audio import dbfs, peak  # noqa: F401  (the meter's, unchanged)

DELAY_MS = 100  # like pactl's events, a moment after the change

watchers = []
DEVICES = {
    "sink": [
        dict(name="speakers", title="Built-in Audio", port="Speakers", icon="volume", volume=40, mute=False),
        dict(name="bt", title="WH-1000XM4", port="Headphones", icon="headphones", volume=65, mute=False),
        dict(name="hdmi", title="Dell U2720Q Monitor With A Very Long Name", port="HDMI / DisplayPort 1",
             icon="display", volume=100, mute=False),
    ],
    "source": [
        dict(name="builtin", title="Built-in Audio", port="Internal Microphone", icon="mic", volume=80,
             mute=False, gains=[["Capture,0", "Capture", 70]]),
        dict(name="yeti", title="Yeti Stereo Microphone", port="Analog Input", icon="mic", volume=100,
             mute=False, gains=[["Capture,0", "Capture", 0], ["Mic Boost,0", "Mic Boost", 0],
                                ["Capture,1", "Capture 1", 50]]),
        dict(name="cam", title="HD Pro Webcam C920", port="", icon="camera", volume=60, mute=True, gains=[]),
    ],
}
default = {"sink": "speakers", "source": "builtin"}
STREAMS = [
    dict(kind="sink-input", index=1, app="Spotify", volume=55, mute=False, device="speakers"),
    dict(kind="sink-input", index=2, app="Firefox", volume=100, mute=False, device="hdmi"),
    dict(kind="source-output", index=3, app="Discord", volume=100, mute=False, device="cam"),
    dict(kind="sink-input", index=4, app="Discord", volume=80, mute=True, device="speakers"),
    dict(kind="sink-input", index=5, app="An Application With A Long Name", volume=30, mute=False,
         device="speakers"),
]
UNPLUGGED = dict(name="usb", title="USB Headset", port="Analog Output", icon="headphones", volume=50, mute=False)


def changed():
    def tell():
        for w in watchers:
            w()
    GLib.timeout_add(DELAY_MS, lambda: tell() or False)


def find(kind, name):
    return next(d for d in DEVICES[kind] if d["name"] == name)


def devices(kind):
    return [{**{k: v for k, v in d.items() if k != "gains"}, "index": d["name"],
             "default": d["name"] == default[kind], "props": {}} for d in DEVICES[kind]]


def set_default(kind, name):
    # Like WirePlumber: the apps on the old default follow it
    for s in STREAMS:
        if s["device"] == default[kind] and s["kind"].startswith("sink" if kind == "sink" else "source"):
            s["device"] = name
    default[kind] = name
    changed()


def set_volume(kind, name, value):
    find(kind, name)["volume"] = int(value)
    changed()


def set_mute(kind, name, on):
    find(kind, name)["mute"] = on
    changed()


def streams():
    return [dict(s) for s in STREAMS]


def stream(kind, index):
    return next(s for s in STREAMS if s["kind"] == kind and s["index"] == index)


def set_stream_volume(kind, index, value):
    stream(kind, index)["volume"] = int(value)
    changed()


def set_stream_mute(kind, index, on):
    stream(kind, index)["mute"] = on
    changed()


def move(kind, index, device):
    stream(kind, index)["device"] = device
    changed()


def gains(source):
    if not source:
        return []
    return [{"key": k, "name": n, "percent": p} for k, n, p in find("source", source["name"]).get("gains", [])]


def tune_gain(source, key, value):
    for g in find("source", source["name"])["gains"]:
        if g[0] == key:
            g[2] = int(value)


def test_sound():
    pass


def restart():
    time.sleep(1)


def fix():
    src = find("source", default["source"])
    done = []
    if src["mute"]:
        src["mute"] = False
        done.append("Unmuted the input")
    for g in src.get("gains", []):
        if g[2] == 0 and "boost" not in g[1].lower():
            g[2] = 80
            done.append(f"Hardware gain '{g[1]}' raised from 0% to 80%")
    for s in STREAMS:
        if s["kind"] == "source-output" and s["device"] != default["source"]:
            s["device"] = default["source"]
            done.append(f"{s['app']} moved to this microphone")
    changed()
    return done or ["Nothing to fix in the settings. If it is still silent, check the headset's own mute switch"]


def level_stream(source, rate=8000):
    """A voice that comes and goes, as raw samples, at its real pace;
    silence from a muted source."""
    loud = 0 if find("source", source)["mute"] else 9000
    code = (f"import math,struct,sys,time\nt=0\nwhile True:\n"
            f" a={loud}*abs(math.sin(t/7))\n"
            f" sys.stdout.buffer.write(struct.pack('<200h',*(int(a*math.sin(i)) for i in range(200))))\n"
            f" sys.stdout.flush(); t+=1; time.sleep(0.025)")
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def subscribe(on_change):
    watchers.append(on_change)
    return lambda: on_change in watchers and watchers.remove(on_change)


# ------------------------------------------------- for panel-sizes' steps

def plug():
    DEVICES["sink"].append(dict(UNPLUGGED))
    changed()


def unplug():
    DEVICES["sink"][:] = [d for d in DEVICES["sink"] if d["name"] != "usb"]
    if default["sink"] == "usb":
        default["sink"] = "speakers"
    changed()


def start(app, kind="sink-input"):
    STREAMS.append(dict(kind=kind, index=max(s["index"] for s in STREAMS) + 1, app=app, volume=100,
                        mute=False, device=default["sink" if kind == "sink-input" else "source"]))
    changed()


def stop(app):
    STREAMS[:] = [s for s in STREAMS if s["app"] != app]
    changed()
