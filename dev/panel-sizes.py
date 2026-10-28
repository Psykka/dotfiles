#!/usr/bin/env python3
"""Checks that the bar popups (waybar/.config/waybar/panel.py) keep their
size while they are used: no jumps when something loads, a tab changes or
a button appears.

Opens each popup on the running sway, goes through its steps (below), and
prints every change in the window size with the step it came after. A
change after a step not marked as resizing (the slide of a list opening,
the swap to the wallpaper preview...) is a failure: exit status 1.

Usage: dev/panel-sizes.py [MODE ...]        all of them by default
       dev/panel-sizes.py --shots DIR MODE  and a screenshot after each step

The popups really open, on the focused display. The media one plays the
pretend player (dev/fake-player.py) and leaves any real one alone; the
Bluetooth one has pretend devices (dev/fake_bluetooth.py) and the sound
one a pretend sound server (dev/fake_audio.py). The
wallpaper one tries a wallpaper already downloaded on the desktop, then
discards it: nothing is saved. Not a stow package: nothing here is linked
into ~.
"""
import os
import pathlib
import subprocess
import sys

PANEL_DIR = pathlib.Path(__file__).resolve().parents[1] / "waybar/.config/waybar"
SAMPLE_MS = 10
SETTLE_MS = 3500  # opening, and the first data coming in (Wallhaven...)


def local_wallpaper():
    import wallpaper
    files = wallpaper.downloaded()
    return str(files[0]) if files else None


# Steps of each popup: (wait ms, name, action(content), may resize).
# The content is the popup's widget (Wallpapers, Menu, Calendar...).
def steps(mode):
    if mode == "wallpaper":
        import panel
        local = local_wallpaper()
        return [
            (0, "filters open", lambda w: w.toggle_filters(), True),
            (800, "filters close", lambda w: w.toggle_filters(), True),
            (800, "pick from Wallhaven", lambda w: w.pick(("wallhaven", w.results["items"][0])), False),
            (500, "next page", lambda w: w.search(2), False),
            (3000, "tab Downloaded", lambda w: w.show_tab("downloaded"), False),
            (800, "pick a local one", lambda w: w.pick(("local", local)), False),
            (500, "ask to delete", lambda w: w.ask("delete"), False),
            (500, "don't delete", lambda w: w.ask(None), False),
            (500, "tab Colors", lambda w: w.show_tab("colors"), False),
            (800, "colors from the wallpaper", lambda w: w.set_mode("wallpaper"), False),
            (500, "style Vivid", lambda w: w.set_style(dict(panel.wallpaper.PRESETS[2][1])), False),
            (500, "accent 2", lambda w: w.set_accent(2), False),
            (500, "tint", lambda w: w.tune("tint", 0.3), False),
            (500, "tab Wallhaven", lambda w: w.show_tab("wallhaven"), False),
            (800, "try it", lambda w: w.try_picked(), False),
            (5000, "ask to save", lambda w: w.ask("save"), False),
            (500, "don't save", lambda w: w.ask(None), False),
            (500, "preview", lambda w: w.start_preview(), True),
            (1500, "examples off", lambda w: w.show_examples(False), False),
            (800, "examples on", lambda w: w.show_examples(True), False),
            (1500, "keep?", lambda w: w.show_slim("save"), False),
            (500, "adjust", lambda w: w.end_preview(), True),
            (1500, "discard", lambda w: w.discard(), False),
            (5000, "end", lambda w: None, False),
        ] if local else None
    if mode == "menu":
        return [
            (0, "power open", lambda m: m.toggle_power(), True),
            (800, "power close", lambda m: m.toggle_power(), True),
            (800, "sound page", lambda m: m.show_page("sound"), True),
            (1500, "back", lambda m: m.show_page("main"), True),
            (800, "displays page", lambda m: m.show_page("displays"), True),
            (1000, "back", lambda m: m.show_page("main"), True),
            (1000, "end", lambda m: None, False),
        ]
    if mode == "media":
        # The pretend player (fake-player.py) goes through its tracks: art,
        # a title far too long, no art, a stream; then it quits
        def player(*args):
            subprocess.run(["playerctl", "-p", "fakeplayer", *args], capture_output=True)
        return [
            (0, "a player starts", lambda _: start_fake_player(), False),
            (1500, "long title", lambda _: player("next"), False),
            (1500, "no art", lambda _: player("next"), False),
            (1500, "stream", lambda _: player("next"), False),
            (1500, "pause", lambda _: player("pause"), False),
            (1500, "volume line", lambda m: m.show_volume(True), False),
            (800, "mute", lambda m: m.toggle_mute(), False),
            (1200, "unmute", lambda m: m.toggle_mute(), False),
            (4000, "back to progress", lambda _: None, False),
            (1500, "player quits", lambda _: stop_fake_player(), False),
            (2000, "end", lambda _: None, False),
        ]
    if mode == "bluetooth":
        # With the pretend Bluetooth (fake_bluetooth.py), set up in run()
        import fake_bluetooth as fake

        def dev(path):
            return next(d for d in fake.devices() if d["path"] == path)
        return [
            (0, "ask to forget", lambda m: m.bluetooth.rows["/fake/mouse"].trash.clicked(), False),
            (500, "don't forget", lambda m: m.bluetooth.rows["/fake/mouse"].back(), False),
            (500, "connect, and fail", lambda m: m.bluetooth.use(dev("/fake/speaker")), False),
            (1500, "pair, asks for a code", lambda m: m.bluetooth.use(dev("/fake/phone")), False),
            (1500, "say yes", lambda m: m.bluetooth.rows["/fake/phone"].answer(True), False),
            (1500, "a code to type", lambda m: m.bluetooth.ask("show", "Keychron K2", "4321", None), False),
            (500, "cancelled by it", lambda m: m.bluetooth.ask(None, "", "", None), False),
            (500, "forget", lambda m: m.bluetooth.forget(dev("/fake/mouse")), False),
            (1500, "turn off", lambda m: m.bluetooth.switch.set_active(False), False),
            (800, "turn on", lambda m: m.bluetooth.switch.set_active(True), False),
            (1000, "end", lambda _: None, False),
        ]
    if mode == "sound":
        # With the pretend sound server (fake_audio.py), set up in run()
        import fake_audio as fake

        def app(s, name):
            return next(r for r in s.apps_rows.values() if r.stream["app"] == name)
        return [
            (0, "pick an output", lambda m: m.sound.pick("sink"), False),
            (800, "use the headphones", lambda m: m.sound.use("bt"), False),
            (800, "pick an input", lambda m: m.sound.pick("source"), False),
            (800, "a mic with three gains", lambda m: m.sound.use("yeti"), False),
            (1000, "drag a gain", lambda m: m.sound.gain_rows[0].moved(55), False),
            (500, "move Firefox here", lambda m: app(m.sound, "Firefox").bring(), False),
            (500, "mute an app", lambda m: app(m.sound, "Spotify").toggle_mute(), False),
            (500, "turn an app down", lambda m: app(m.sound, "Spotify").volume.moved(20), False),
            (500, "a device plugged", lambda _: fake.plug(), False),
            (500, "pick among four", lambda m: m.sound.pick("sink"), False),
            (800, "back", lambda m: m.sound.show("main"), False),
            (800, "and unplugged", lambda _: fake.unplug(), False),
            (500, "an app starts", lambda _: fake.start("Telegram"), False),
            (500, "and another", lambda _: fake.start("OBS", "source-output"), False),
            (500, "both stop", lambda _: fake.stop("Telegram") or fake.stop("OBS"), False),
            (500, "mute the mic", lambda m: m.sound.input.toggle_mute(), False),
            (800, "fix", lambda m: m.sound.fix(), False),
            (1500, "OK", lambda m: m.sound.fixes.set_visible_child_name("buttons"), False),
            (500, "restart audio", lambda m: m.sound.restart(), False),
            (2000, "end", lambda _: None, False),
        ]
    if mode == "calendar":
        return [
            (0, "next month", lambda c: c.month.move(1), False),
            # February 2026 fits in four weeks; still six rows
            (500, "a short month", lambda c: c.month.show(2026, 2), False),
            (500, "a long name", lambda c: c.month.show(2026, 9), False),
            (500, "back a year", lambda c: c.month.move(-12), False),
            (500, "today", lambda c: c.month.back.clicked(), False),
            (1000, "end", lambda _: None, False),
        ]
    return None


FAKE_PLAYER = pathlib.Path(__file__).resolve().parent / "fake-player.py"
fake = []


def start_fake_player():
    # Quits by itself too, should this script die before stopping it
    fake.append(subprocess.Popen([sys.executable, str(FAKE_PLAYER), "60"], stderr=subprocess.DEVNULL))


def stop_fake_player():
    while fake:
        fake.pop().terminate()


MODES = ("wallpaper", "menu", "sound", "bluetooth", "calendar", "media")


def run(mode, shots):
    """In its own process: panel.py's main loop runs once per process."""
    sys.path.insert(0, str(PANEL_DIR))
    sys.argv = ["panel.py", mode]
    import panel
    from gi.repository import GLib, Gtk

    panel.PLAYERCTL = ["playerctl", "-p", "fakeplayer"]
    if mode == "bluetooth":
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import fake_bluetooth
        panel.bluetooth = fake_bluetooth
        panel.HAS_BLUETOOTH = True
    if mode in ("sound", "menu"):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import fake_audio
        panel.audio = fake_audio
    plan = steps(mode)
    if plan is None:
        print(f"{mode}: skipped (nothing to try it with)")
        return 0
    found = {}
    init = panel.Panel.__init__

    def keep(self, *args):
        init(self, *args)
        found["panel"] = self
    panel.Panel.__init__ = keep

    state = {"step": "open", "allowed": False, "size": None}
    # Each step that changed the size: [from, to, frames, allowed], in order
    changes = {}

    def sample():
        win = found.get("panel")
        if win:
            size = (win.get_allocated_width(), win.get_allocated_height())
            if state["size"] and size != state["size"]:
                c = changes.setdefault(state["step"], [state["size"], size, 0, state["allowed"]])
                c[1], c[2] = size, c[2] + 1
            state["size"] = size
        return True

    def do(name, action, allowed):
        state["step"], state["allowed"] = name, allowed
        action(found["panel"].content)
        if shots:
            GLib.timeout_add(400, lambda: subprocess.run(
                ["grim", os.path.join(shots, f"{mode}-{name.replace(' ', '-')}.png")]) and False)
        return False

    # The opening slide is not measured: from when it has settled
    GLib.timeout_add(panel.SLIDE_MS + 100, lambda: GLib.timeout_add(SAMPLE_MS, sample) and False)
    t = SETTLE_MS
    for wait, name, action, allowed in plan:
        t += wait
        GLib.timeout_add(t, lambda n=name, a=action, ok=allowed: do(n, a, ok))
    GLib.timeout_add(t + 300, lambda: Gtk.main_quit() or False)
    try:
        panel.main()
    finally:
        stop_fake_player()

    def wh(size):
        return f"{size[0]}x{size[1]}"
    for step, (before, after, frames, allowed) in changes.items():
        how = "animated" if allowed else "UNEXPECTED"
        print(f"  {step:28} {wh(before)} -> {wh(after)}  ({frames} frame{'s' if frames != 1 else ''}, {how})")
    bad = [step for step, c in changes.items() if not c[3]]
    if bad:
        print(f"{mode}: FAIL, changed size after: " + ", ".join(bad))
        return 1
    print(f"{mode}: ok, {state['size'][0]}x{state['size'][1]}")
    return 0


def main():
    args = sys.argv[1:]
    shots = None
    if args[:1] == ["--shots"]:
        shots, args = args[1], args[2:]
        os.makedirs(shots, exist_ok=True)
    if args[:1] == ["--run"]:
        sys.exit(run(args[1], shots))
    modes = args or MODES
    unknown = [m for m in modes if m not in MODES]
    if unknown:
        sys.exit(f"panel-sizes: no steps for {', '.join(unknown)} (there are: {', '.join(MODES)})")
    failed = 0
    for mode in modes:
        print(f"{mode}:", flush=True)
        cmd = [sys.executable, __file__] + (["--shots", shots] if shots else []) + ["--run", mode]
        out = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
        # GLib's deprecation warnings are noise here
        for line in out.stderr.splitlines():
            if "Deprecat" not in line and "unix_signal_add" not in line:
                print(line, file=sys.stderr)
        failed += out.returncode != 0
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
