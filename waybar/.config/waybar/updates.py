#!/usr/bin/env python3
"""Pending updates: packages and, on Fedora, a new release.

Usage: updates.py bar            check (at most every 30 min) and print
                                 the Waybar JSON
       updates.py list           the last result as JSON (for the popup)
       updates.py run packages|release
                                 update in a terminal, then check again
       updates.py refresh        check now and refresh the bar

Fedora (dnf, plus new releases from fedoraproject.org), Arch (paru or yay,
so AUR packages count too; else checkupdates from pacman-contrib) and
Debian (apt). The result is cached so the popup
opens at once; the bar icon refreshes through Waybar's signal 8.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

CACHE = os.path.expanduser("~/.cache/updates.json")
MAX_AGE = 25 * 60  # the bar asks every 30 min
ICON = "<span font_size='10pt' rise='-1pt'>\uf1b2</span>"  # a package (cube)


def os_release():
    info = {}
    with open("/etc/os-release") as f:
        for line in f:
            key, _, value = line.strip().partition("=")
            info[key] = value.strip('"')
    return info


def distro():
    info = os_release()
    ids = [info.get("ID", "")] + info.get("ID_LIKE", "").split()
    for d in ("fedora", "arch", "debian"):
        if d in ids or (d == "debian" and "ubuntu" in ids):
            return d, info
    return None, info


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def fedora_packages():
    """What `sudo dnf upgrade` would install: read the system's package
    lists (kept fresh by dnf-makecache.timer and by every sudo dnf run).
    A user's own copy can come from another mirror and disagree with it."""
    system = ["dnf", "check-upgrade", "--quiet", "--cacheonly", "--setopt=cachedir=/var/cache/libdnf5"]
    try:
        r = subprocess.run(system, capture_output=True, text=True, timeout=120)
        lines = r.stdout if r.returncode in (0, 100) else run("dnf", "check-upgrade", "--quiet")
    except (OSError, subprocess.TimeoutExpired):
        lines = run("dnf", "check-upgrade", "--quiet")
    out = []
    for line in lines.splitlines():
        parts = line.split()
        if len(parts) == 3 and "." in parts[0]:
            name = parts[0].rsplit(".", 1)[0]
            out.append({"name": name, "version": parts[1].split(":")[-1]})
    return out


def fedora_release(current):
    """The newest stable Fedora above this one, if there is one."""
    try:
        with urllib.request.urlopen("https://fedoraproject.org/releases.json", timeout=8) as r:
            versions = {int(x["version"]) for x in json.load(r) if str(x.get("version", "")).isdigit()}
    except (OSError, ValueError):
        return None
    newest = max(versions, default=0)
    return str(newest) if current.isdigit() and newest > int(current) else None


def aur_helper():
    return next((h for h in ("paru", "yay") if shutil.which(h)), None)


def arch_packages():
    helper = aur_helper()
    out = []
    lines = run(helper, "-Qu") if helper else run("checkupdates")
    for line in lines.splitlines():
        m = re.match(r"(\S+) \S+ -> (\S+)", line)
        if m:
            out.append({"name": m.group(1), "version": m.group(2)})
    return out


def debian_packages():
    out = []
    for line in run("apt", "list", "--upgradable").splitlines():
        m = re.match(r"([^/\s]+)/\S+ (\S+)", line)
        if m:
            out.append({"name": m.group(1), "version": m.group(2)})
    return out


def check():
    name, info = distro()
    result = {"distro": name, "pretty": info.get("NAME", "Linux"), "release": None,
              "packages": [], "checked": time.time()}
    if name == "fedora":
        result["packages"] = fedora_packages()
        result["release"] = fedora_release(info.get("VERSION_ID", ""))
    elif name == "arch" and (aur_helper() or shutil.which("checkupdates")):
        result["packages"] = arch_packages()
    elif name == "debian":
        result["packages"] = debian_packages()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(result, f)
    return result


def cached():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def bar():
    data = cached()
    if not data or time.time() - data.get("checked", 0) > MAX_AGE:
        data = check()
    count = len(data["packages"])
    if not count and not data["release"]:
        # Kept as a hidden island (style.css), so it can slide away
        print(json.dumps({"text": " ", "class": "none"}))
        return
    text = f"{ICON} {count}" if count else ICON
    if data["release"]:
        text += "  •"  # a dot: a new release is out
    print(json.dumps({"text": text, "class": "release" if data["release"] else "updates"}))


def commands(kind):
    name, _ = distro()
    data = cached() or {}
    if kind == "release" and name == "fedora" and data.get("release"):
        n = data["release"]
        return (f"echo 'Upgrading to Fedora {n}: download everything, then reboot to install.'; echo; "
                f"sudo dnf upgrade --refresh && "
                f"sudo dnf system-upgrade download --releasever={n} && sudo dnf offline reboot")
    return {"fedora": "sudo dnf upgrade --refresh",
            "arch": f"{aur_helper()} -Syu" if aur_helper() else "sudo pacman -Syu",
            "debian": "sudo apt update && sudo apt full-upgrade"}.get(name, "echo 'Unknown distro'")


def refresh():
    check()
    subprocess.run(["pkill", "-RTMIN+8", "-x", "waybar"])


def run_update(kind):
    script = (f"{commands(kind)}; echo; printf 'Done. Press Enter to close.'; read _")
    # The terminal waits for Enter; afterwards, check again and refresh the bar
    subprocess.Popen(["sh", "-c", f"alacritty --title 'System update' -e sh -c \"$1\"; {sys.argv[0]} refresh",
                      "update", script], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "bar"
    if arg == "bar":
        bar()
    elif arg == "list":
        print(json.dumps(cached() or check()))
    elif arg == "refresh":
        refresh()
    elif arg == "run" and len(sys.argv) > 2:
        run_update(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
