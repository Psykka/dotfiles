# dotfiles

My SwayFX configs on Fedora.

![Desktop: nnn, ufetch, cava and cmatrix](screenshots/desktop.png)

```sh
git clone git@github.com:Psykka/dotfiles.git ~/dotfiles
~/dotfiles/install.sh
```

Works on Fedora, Arch and Debian. It installs the packages, links the configs
with GNU Stow (backing up anything in the way) and applies the color theme.
On Debian there is no SwayFX, so it runs on plain sway without rounded corners
and shadows.

Colors live in `themes/dark.ini`; after editing it, run `theme` to apply.

Wallpaper: click the clock (then "Wallpaper"), or "Wallpaper" under System in
the launcher. Search Wallhaven or pick one already downloaded, take the colors
from it (or keep the theme's), adjust the picture, try it on the desktop, then
save it or discard it. What you pick is this machine's choice: it goes to
`~/.local/state/theme-local.ini`, on top of the palette, not into the repo.
The files `theme` writes from `themes/templates` are not in git either.

Notifications come from our own server (`waybar/.config/waybar/notifications.py`,
in place of mako): same-size cards with a bar for the time left, which stops
under the mouse; the calendar lists the last 30.

`Super + /` shows all keybindings.

## Screenshots

| | |
|---|---|
| ![App launcher](screenshots/launcher.png) | ![Keybindings](screenshots/keybindings.png) |
| App launcher (`Super + Space`) | Keybindings (`Super + /`) |
| ![Calendar and notifications](screenshots/calendar.png) | ![Media player](screenshots/media.png) |
| Calendar and notifications (click the clock) | Media player (click the song) |
| ![System menu](screenshots/menu.png) | ![Updates](screenshots/updates.png) |
| Network, sound and power (`☰`) | Pending updates (the cube) |
| ![Lock screen](screenshots/lock.png) | ![Login screen](screenshots/greeter.png) |
| Lock screen (`Super + L`) | Login screen (greetd + tuigreet) |

## Credits

Wallpaper: "The Edge of Two Worlds", taken by the Artemis II crew.
Image Credit: NASA ([source](https://www.nasa.gov/image-detail/amf-art002e009285/)).
Details in [`wallpapers/.local/share/wallpapers/CREDITS.md`](wallpapers/.local/share/wallpapers/CREDITS.md).

Fetch: [ufetch](https://gitlab.com/jschx/ufetch) by J Schillinger, MIT license
([`licenses/ufetch`](licenses/ufetch)).

## License

Copyright © 2026 Psykka. Distributed under the [GorillaPL](LICENSE) 🦍,
except the wallpaper, a NASA image (see Credits).
