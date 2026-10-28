#!/usr/bin/env python3
"""Workspaces per display: each one has its own 1..6.

Super+N goes to workspace N of the focused display. The main display (the
menu's Displays page) holds workspaces "1".."6"; the others, left to right,
hold "11:1".."16:6", "21:1".."26:6", ... (waybar shows just the part after
the colon). The workspaces of an unplugged display wait on another one and
go back when it is plugged in again.

Super + scroll goes to the previous / next workspace of the display;
scrolling past the last opens a new one (up to 6), unless the current one
is empty. At most one step every 300ms, so one flick of the wheel or a
touchpad swipe moves just once.

Usage: workspaces.py go N | move N   go to / move the window to workspace N
       workspaces.py prev | next     previous / next workspace
       workspaces.py arrange         puts every workspace on its display
       workspaces.py watch           arrange, then again on every display change
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.expanduser("~/.config/waybar"))
import displays  # noqa: E402

LAST = 6
DELAY_MS = 300
STAMP = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "workspace-scroll")


def sway(command):
    subprocess.run(["swaymsg", command], stdout=subprocess.DEVNULL)


def quote(name):
    return '"' + name.replace('"', '\\"') + '"'


def name(display, n):
    return str(n) if display == 0 else f"{display * 10 + n}:{n}"


def home(num):
    """Index of the display a workspace number belongs to."""
    return num // 10


def order():
    """Output names (ports), the main display first, then left to right."""
    items = displays.outputs()
    main = displays.primary(items)
    items.sort(key=lambda o: (o["id"] != main, o["rect"]["x"], o["rect"]["y"]))
    return [o["name"] for o in items]


def tree():
    """Workspaces by output: {output: [workspace, ...]}, each workspace with
    "windows" (how many) and "visible"."""
    root = json.loads(subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True, text=True).stdout)
    out = {}
    for o in root["nodes"]:
        if o["name"] == "__i3":
            continue
        out[o["name"]] = [{"name": w["name"], "num": w.get("num", -1), "focused": w["focused"],
                           "visible": w["name"] == o.get("current_workspace"),
                           "windows": len(w["nodes"]) + len(w["floating_nodes"])}
                          for w in o["nodes"] if w["type"] == "workspace"]
    return out


def focused():
    """(output, workspace) with the focus."""
    out = json.loads(subprocess.run(["swaymsg", "-t", "get_workspaces"], capture_output=True, text=True).stdout)
    w = next(w for w in out if w["focused"])
    return w["output"], w


def display_of(output):
    names = order()
    return names.index(output) if output in names else 0


# ------------------------------------------------------------ keybindings

def go(n):
    output, _ = focused()
    sway(f"workspace {quote(name(display_of(output), n))}")


def move(n):
    output, _ = focused()
    sway(f"move container to workspace {quote(name(display_of(output), n))}")


def recently_moved():
    now = time.time_ns() // 1_000_000
    try:
        last = int(open(STAMP).read())
    except (OSError, ValueError):
        last = 0
    # A stamp from the future (clock change, old format) counts as stale
    if 0 <= now - last < DELAY_MS:
        return True
    with open(STAMP, "w") as f:
        f.write(str(now))
    return False


def scroll(step):
    if recently_moved():
        return
    output, current = focused()
    display = display_of(output)
    spaces = sorted((w for w in tree().get(output, []) if w["num"] > 0 and home(w["num"]) == display),
                    key=lambda w: w["num"])
    nums = [w["num"] for w in spaces]
    i = nums.index(current["num"]) if current["num"] in nums else 0

    if step == "prev":
        target = spaces[i - 1]["name"] if i > 0 else None
    elif i + 1 < len(spaces):
        target = spaces[i + 1]["name"]
    else:
        # Last one: open a new workspace, unless this one is still empty
        n = current["num"] - display * 10
        empty = not spaces or spaces[i]["windows"] == 0
        target = name(display, n + 1) if home(current["num"]) == display and n < LAST and not empty else None

    if target:
        sway(f"workspace {quote(target)}")


# ------------------------------------------------------------------ arrange

def arrange():
    names = order()
    if not names:
        return
    before = tree()
    focus = next((w["name"] for ws in before.values() for w in ws if w["focused"]), None)
    shown = {o: next((w["name"] for w in ws if w["visible"]), None) for o, ws in before.items()}

    # Workspaces with windows go to their own display, when it is plugged in
    moved = False
    for output, spaces in before.items():
        for w in spaces:
            d = home(w["num"])
            if w["num"] > 0 and w["windows"] and d < len(names) and names[d] != output:
                sway(f"workspace {quote(w['name'])}; move workspace to output {names[d]}")
                moved = True
    if moved:
        # Back to what each display was showing, where it still is
        now = tree()
        for output, ws in shown.items():
            if ws and any(w["name"] == ws for w in now.get(output, [])):
                sway(f"workspace {quote(ws)}")

    # A display showing an empty workspace of another display (a new display,
    # or one that lost its workspaces) switches to one of its own
    now = tree()
    taken = {w["name"] for ws in now.values() for w in ws}
    for output, spaces in now.items():
        d = names.index(output) if output in names else None
        visible = next((w for w in spaces if w["visible"]), None)
        if d is None or not visible or visible["windows"] or home(visible["num"]) == d:
            continue
        own = sorted((w for w in spaces if w["num"] > 0 and home(w["num"]) == d), key=lambda w: w["num"])
        target = own[0]["name"] if own else next(
            (name(d, n) for n in range(1, LAST + 1) if name(d, n) not in taken), None)
        if target:
            sway(f"focus output {output}; workspace {quote(target)}")
            taken.add(target)
            if focus == visible["name"]:
                focus = target

    if focus and any(w["name"] == focus for ws in tree().values() for w in ws):
        sway(f"workspace {quote(focus)}")


def watch():
    arrange()
    events = subprocess.Popen(["swaymsg", "-t", "subscribe", "-m", '["output"]'],
                              stdout=subprocess.PIPE, text=True)
    for _ in events.stdout:
        arrange()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("go", "move") and len(sys.argv) > 2 and sys.argv[2].isdigit():
        (go if cmd == "go" else move)(int(sys.argv[2]))
    elif cmd in ("prev", "next"):
        scroll(cmd)
    elif cmd == "arrange":
        arrange()
    elif cmd == "watch":
        watch()
    else:
        sys.exit(__doc__.split("\n\n")[-1])


if __name__ == "__main__":
    main()
