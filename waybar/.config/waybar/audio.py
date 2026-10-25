#!/usr/bin/env python3
"""Sound helpers for the menu's Sound page, and the fixes for a microphone
that goes quiet.

Usage: audio.py watch  puts the saved hardware gains back whenever a device
                       returns (started with sway)
       audio.py fix    unmutes the input, raises a hardware gain stuck at 0
                       and moves the apps to the default devices

Some headsets (USB ones especially) come back from a replug or a profile
change with a capture control of their own at 0%: the input looks fine
everywhere but sends pure silence. The gains set in the sound popup (or by
`fix`) are saved per device and put back by `watch`.
"""
import json
import math
import os
import re
import subprocess
import sys
import threading
import time

# Our own recording stream (the Sound page's meter), left out of "an app is
# using the microphone"
CLIENT = "bar-audio"
GAINS = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                     "bar-audio-gains.json")
# Gain a control stuck at 0 is raised to when nothing is saved for it
DEFAULT_GAIN = 80



def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def pactl(kind):
    try:
        return json.loads(run("pactl", "--format=json", "list", kind) or "[]")
    except json.JSONDecodeError:
        return []


def percent(volume):
    """Highest channel of a pactl volume, in %."""
    return max((int(c["value_percent"].rstrip("%")) for c in volume.values()), default=0)


def find(items, name):
    return next((d for d in items if d["name"] == name), None)


def real_sources():
    """Microphones and line inputs, without the outputs' monitors."""
    return [s for s in pactl("sources") if s["properties"].get("device.class") != "monitor"
            and not s["name"].endswith(".monitor")]


def recording(sources=None):
    """Apps recording from a real input: [(source-output index, app, source index)]."""
    ids = {s["index"] for s in (sources or real_sources())}
    out = []
    for o in pactl("source-outputs"):
        p = o["properties"]
        if o["source"] in ids and p.get("application.name") != CLIENT:
            app = p.get("application.process.binary") or p.get("application.name") or "?"
            out.append((o["index"], app.capitalize(), o["source"]))
    return out


# ------------------------------------------------------- hardware gains

def device_key(props):
    """Same name for a device across replugs (its card number may change)."""
    return ":".join(props.get(k, "") for k in ("device.vendor.id", "device.product.id", "alsa.card_name"))


def capture_controls(card):
    """ALSA capture volumes of a card: [{name, index, percent, on}]."""
    out = []
    for block in run("amixer", "-c", str(card), "scontents").split("Simple mixer control ")[1:]:
        m = re.match(r"'(.+)',(\d+)", block)
        caps = re.search(r"Capabilities:(.*)", block)
        if not m or not caps or "cvolume" not in caps.group(1).split():
            continue
        cur = re.search(r"Capture \d+ \[(\d+)%\]([^\n]*)", block)
        if cur:
            out.append({"name": m.group(1), "index": int(m.group(2)),
                        "percent": int(cur.group(1)), "on": "[off]" not in cur.group(2)})
    return out


def load_gains():
    try:
        with open(GAINS) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_gain(key, control, value):
    gains = load_gains()
    gains.setdefault(key, {})[control] = value
    os.makedirs(os.path.dirname(GAINS), exist_ok=True)
    with open(GAINS, "w") as f:
        json.dump(gains, f, indent=2)


def set_gain(card, name, index, value):
    run("amixer", "-q", "-c", str(card), "sset", f"{name},{index}", f"{int(value)}%", "cap")


def restore_gains():
    """Puts the saved gains back on the devices that are plugged in."""
    gains = load_gains()
    for s in real_sources():
        props = s["properties"]
        saved = gains.get(device_key(props))
        if not saved or "alsa.card" not in props:
            continue
        for c in capture_controls(props["alsa.card"]):
            want = saved.get(f"{c['name']},{c['index']}")
            if want is not None and (c["percent"] != want or not c["on"]):
                set_gain(props["alsa.card"], c["name"], c["index"], want)


# ------------------------------------------------------------------ fix

def fix():
    """Everything that usually brings a silent microphone back; returns what
    it changed, one line each."""
    done = []
    sources = real_sources()
    if not sources:
        return ["No microphone found: is it plugged in?"]
    default = find(sources, run("pactl", "get-default-source"))
    if not default:
        default = sources[0]
        run("pactl", "set-default-source", default["name"])
        done.append(f"Input set to {default['properties'].get('device.nick', default['name'])}")
    if default["mute"]:
        run("pactl", "set-source-mute", default["name"], "0")
        done.append("Unmuted the input")
    if percent(default["volume"]) < 20:
        run("pactl", "set-source-volume", default["name"], "100%")
        done.append("Input volume raised to 100%")

    props = default["properties"]
    if "alsa.card" in props:
        key, saved = device_key(props), load_gains().get(device_key(props), {})
        for c in capture_controls(props["alsa.card"]):
            control = f"{c['name']},{c['index']}"
            value = c["percent"]
            # Boosts sit at 0 on purpose; raising them only adds noise
            if value == 0 and "boost" not in c["name"].lower():
                value = saved.get(control) or DEFAULT_GAIN
                done.append(f"Hardware gain '{c['name']}' {c['index']} raised from 0% to {value}%")
            elif not c["on"]:
                done.append(f"Hardware capture '{c['name']}' {c['index']} turned on")
            if value != c["percent"] or not c["on"]:
                set_gain(props["alsa.card"], c["name"], c["index"], value)
            save_gain(key, control, value)

    for index, app, source in recording(sources):
        if source != default["index"]:
            run("pactl", "move-source-output", str(index), default["name"])
            done.append(f"{app} moved to this microphone")
    sink = run("pactl", "get-default-sink")
    sinks = {s["index"]: s["name"] for s in pactl("sinks")}
    for i in pactl("sink-inputs"):
        if sinks.get(i["sink"]) not in (None, sink):
            run("pactl", "move-sink-input", str(i["index"]), sink)
            name = i["properties"].get("application.name", "An app")
            done.append(f"{name} moved to the default output")
    return done or ["Nothing to fix in the settings. If it is still silent, check the headset's own mute switch"]


# ---------------------------------------------------------------- meter

def level_stream(source, rate=8000):
    """Raw mono samples from a source, for a level meter."""
    return subprocess.Popen(["parec", "-d", source, "--raw", "--format=s16le", "--channels=1",
                             f"--rate={rate}", "--latency-msec=50", f"--client-name={CLIENT}",
                             "--stream-name=Level meter"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def peak(chunk):
    if len(chunk) < 2:
        return 0
    samples = memoryview(chunk[: len(chunk) // 2 * 2]).cast("h")
    return max(max(samples), -min(samples))


def dbfs(value):
    """0..1 on a 60 dB scale, for meters."""
    return max(0.0, (20 * math.log10(value / 32768) + 60) / 60) if value else 0.0


# ---------------------------------------------------------------- watch

def watch():
    """Puts the saved gains back each time a card or input comes (back)."""
    devices = threading.Event()

    def subscribe():
        # pactl exits when the sound server restarts; wait for it and resubscribe
        while True:
            p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
            devices.set()
            for line in p.stdout:
                if "'new'" in line and (" card " in line or " source " in line) or \
                        "'change'" in line and " card " in line:
                    devices.set()
            p.wait()
            time.sleep(1)

    threading.Thread(target=subscribe, daemon=True).start()
    while True:
        devices.wait()
        # WirePlumber sets up the mixer right after the device appears;
        # one restore for the whole burst of events
        time.sleep(1.5)
        devices.clear()
        restore_gains()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "watch":
        watch()
    elif mode == "fix":
        print("\n".join(fix()))
    else:
        sys.exit("usage: audio.py watch|fix")


if __name__ == "__main__":
    main()
