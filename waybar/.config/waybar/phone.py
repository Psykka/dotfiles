#!/usr/bin/env python3
"""The phone, through KDE Connect's daemon (kdeconnectd) on the session
bus: its battery, its notifications, and ringing it, browsing its files or
sending it the clipboard. The phone popup (panel.py phone) uses it, and the
bar's icon next to the clock runs it as `phone.py bar`.

Calls never start the daemon (it starts with sway): with no daemon there is
simply no phone. Browsing waits for the phone (mountAndWait), so it is
asynchronous: it needs the GLib main loop and answers through a callback.

Usage: phone.py bar      one JSON line for waybar per change, forever
"""
import json
import sys

from gi.repository import Gio, GLib

NAME = "org.kde.kdeconnect"
DAEMON_PATH, DAEMON = "/modules/kdeconnect", "org.kde.kdeconnect.daemon"
DEVICE = "org.kde.kdeconnect.device"
NOTIFICATION = "org.kde.kdeconnect.device.notifications.notification"
PROPS = "org.freedesktop.DBus.Properties"
ICON = ""  # Font Awesome's mobile phone
LOW = 20  # battery percent shown as low on the bar

_bus = None


def bus():
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    return _bus


def call(path, iface, method, params=None, timeout=3000):
    """The reply unpacked, or None when the daemon or the object isn't
    there. NO_AUTO_START: asking must not start kdeconnectd."""
    try:
        reply = bus().call_sync(NAME, path, iface, method, params, None,
                                Gio.DBusCallFlags.NO_AUTO_START, timeout)
    except GLib.Error:
        return None
    return reply.unpack()


def props(path, iface):
    out = call(path, PROPS, "GetAll", GLib.Variant("(s)", (iface,)))
    return out[0] if out else {}


def device():
    """The phone: the first paired device, reachable ones first; None when
    there is none (or no daemon). Its battery and signal are None when the
    phone doesn't say (the plugin off, no permission)."""
    out = call(DAEMON_PATH, DAEMON, "devices", GLib.Variant("(bb)", (False, True)))
    found = []
    for dev_id in (out[0] if out else []):
        path = f"{DAEMON_PATH}/devices/{dev_id}"
        p = props(path, DEVICE)
        if p:
            found.append((path, dev_id, p))
    if not found:
        return None
    path, dev_id, p = sorted(found, key=lambda f: not f[2].get("isReachable"))[0]
    battery = props(path + "/battery", DEVICE + ".battery")
    cell = props(path + "/connectivity_report", DEVICE + ".connectivity_report")
    return {
        "id": dev_id,
        "name": p.get("name", ""),
        "reachable": bool(p.get("isReachable")),
        "battery": battery.get("charge") if battery.get("hasBattery") and battery.get("charge", -1) >= 0 else None,
        "charging": bool(battery.get("isCharging")),
        "network": cell.get("cellularNetworkType") or None,
        "signal": cell.get("cellularNetworkStrength") if cell.get("cellularNetworkStrength", -1) >= 0 else None,
    }


def notifications(dev_id):
    """The phone's notifications on screen there, newest first: id, app,
    title, text, picture (a file, or "") and whether it can be dismissed."""
    path = f"{DAEMON_PATH}/devices/{dev_id}/notifications"
    out = call(path, DEVICE + ".notifications", "activeNotifications")
    found = []
    for nid in reversed(out[0] if out else []):
        p = props(f"{path}/{nid}", NOTIFICATION)
        if not p:
            continue
        found.append({"id": nid, "app": p.get("appName", ""), "title": p.get("title", ""),
                      "text": p.get("text", "") or p.get("ticker", ""),
                      "picture": p.get("iconPath", "") if p.get("hasIcon") else "",
                      "dismissable": bool(p.get("dismissable"))})
    return found


def dismiss(dev_id, nid):
    call(f"{DAEMON_PATH}/devices/{dev_id}/notifications/{nid}", NOTIFICATION, "dismiss")


def ring(dev_id):
    call(f"{DAEMON_PATH}/devices/{dev_id}/findmyphone", DEVICE + ".findmyphone", "ring")


def send_clipboard(dev_id):
    call(f"{DAEMON_PATH}/devices/{dev_id}/clipboard", DEVICE + ".clipboard", "sendClipboard")


def browse(dev_id, done):
    """Mounts the phone's storage (it asks the phone, which can take a few
    seconds); done(folder, error): one of them is None."""
    path = f"{DAEMON_PATH}/devices/{dev_id}/sftp"
    iface = DEVICE + ".sftp"

    def mounted(conn, res):
        try:
            ok = conn.call_finish(res).unpack()[0]
        except GLib.Error as e:
            done(None, e.message)
            return
        if not ok:
            out = call(path, iface, "getMountError")
            done(None, (out[0] if out else "") or "the phone didn't answer")
            return
        out = call(path, iface, "mountPoint")
        done(out[0] if out else None, None if out else "no folder")
    bus().call(NAME, path, iface, "mountAndWait", None, None, Gio.DBusCallFlags.NO_AUTO_START,
               30000, None, mounted)


def watch(callback):
    """callback() on anything the daemon says (a phone coming or going, its
    battery, a notification), and when the daemon starts or stops. Many
    come at once: debounce on the other end."""
    bus().signal_subscribe(NAME, None, None, None, None, Gio.DBusSignalFlags.NONE,
                           lambda *_: callback())
    bus().signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                           "/org/freedesktop/DBus", NAME, Gio.DBusSignalFlags.NONE, lambda *_: callback())


def bar_line():
    """The icon, only while a paired phone is reachable; an empty text
    hides the module."""
    d = device()
    if not d or not d["reachable"]:
        return {"text": "", "class": "none"}
    low = d["battery"] is not None and d["battery"] <= LOW and not d["charging"]
    return {"text": ICON, "class": "low" if low else "on"}


def bar():
    last = [None]
    queued = [False]

    def show():
        queued[0] = False
        line = json.dumps(bar_line())
        if line != last[0]:
            last[0] = line
            print(line, flush=True)
        return False

    def changed():
        if not queued[0]:
            queued[0] = True
            GLib.timeout_add(300, show)
    watch(changed)
    show()
    # The battery comes in without a signal of its own now and then
    GLib.timeout_add_seconds(60, lambda: show() or True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    if sys.argv[1:] == ["bar"]:
        bar()
    else:
        sys.exit("usage: phone.py bar")
