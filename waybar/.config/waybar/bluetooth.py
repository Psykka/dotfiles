"""Bluetooth helpers for the menu's Bluetooth page, over BlueZ's D-Bus API.

Calls that take a while (connect, pair) are asynchronous: they need the GLib
main loop running, and report back through a callback. Discovery started
here stops by itself when the process exits.
"""
import re
import subprocess

from gi.repository import Gio, GLib

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
PROPS = "org.freedesktop.DBus.Properties"
AGENT_PATH = "/bar/bluetooth/agent"

AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
    <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
    <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
    <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="Cancel"/>
  </interface>
</node>
"""

_bus = None


def bus():
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    return _bus


def objects():
    try:
        reply = bus().call_sync(BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                                None, None, Gio.DBusCallFlags.NONE, 3000)
    except GLib.Error:
        return {}
    return reply.unpack()[0]


def adapter():
    """(path, properties) of the first adapter, or (None, {})."""
    return next(((p, i[ADAPTER]) for p, i in sorted(objects().items()) if ADAPTER in i), (None, {}))


def devices():
    """Known and nearby devices of the adapter, as dicts."""
    path, _ = adapter()
    out = []
    for p, ifaces in objects().items():
        d = ifaces.get(DEVICE)
        if not d or d.get("Adapter") != path:
            continue
        out.append({
            "path": p,
            "address": d.get("Address", ""),
            # Without a name of its own, Alias is the address with dashes
            "name": d.get("Alias") or d.get("Name") or d.get("Address", ""),
            "named": "Name" in d,
            "icon": d.get("Icon", ""),
            "paired": d.get("Paired", False) or d.get("Bonded", False),
            "connected": d.get("Connected", False),
            "rssi": d.get("RSSI"),
            "battery": ifaces.get(BATTERY, {}).get("Percentage"),
        })
    return out


def _set(path, iface, name, value):
    try:
        bus().call_sync(BLUEZ, path, PROPS, "Set", GLib.Variant("(ssv)", (iface, name, value)),
                        None, Gio.DBusCallFlags.NONE, 3000)
        return True
    except GLib.Error:
        return False


def set_powered(on):
    path, _ = adapter()
    if not path:
        return
    if not _set(path, ADAPTER, "Powered", GLib.Variant("b", on)) and on:
        # Blocked by rfkill (airplane mode, or turned off elsewhere)
        subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
        _set(path, ADAPTER, "Powered", GLib.Variant("b", True))


def _call(path, iface, method, done=None, args=None, timeout=30000, ignore=()):
    """Calls a method without blocking; done(error message or None). The
    BlueZ errors named in ignore count as success."""
    def finish(conn, res):
        err = None
        try:
            conn.call_finish(res)
        except GLib.Error as e:
            if (Gio.DBusError.get_remote_error(e) or "") not in ignore:
                err = re.sub(r"^GDBus\.Error:[\w.]+: ", "", e.message)
        if done:
            done(err)
    bus().call(BLUEZ, path, iface, method, args, None, Gio.DBusCallFlags.NONE, timeout, None, finish)


def discover(on):
    path, _ = adapter()
    if path:
        _call(path, ADAPTER, "StartDiscovery" if on else "StopDiscovery")


def connect(path, done=None):
    _call(path, DEVICE, "Connect", done)


def disconnect(path, done=None):
    _call(path, DEVICE, "Disconnect", done)


def pair(path, done=None):
    """Pairs, trusts (so it can reconnect by itself) and connects."""
    def paired(err):
        if err:
            done and done(err)
            return
        _set(path, DEVICE, "Trusted", GLib.Variant("b", True))
        connect(path, done)
    _call(path, DEVICE, "Pair", paired, timeout=60000, ignore=("org.bluez.Error.AlreadyExists",))


def cancel_pairing(path):
    _call(path, DEVICE, "CancelPairing")


def forget(path):
    adapter_path, _ = adapter()
    if adapter_path:
        _call(adapter_path, ADAPTER, "RemoveDevice", args=GLib.Variant("(o)", (path,)))


def watch(on_change):
    """Calls on_change() when an adapter or device appears, goes or changes."""
    for member in ("InterfacesAdded", "InterfacesRemoved", "PropertiesChanged"):
        bus().signal_subscribe(BLUEZ, None, member, None, None, Gio.DBusSignalFlags.NONE,
                               lambda *_: on_change())


def name_of(path):
    return (objects().get(path, {}).get(DEVICE, {}).get("Alias")) or path.rsplit("/", 1)[-1]


class Agent:
    """Answers BlueZ while pairing: asks the page to show a code to confirm
    or to type on the device. Registered as the default agent while the
    page is open (no other one runs on this desktop).

    on_request(kind, device name, code, reply): kind is "confirm" (reply
    with True/False; code is None for a device that just asks to pair) or
    "show" (reply is None); on_request(None, ...) takes the request away."""

    def __init__(self, on_request):
        self.on_request = on_request
        node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
        self.reg = bus().register_object(AGENT_PATH, node.interfaces[0], self.handle, None, None)
        self.manager("RegisterAgent", GLib.Variant("(os)", (AGENT_PATH, "DisplayYesNo")))
        self.manager("RequestDefaultAgent", GLib.Variant("(o)", (AGENT_PATH,)))

    def manager(self, method, args):
        try:
            bus().call_sync(BLUEZ, "/org/bluez", "org.bluez.AgentManager1", method, args,
                            None, Gio.DBusCallFlags.NONE, 3000)
        except GLib.Error:
            pass

    def close(self):
        self.manager("UnregisterAgent", GLib.Variant("(o)", (AGENT_PATH,)))
        bus().unregister_object(self.reg)

    def handle(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method in ("RequestConfirmation", "RequestAuthorization"):
            device, code = args[0], f"{args[1]:06d}" if len(args) > 1 else None

            def reply(ok):
                if ok:
                    invocation.return_value(None)
                else:
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Rejected")
            self.on_request("confirm", name_of(device), code, reply)
        elif method in ("DisplayPasskey", "DisplayPinCode"):
            code = f"{args[1]:06d}" if method == "DisplayPasskey" else args[1]
            self.on_request("show", name_of(args[0]), code, None)
            invocation.return_value(None)
        elif method == "RequestPinCode":
            # Old devices (headsets, mice) that ask for a PIN mostly use 0000
            invocation.return_value(GLib.Variant("(s)", ("0000",)))
        elif method == "RequestPasskey":
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Typing a passkey is not supported")
        elif method == "Cancel":
            self.on_request(None, "", "", None)
            invocation.return_value(None)
        else:
            # Release, and services of devices already paired
            invocation.return_value(None)
