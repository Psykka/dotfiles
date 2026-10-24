#!/usr/bin/env python3
"""Super + scroll: previous / next workspace.

Scrolling past the last workspace opens a new one (up to 6, the ones with
a keybinding), unless the current one is empty. At most one step every
300ms, so one flick of the wheel or a touchpad swipe moves just once.

Usage: workspace-scroll.py prev|next
"""
import json
import os
import subprocess
import sys
import time

LAST = 6
DELAY_MS = 300
STAMP = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "workspace-scroll")


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


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "next"
    if recently_moved():
        return
    out = subprocess.run(["swaymsg", "-t", "get_workspaces"], capture_output=True, text=True).stdout
    spaces = sorted((w for w in json.loads(out) if w["num"] > 0), key=lambda w: w["num"])
    current = next(w for w in json.loads(out) if w["focused"])
    nums = [w["num"] for w in spaces]
    i = nums.index(current["num"]) if current["num"] in nums else 0

    if step == "prev":
        target = nums[i - 1] if i > 0 else None
    elif i + 1 < len(nums):
        target = nums[i + 1]
    else:
        # Last one: open a new workspace, unless this one is still empty
        empty = not current.get("representation") or current["representation"] == "H[]"
        target = current["num"] + 1 if current["num"] < LAST and not empty else None

    if target:
        subprocess.run(["swaymsg", f"workspace number {target}"], stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
