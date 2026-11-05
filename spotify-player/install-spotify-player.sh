#!/bin/sh
# Builds spotify_player with daemon mode (the prebuilt releases leave it
# out) into ~/.local/bin, and starts it as a user service. The bar's media
# popup talks to it through its CLI (playlists, search, queue).
#
# Usage: spotify-player/install-spotify-player.sh      (asks for the password)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
SUDO=${SUDO:-sudo}

. /etc/os-release
case "$ID ${ID_LIKE:-}" in
    *fedora*) $SUDO dnf install -y git cargo openssl-devel alsa-lib-devel dbus-devel pulseaudio-libs-devel ;;
    *arch*) $SUDO pacman -S --needed --noconfirm git rust openssl alsa-lib dbus libpulse ;;
    *debian*|*ubuntu*) $SUDO apt-get install -y git cargo pkg-config libssl-dev libasound2-dev libdbus-1-dev libpulse-dev ;;
    *) echo "Unsupported distro: $ID" >&2; exit 1 ;;
esac

# v0.25.1 asks ncspot's client (its fallback for playlists) to come back
# to /login, which ncspot no longer registers: Spotify answers "redirect_uri:
# Not matching configuration". Same one-line fix as upstream PR #1108;
# back to a plain `cargo install spotify_player` once a release has it.
VERSION=v0.25.1
# Not /tmp: the build takes a few GB, more than a tmpfs usually has
src=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}")
trap 'rm -rf "$src"' EXIT
git clone -q --depth 1 --branch $VERSION https://github.com/aome510/spotify-player "$src"
sed -i 's|^\(pub const NCSPOT_REDIRECT_URI: &str = "http://127.0.0.1:8989/\)login";|\1ncspot_login";|' \
    "$src/spotify_player/src/auth.rs"
grep -q '/ncspot_login"' "$src/spotify_player/src/auth.rs"

# Streaming stays built in (daemon mode needs it) but is off in app.toml:
# Soloist plays (soloist/)
cargo install --path "$src/spotify_player" --locked --root "$HOME/.local" \
    --no-default-features --features daemon,pulseaudio-backend,media-control,streaming

mkdir -p "$HOME/.config/systemd/user"
cp "$here/spotify-player.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
if [ -s "$HOME/.cache/spotify-player/credentials.json" ]; then
    systemctl --user enable --now spotify-player.service
else
    # The first login opens the browser, which a service can't wait on
    echo "Log in once with: spotify_player authenticate"
    echo "then: systemctl --user enable --now spotify-player.service"
fi
