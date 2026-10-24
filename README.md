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

`theme dark|light|toggle` switches the palette; colors live in `themes/`.

`Super + /` shows all keybindings.

## License

Copyright © 2026 Psykka. Distributed under the [GorillaPL](LICENSE) 🦍.
