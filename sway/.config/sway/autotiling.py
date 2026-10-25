#!/usr/bin/env python3
"""Gorilla-like tiling: each new window splits the focused one in half,
side by side if it is wider than tall, stacked otherwise, so windows
keep halving the space in a spiral.

Before a window opens, the focused one decides the direction: on every
focus change the split direction is set from its shape.
"""
from i3ipc import Connection, Event


def on_focus(sway, _event):
    win = sway.get_tree().find_focused()
    if not win or win.type == "floating_con" or win.fullscreen_mode == 1:
        return
    if win.parent and win.parent.layout in ("tabbed", "stacked"):
        return
    want = "splith" if win.rect.width > win.rect.height else "splitv"
    if win.parent and win.parent.layout != want:
        sway.command(want)


def main():
    sway = Connection()
    sway.on(Event.WINDOW_FOCUS, on_focus)
    sway.main()


if __name__ == "__main__":
    main()
