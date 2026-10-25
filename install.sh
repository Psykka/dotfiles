#!/bin/sh
# Installs the packages and links the configs into ~ with GNU Stow.
# Works on Fedora, Arch and Debian (and distros based on them).
#
# Usage: ./install.sh
#
# Existing files that would be replaced are moved to ~/.dotfiles-backup/<date>.
set -eu

cd "$(dirname "$0")"
REPO=$(pwd)
STOW_PACKAGES="sway waybar mako fuzzel swaylock alacritty gtk fonts keyboard spotify bin wallpapers launcher bash"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

. /etc/os-release
case "$ID ${ID_LIKE:-}" in
    *fedora*) distro=fedora ;;
    *arch*) distro=arch ;;
    *debian*|*ubuntu*) distro=debian ;;
    *) echo "Unsupported distro: $ID (Fedora, Arch and Debian are supported)" >&2; exit 1 ;;
esac

# Same name everywhere
common="swaybg swaylock swayidle waybar playerctl fuzzel alacritty grim slurp
wl-clipboard cliphist mate-polkit stow wireplumber wdisplays kanshi blueman
papirus-icon-theme starship eza bat"

case $distro in
    fedora) packages="$common mako sway-systemd libnotify pulseaudio-utils
        gtk-layer-shell python3-gobject python3-i3ipc jetbrains-mono-fonts-all rsms-inter-fonts
        google-noto-color-emoji-fonts fontawesome-6-free-fonts
        fontawesome-6-brands-fonts adwaita-mono-fonts papirus-icon-theme-dark" ;;
    arch) packages="$common mako libnotify libpulse gtk-layer-shell python-gobject python-i3ipc
        ttf-jetbrains-mono inter-font noto-fonts-emoji otf-font-awesome" ;;
    debian) packages="$common sway mako-notifier libnotify-bin pulseaudio-utils
        gir1.2-gtklayershell-0.1 gir1.2-gtk-3.0 python3-gi python3-i3ipc fonts-jetbrains-mono
        fonts-inter fonts-noto-color-emoji fonts-font-awesome" ;;
esac

# Keeps only the packages this distro has, and remembers the rest
available() {
    case $distro in
        fedora) dnf -q repoquery --qf '%{name}' "$1" 2>/dev/null | grep -qx "$1" ;;
        arch) pacman -Si "$1" >/dev/null 2>&1 ;;
        debian) apt-cache show "$1" >/dev/null 2>&1 ;;
    esac
}

say "Installing packages ($distro)"
[ $distro = debian ] && sudo apt-get update -q
if [ $distro = fedora ]; then
    sudo dnf copr enable -y swayfx/swayfx
    sudo dnf copr enable -y atim/starship
fi
found="" missing=""
for p in $packages; do
    if available "$p"; then found="$found $p"; else missing="$missing $p"; fi
done

case $distro in
    fedora)
        # SwayFX replaces sway (rounded corners, shadows)
        # shellcheck disable=SC2086
        sudo dnf install -y --allowerasing swayfx $found ;;
    arch)
        # shellcheck disable=SC2086
        sudo pacman -S --needed --noconfirm $found
        # SwayFX comes from the AUR; plain sway works too, without effects
        if command -v paru >/dev/null; then paru -S --needed --noconfirm swayfx
        elif command -v yay >/dev/null; then yay -S --needed --noconfirm swayfx
        else
            sudo pacman -S --needed --noconfirm sway
            missing="$missing swayfx(AUR:no-helper)"
        fi ;;
    debian)
        # No SwayFX package on Debian: plain sway, without effects
        # shellcheck disable=SC2086
        sudo apt-get install -y $found ;;
esac

say "Linking configs"
backup="$HOME/.dotfiles-backup/$(date +%Y-%m-%d_%H-%M-%S)"
for pkg in $STOW_PACKAGES; do
    # Move away real files that are in the way (links into this repo are fine)
    (cd "$pkg" && find . -type f) | while read -r rel; do
        target="$HOME/${rel#./}"
        if [ -e "$target" ] && ! readlink -f "$target" | grep -q "^$REPO/"; then
            mkdir -p "$backup/$(dirname "${rel#./}")"
            mv "$target" "$backup/${rel#./}"
            echo "backed up ~/${rel#./}"
        fi
    done
    stow -t "$HOME" "$pkg"
done

# Fedora's ~/.bashrc already loads ~/.bashrc.d; elsewhere, add that
if ! grep -q 'bashrc.d' "$HOME/.bashrc" 2>/dev/null; then
    printf '\n# Shell config from ~/dotfiles (bash package)\nfor rc in ~/.bashrc.d/*.sh; do [ -f "$rc" ] && . "$rc"; done\nunset rc\n' >> "$HOME/.bashrc"
fi

say "Building the grayscale icon theme"
"$HOME/.local/bin/make-mono-icons" || echo "Skipped: Papirus is not installed"

say "Applying the color theme"
"$HOME/.local/bin/theme" "$(cat themes/current 2>/dev/null || echo dark)"

say "Done"
if [ -d "$backup" ]; then echo "Old files saved in $backup"; fi
if [ -n "$missing" ]; then echo "Not available on this distro, skipped:$missing"; fi
echo "Log out and pick Sway at the login screen (or run 'sway' from a TTY)."
