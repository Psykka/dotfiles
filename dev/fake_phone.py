"""A pretend phone, with the same calls as waybar/.config/waybar/phone.py,
to see and test the phone popup without KDE Connect or a phone.
dev/panel-sizes.py puts it in place of the real one; nothing reaches
kdeconnectd.

The phone: charging, on LTE, with notifications (a long chat, one that
can't be dismissed, more than fit). Ringing and the clipboard just answer;
opening its files fails after a moment (nothing gets mounted or opened).
"""
from gi.repository import GLib

DELAY_MS = 700

state = {"paired": True, "reachable": True, "battery": 64, "charging": True, "network": "LTE"}
watchers = []
NOTES = [
    dict(id="1", app="WhatsApp", title="Maria", text="Are we still on for tonight?\nI can bring the projector",
         picture="", dismissable=True),
    dict(id="2", app="Gmail", title="A subject far too long to fit on one line of the card, cut with an ellipsis",
         text="And a body that goes on and on, much longer than the card is wide " * 3, picture="", dismissable=True),
    dict(id="3", app="Android System", title="", text="USB debugging connected", picture="", dismissable=False),
    dict(id="4", app="Calendar", title="Dentist", text="Tomorrow 09:30", picture="", dismissable=True),
    dict(id="5", app="Telegram", title="Group chat", text="12 new messages", picture="", dismissable=True),
]
notes = list(NOTES)


def changed():
    for w in watchers:
        w()


def watch(callback):
    watchers.append(callback)


def device():
    if not state["paired"]:
        return None
    return {"id": "fake", "name": "Pixel 8 Pro", "reachable": state["reachable"],
            "battery": state["battery"], "charging": state["charging"],
            "network": state["network"], "signal": 3}


def notifications(_dev_id):
    return [dict(n) for n in notes]


def dismiss(_dev_id, nid):
    notes[:] = [n for n in notes if n["id"] != nid]
    changed()


def ring(_dev_id):
    pass


def send_clipboard(_dev_id):
    pass


def browse(_dev_id, done):
    GLib.timeout_add(DELAY_MS, lambda: done(None, "the phone didn't answer") or False)


# For the steps of dev/panel-sizes.py

def post(**n):
    notes.insert(0, {"picture": "", "dismissable": True, "title": "", **n})
    changed()


def clear():
    notes.clear()
    changed()


def set_state(**values):
    state.update(values)
    changed()
