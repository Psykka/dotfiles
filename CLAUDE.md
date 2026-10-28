# Notes for Claude

SwayFX dotfiles for Fedora, Arch and Debian. Each top-level folder is a GNU
Stow package linked into `~` (`install.sh`); `dev/` is not one.

- Talk to the user in Portuguese (pt-BR); code, comments and commits stay in English.
- Commits: `feat: ...` style, short subject.
- Match the surrounding code: plain Python/sh, few dependencies, comments
  that say why.

## Colors and choices of this machine

- `themes/<name>.ini` is the palette and `themes/templates/` are filled from it
  by `theme` (`bin/.local/bin/theme`). The files it writes are not in git
  (`.gitignore`): edit the templates, never the generated files.
- This machine's picks (wallpaper and its colors) live in
  `~/.local/state/theme-local.ini` (`theme local`), never in the repo.
- `theme preview` / `theme local` change colors without `swaymsg reload`
  (it makes the screen blink); keep it that way.

## Bar popups must stay fluid

`waybar/.config/waybar/panel.py` holds every bar popup (GTK3 + layer
shell). The user cares that the UI never jumps: nothing may change size
when data loads, a tab changes, a button appears or a message shows.
Reserve the room up front (fixed sizes, homogeneous stacks, empty slots
while loading) instead of letting things grow.

After touching `panel.py` (or anything it shows), run:

    dev/panel-sizes.py              # every popup, or: dev/panel-sizes.py wallpaper

It opens each popup on the running sway, goes through its steps and fails
on any size change that is not a deliberate animation. When adding a
popup, a tab or a new state, add its steps to `steps()` in that script.
`--shots DIR` also saves a screenshot after each step (look at them with
the Read tool). It needs the user's live sway session (`$SWAYSOCK`); it
tries a wallpaper but saves nothing.

For sway behaviour (workspaces, outputs) that shouldn't touch the user's
session, run a nested headless sway: `WLR_BACKENDS=headless
WLR_RENDERER=pixman sway` with a short `XDG_RUNTIME_DIR` (long paths break
the IPC socket) and a throwaway `HOME`.
