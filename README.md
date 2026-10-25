# dotfiles

My SwayFX configs on Fedora.

```sh
git clone git@github.com:Psykka/dotfiles.git ~/dotfiles
~/dotfiles/install.sh
```

Works on Fedora, Arch and Debian. It installs the packages, links the configs
with GNU Stow (backing up anything in the way) and applies the color theme.
On Debian there is no SwayFX, so it runs on plain sway without rounded corners
and shadows.

Colors live in `themes/dark.ini`; after editing it, run `theme` to apply.

`Super + /` shows all keybindings.

## Credits

Wallpaper: "The Edge of Two Worlds", taken by the Artemis II crew.
Image Credit: NASA ([source](https://www.nasa.gov/image-detail/amf-art002e009285/)).
Details in [`wallpapers/.local/share/wallpapers/CREDITS.md`](wallpapers/.local/share/wallpapers/CREDITS.md).

Fetch: [ufetch](https://gitlab.com/jschx/ufetch) by J Schillinger, MIT license
([`licenses/ufetch`](licenses/ufetch)).

## License

Copyright © 2026 Psykka. Distributed under the [GorillaPL](LICENSE) 🦍,
except the wallpaper, a NASA image (see Credits).
