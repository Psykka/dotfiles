#!/usr/bin/env python3
"""The VPN daemon (vpn/ in the dotfiles, vpnd.service) for the menu's VPN
page: its status, and connecting, importing and removing VPNs. Talks to the
daemon's socket, one JSON request per connection, like the `vpn` command.

dev/fake_vpn.py has the same calls, for tests without the daemon.

Usage: vpn.py bar             the bar's shield, one JSON line per change:
                              shown only while a VPN is on (or connecting,
                              or dropped)
       vpn.py run -- APP...   APP through the VPN (the launcher's prefix
                              for the chosen apps)
       vpn.py choose -- APP   remember APP (fuzzel's DESKTOP_ENTRY_ID) as
                              one that always uses the VPN, and open it
"""
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time

from gi.repository import GLib

SOCKET = os.environ.get("VPN_SOCKET", "/run/vpn/vpnd.sock")
# openconnect's --protocol names, as the page lists them
PROTOCOLS = [("anyconnect", "Cisco AnyConnect"), ("gp", "GlobalProtect"), ("fortinet", "Fortinet"),
             ("pulse", "Pulse / Ivanti"), ("nc", "Juniper"), ("f5", "F5"), ("array", "Array")]

watchers = []
_watch = {"sock": None, "source": None, "buffer": b""}


def available():
    """Is the daemon installed (it may be stopped)?"""
    return bool(shutil.which("vpn"))


def call(request):
    """(status, None) or (None, error)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(SOCKET)
            s.sendall(json.dumps(request).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        answer = json.loads(data)
    except (OSError, ValueError):
        return None, "The VPN service isn't running"
    return answer.get("status"), answer.get("error")


def status():
    return call({"cmd": "status"})[0]


def watch(fn):
    """fn(status) on every change; status is None while the daemon is away."""
    watchers.append(fn)
    if not _watch["sock"]:
        _connect()


def _connect():
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCKET)
        s.sendall(b'{"cmd": "watch"}\n')
    except OSError:
        _notify(None)
        GLib.timeout_add_seconds(5, lambda: _connect() and False)
        return
    _watch.update(sock=s, buffer=b"")
    _watch["source"] = GLib.io_add_watch(s, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, _read)


def _read(s, cond):
    data = s.recv(65536) if cond & GLib.IO_IN else b""
    if not data:
        s.close()
        _watch["sock"] = None
        _notify(None)
        GLib.timeout_add_seconds(5, lambda: _connect() and False)
        return False
    _watch["buffer"] += data
    *lines, _watch["buffer"] = _watch["buffer"].split(b"\n")
    for line in lines[-1:]:  # only the latest matters
        try:
            _notify(json.loads(line).get("status"))
        except ValueError:
            pass
    return True


def _notify(s):
    for fn in watchers:
        fn(s)


def up(name):
    return call({"cmd": "up", "profile": name})[1]


def down():
    return call({"cmd": "down"})[1]


def set_mode(mode):
    return call({"cmd": "mode", "mode": mode})[1]


def remove(name):
    return call({"cmd": "remove", "profile": name})[1]


# ----------------------------------------------------------------- import

def _xdg_dir(name, fallback):
    try:
        out = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or os.path.expanduser(fallback)


def candidates(limit=4):
    """What there is to import, newest first: VPN files in Downloads,
    Documents and the home folder, and the WireGuard and OpenVPN
    connections NetworkManager (GNOME's settings) knows. Each one is
    (title, where, source), source being ("file", path) or ("nm", name)."""
    found = []
    for folder in dict.fromkeys([_xdg_dir("DOWNLOAD", "~/Downloads"), _xdg_dir("DOCUMENTS", "~/Documents"),
                                 os.path.expanduser("~")]):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            if e.name.endswith((".conf", ".ovpn")) and e.is_file() and kind_of(("file", e.path))[0]:
                found.append((e.stat().st_mtime, e.name, os.path.basename(folder) or "~", ("file", e.path)))
    found.sort(reverse=True)
    out = [(name, where, source) for _, name, where, source in found]
    try:
        lines = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                               capture_output=True, text=True, timeout=3).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        lines = []
    for line in lines:
        name, _, kind = line.rpartition(":")
        name = name.replace("\\:", ":")
        if kind == "wireguard" or (kind == "vpn" and _nm_field(name, "vpn.service-type").endswith("openvpn")):
            out.append((name, "GNOME", ("nm", name)))
    return out[:limit]


def _nm_field(name, field, secrets=False):
    args = ["nmcli", "-t"] + (["--show-secrets"] if secrets else []) + ["-f", field, "connection", "show", name]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.split(":", 1)[1].strip() if ":" in out else ""


def _nm_text(name):
    """A NetworkManager connection as a WireGuard .conf or an .ovpn."""
    if _nm_field(name, "connection.type") == "vpn":
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-export.ovpn")
        try:
            subprocess.run(["nmcli", "connection", "export", name, path], capture_output=True, timeout=10)
            with open(path) as f:
                return f.read()
        except (OSError, subprocess.SubprocessError):
            return ""
        finally:
            if os.path.exists(path):
                os.remove(path)
    f = {}
    for field in ("wireguard.private-key", "wireguard.listen-port", "wireguard.mtu", "wireguard.peers",
                  "ipv4.addresses", "ipv6.addresses", "ipv4.dns", "ipv6.dns"):
        f[field] = _nm_field(name, field, secrets=True)
    if not f["wireguard.private-key"]:
        return ""
    addresses = [a.strip() for a in (f["ipv4.addresses"] + "," + f["ipv6.addresses"]).split(",") if a.strip()]
    dns = [d.strip() for d in (f["ipv4.dns"] + "," + f["ipv6.dns"]).split(",") if d.strip()]
    lines = ["[Interface]", "PrivateKey = " + f["wireguard.private-key"], "Address = " + ", ".join(addresses)]
    if dns:
        lines.append("DNS = " + ", ".join(dns))
    if f["wireguard.listen-port"] not in ("", "0"):
        lines.append("ListenPort = " + f["wireguard.listen-port"])
    if f["wireguard.mtu"] not in ("", "0"):
        lines.append("MTU = " + f["wireguard.mtu"])
    keys = {"allowed-ips": "AllowedIPs", "endpoint": "Endpoint", "persistent-keepalive": "PersistentKeepalive",
            "preshared-key": "PresharedKey"}
    # Peers: "KEY allowed-ips=a;b endpoint=h:p, KEY2 ..."
    for peer in f["wireguard.peers"].split(", "):
        parts = peer.split()
        if not parts:
            continue
        lines += ["", "[Peer]", "PublicKey = " + parts[0]]
        for kv in parts[1:]:
            k, _, v = kv.partition("=")
            if k in keys:
                lines.append(f"{keys[k]} = {v.replace(';', ', ').strip(', ')}")
    return "\n".join(lines) + "\n"


def _text(source):
    kind, where = source
    if kind == "nm":
        return _nm_text(where)
    try:
        with open(where, errors="replace") as f:
            return f.read(1 << 20)
    except OSError:
        return ""


def kind_of(source):
    """What a file or connection to import is: "wireguard", "openvpn" or
    None; and whether it asks for a username and password (OpenVPN)."""
    if source[0] == "nm":
        kind = _nm_field(source[1], "connection.type")
        return ("wireguard" if kind == "wireguard" else "openvpn"), kind == "vpn"
    text = _text(source)
    if "[Interface]" in text:
        return "wireguard", False
    lines = [line.split() for line in text.splitlines()]
    if any(f and f[0] in ("remote", "client") for f in lines):
        return "openvpn", any(f == ["auth-user-pass"] for f in lines)
    return None, False


def import_source(source, name, username="", password=""):
    """Error text, or None."""
    text = _text(source)
    if not text:
        return "Couldn't read it" if source[0] == "file" else "NetworkManager didn't hand it over"
    return call({"cmd": "import", "import": {"name": name, "text": text, "username": username,
                                             "password": password}})[1]


def add_openconnect(name, server, protocol, username, password):
    return call({"cmd": "import", "import": {"kind": "openconnect", "name": name, "server": server,
                                             "protocol": protocol, "username": username,
                                             "password": password}})[1]


# ------------------------------------------------------- the chosen apps

# Apps that always go through the VPN, by desktop entry id (firefox.desktop),
# one per line. This machine's pick: not in the repo
APPS = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "vpn-apps")


def chosen():
    try:
        with open(APPS) as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def _save(ids):
    os.makedirs(os.path.dirname(APPS), exist_ok=True)
    with open(APPS, "w") as f:
        f.write("".join(i + "\n" for i in ids))


def choose(app_id):
    if app_id and app_id not in chosen():
        _save(chosen() + [app_id])


def unchoose(app_id):
    _save([i for i in chosen() if i != app_id])


def _desktop(app_id):
    """A desktop entry (GioUnix in newer GLib, Gio before); None when it's gone."""
    import gi
    try:
        gi.require_version("GioUnix", "2.0")
        from gi.repository import GioUnix as G
    except (ValueError, ImportError):
        from gi.repository import Gio as G
    try:
        return G.DesktopAppInfo.new(app_id)
    except TypeError:
        return None


def app_info(app_id):
    """(name, icon, executable) of a desktop entry; None when it's gone."""
    info = _desktop(app_id)
    if not info:
        return None
    return info.get_name(), info.get_icon(), os.path.basename(info.get_executable() or "")


def add_app(output=None, after=None):
    """The app launcher, to pick an app that will always use the VPN (it
    opens through it now if one is on). On output (a sway output name),
    once the process after (the panel) is gone: fuzzel quits when the
    panel, which holds the keyboard, closes after it opened."""
    fuzzel = ["fuzzel", f"--launch-prefix={os.path.abspath(__file__)} choose --", "--prompt=vpn ❯ "]
    if output:
        fuzzel.append(f"--output={output}")
    wait = f"while kill -0 {int(after)} 2>/dev/null; do sleep 0.05; done; " if after else ""
    subprocess.Popen(["sh", "-c", wait + 'exec "$@"', "sh"] + fuzzel,
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_chosen(app_id):
    """Opens one of the chosen apps through the VPN (run_app)."""
    info = _desktop(app_id)
    if not info:
        return
    # Its command without the %u, %F... of files to open
    args = [a for a in shlex.split(info.get_commandline() or "") if not re.fullmatch(r"%[a-zA-Z]", a)]
    if args:
        subprocess.Popen([os.path.abspath(__file__), "run", "--"] + args, start_new_session=True,
                         env=dict(os.environ, DESKTOP_ENTRY_ID=app_id),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def notify(title, body):
    subprocess.run(["notify-send", "-a", "VPN", "-i", "network-vpn", title, body])


def outside(name):
    """This user's processes called name that are not in vpn.slice."""
    try:
        pids = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", name[:15]],
                              capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    out = []
    for pid in pids:
        try:
            if "/vpn.slice/" not in open(f"/proc/{pid}/cgroup").read():
                out.append(pid)
        except OSError:
            pass
    return out


def run_app(args):
    """Starts a chosen app with `vpn run`, for the launcher (fuzzel's launch
    prefix, see sway's vpn-launch.sh) and the VPN page. Says so when it
    can't, since nothing would show fuzzel's errors: with no VPN on it
    doesn't open at all (it would quietly use the normal connection), and
    an app already open outside the VPN (Firefox, Chrome, Spotify...)
    would hand the new window to that one, which doesn't use it."""
    s = status()
    info = app_info(os.environ.get("DESKTOP_ENTRY_ID", "")) if os.environ.get("DESKTOP_ENTRY_ID") else None
    name = info[0] if info else os.path.basename(args[0])
    if not s:
        notify(f"{name} uses the VPN, whose service isn't running", "sudo systemctl start vpnd")
        return 1
    if s["state"] not in ("on", "connecting"):
        notify(f"{name} uses the VPN, which is off",
               "Turn a VPN on in the menu, or take it off the VPN's apps")
        return 1
    exe = os.path.basename(args[0])
    if exe not in ("flatpak", "env", "sh", "bash", "gtk-launch") and outside(exe):
        notify(f"{name} is already open outside the VPN",
               "Close it and open it again: a new window of it would not use the VPN")
        return 1
    os.execvp("vpn", ["vpn", "run", "--"] + args)


def bar():
    """Waybar's custom module. Off (or failed to connect) it has no text, so
    waybar hides it: the VPN is turned on from the menu. A dropped one stays,
    red: what went through it is blocked."""
    def show(s):
        state = s["state"] if s else "off"
        text = "\uf3ed" if state in ("on", "connecting", "dropped") else ""
        tip = {"on": f"{s and s['profile']} · on" + (" · chosen apps" if s and s["mode"] == "apps" else ""),
               "connecting": f"{s and s['profile']} · connecting",
               "dropped": f"{s and s['profile']} dropped: {s and s['error']}"}.get(state, "")
        print(json.dumps({"text": text, "class": state, "alt": state, "tooltip": tip}), flush=True)

    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(SOCKET)
                s.sendall(b'{"cmd": "watch"}\n')
                for line in s.makefile():
                    show(json.loads(line).get("status"))
        except (OSError, ValueError):
            pass
        show(None)
        time.sleep(5)


if __name__ == "__main__":
    if sys.argv[1:] == ["bar"]:
        bar()
    elif sys.argv[1:2] in (["run"], ["choose"]):
        args = sys.argv[2:]
        args = args[1:] if args[:1] == ["--"] else args
        if sys.argv[1] == "choose":
            # Picked to always use the VPN: remembered, and opened if one is on
            choose(os.environ.get("DESKTOP_ENTRY_ID"))
            s = status()
            if not s or s["state"] not in ("on", "connecting"):
                sys.exit(0)
        sys.exit(run_app(args))
    else:
        sys.exit(__doc__.split("\n\n")[-1])
