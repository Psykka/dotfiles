#!/usr/bin/env python3
"""Display helpers for the menu's Displays page: the main display, the
resolution and scale of each one, and their order side by side.

Usage: displays.py save  writes the current layout (also after changing it
                         in wdisplays), so it comes back at the next login

The main display holds workspace 1 and has the focus at login. Settings are
kept per monitor (make, model and serial, so a monitor keeps them on any
port) in a file sway includes; a monitor that is not plugged in keeps its
line for the next time it is.
"""
import json
import os
import re
import subprocess
import sys

# Included by the sway config: same path there, so no XDG_STATE_HOME here
CONF = os.path.expanduser("~/.local/state/sway-displays.conf")
SCALES = [1, 1.25, 1.5, 1.75, 2]


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def sway(command):
    run("swaymsg", command)


def outputs():
    """Active outputs, each with its config name in "id"."""
    try:
        items = [o for o in json.loads(run("swaymsg", "-t", "get_outputs") or "[]") if o.get("active")]
    except json.JSONDecodeError:
        return []
    ids = [f"{o['make']} {o['model']} {o['serial']}" for o in items]
    for o, ident in zip(items, ids):
        # Two identical monitors without serials can't be told apart: the port then
        o["id"] = ident if ids.count(ident) == 1 else o["name"]
    return items


def title(o):
    if o["name"].startswith(("eDP", "LVDS", "DSI")):
        return "Built-in display"
    model = o["model"] if o["model"] not in ("", "Unknown") else ""
    return f"{o['make']} {model}".strip() if o["make"] not in ("", "Unknown") else o["name"]


def mode_text(m):
    return f"{m['width']}×{m['height']} · {round(m['refresh'] / 1000)} Hz"


def modes(o):
    """Distinct modes, largest and fastest first."""
    seen, out = set(), []
    for m in sorted(o["modes"], key=lambda m: (-m["width"] * m["height"], -m["refresh"])):
        key = (m["width"], m["height"], m["refresh"])
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def quote(ident):
    return '"' + ident.replace('"', '\\"') + '"'


# ------------------------------------------------------------ main display

def saved_primary():
    try:
        m = re.search(r'^workspace 1 output "(.*)"$', open(CONF).read(), re.M)
    except OSError:
        return None
    return m.group(1).replace('\\"', '"') if m else None


def primary(items=None):
    """Id of the main display: the saved one when plugged in, else the one
    holding workspace 1."""
    items = items if items is not None else outputs()
    saved = saved_primary()
    if any(o["id"] == saved for o in items):
        return saved
    try:
        ws = json.loads(run("swaymsg", "-t", "get_workspaces") or "[]")
    except json.JSONDecodeError:
        ws = []
    holder = next((w["output"] for w in ws if w["name"] == "1"), None)
    return next((o["id"] for o in items if o["name"] == holder), items[0]["id"] if items else None)


def set_primary(ident):
    items = outputs()
    target = next((o for o in items if o["id"] == ident), None)
    if not target:
        return
    sway(f"workspace 1 output {quote(ident)}")
    try:
        ws = json.loads(run("swaymsg", "-t", "get_workspaces") or "[]")
    except json.JSONDecodeError:
        ws = []
    one = next((w for w in ws if w["name"] == "1"), None)
    if one and one["output"] != target["name"]:
        back = next((w["name"] for w in ws if w["focused"]), "1")
        sway(f"workspace number 1; move workspace to output {quote(target['name'])}; "
             f"workspace {quote(back)}")
    save(ident)


# ------------------------------------------------------ resolution, scale

def resize(ident, setting):
    """Applies a setting that changes an output's size, then moves the ones
    to its right (or below) by as much, so they still touch it."""
    before = outputs()
    old = next((o["rect"] for o in before if o["id"] == ident), None)
    if not old:
        return
    # Every output pinned where it is first: sway re-places the ones without
    # a position of their own whenever the layout changes
    sway("; ".join([f"output {quote(o['id'])} pos {o['rect']['x']} {o['rect']['y']}" for o in before]
                   + [f"output {quote(ident)} {setting}"]))
    new = next((o["rect"] for o in outputs() if o["id"] == ident), old)
    dx, dy = new["width"] - old["width"], new["height"] - old["height"]
    moves = []
    for o in before:
        r = o["rect"]
        x = r["x"] + dx if o["id"] != ident and r["x"] >= old["x"] + old["width"] else r["x"]
        y = r["y"] + dy if o["id"] != ident and r["y"] >= old["y"] + old["height"] else r["y"]
        if (x, y) != (r["x"], r["y"]):
            moves.append(f"output {quote(o['id'])} pos {max(0, x)} {max(0, y)}")
    if moves:
        sway("; ".join(moves))
    save()


def set_scale(ident, scale):
    resize(ident, f"scale {scale}")


def set_mode(ident, m):
    resize(ident, f"mode {m['width']}x{m['height']}@{m['refresh'] / 1000:.3f}Hz")


def move(ident, step):
    """Swaps an output with its neighbour on the left (-1) or right (+1),
    then lines them all up side by side."""
    items = sorted(outputs(), key=lambda o: o["rect"]["x"])
    i = next((n for n, o in enumerate(items) if o["id"] == ident), None)
    if i is None or not 0 <= i + step < len(items):
        return
    items[i], items[i + step] = items[i + step], items[i]
    x = 0
    for o in items:
        sway(f"output {quote(o['id'])} pos {x} {o['rect']['y']}")
        x += o["rect"]["width"]
    save()


# -------------------------------------------------------------------- save

def line(o):
    m = o["current_mode"]
    out = (f"output {quote(o['id'])} mode {m['width']}x{m['height']}@{m['refresh'] / 1000:.3f}Hz "
           f"pos {o['rect']['x']} {o['rect']['y']} scale {o['scale']:g}")
    if o.get("transform", "normal") != "normal":
        out += f" transform {o['transform']}"
    return out


def save(main=None):
    """Writes every active output as it is now, keeping the lines of the
    monitors that are not plugged in."""
    items = outputs()
    # A main display that is unplugged right now stays the main one
    main = main or saved_primary() or primary(items)
    try:
        old = open(CONF).read().splitlines()
    except OSError:
        old = []
    current = {quote(o["id"]) for o in items}
    kept = [l for l in old if l.startswith("output ") and
            re.match(r'output ("(?:[^"\\]|\\.)*"|\S+)', l).group(1) not in current]
    lines = ["# Written by ~/.config/waybar/displays.py (the menu's Displays page)"]
    lines += kept + [line(o) for o in items]
    if main:
        lines += ["", "# Main display: workspace 1, focused at login",
                  f"workspace 1 output {quote(main)}", "exec swaymsg workspace number 1"]
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "save":
        save()
    else:
        sys.exit("usage: displays.py save")


if __name__ == "__main__":
    main()
