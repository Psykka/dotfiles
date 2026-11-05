#!/bin/sh
# Installs Spotify Soloist, Spotify's own headless Connect player, into
# ~/.local/bin and runs it as a user service named after the machine.
# It plays where librespot can't: Spotify refuses librespot's audio keys on
# some accounts (librespot issue #1649), Soloist uses the official DRM.
#
# Its builds expire 90 days after they're made, so a weekly timer runs this
# again with --update: it downloads the current build and restarts the
# service only when the version changed. Spotify asks not to redistribute
# the binary, so it always comes from their CDN, never from this repo.
#
# Needs a Soloist API key (https://developer.spotify.com/dashboard/soloist),
# kept in the keyring:
#   secret-tool store --label="Spotify Soloist API key" service soloist key api-key
#
# Usage: soloist/install-soloist.sh [--update]
set -eu

here=$(cd "$(dirname "$0")" && pwd)
URL=https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz
case $(uname -m) in
    aarch64) URL=https://soloist-builds.spotifycdn.com/soloist_release_arm64.tar.gz ;;
    armv7l) URL=https://soloist-builds.spotifycdn.com/soloist_release_arm32.tar.gz ;;
esac
bin="$HOME/.local/bin/soloist"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl --fail -sSL -o "$tmp/soloist.tar.gz" "$URL"
tar -xzf "$tmp/soloist.tar.gz" -C "$tmp" soloist
new=$("$tmp/soloist" --version)
old=$("$bin" --version 2>/dev/null || true)

if [ "$new" != "$old" ]; then
    install -D -m 755 "$tmp/soloist" "$bin"
    echo "Installed $new"
    [ "${1:-}" = --update ] && systemctl --user try-restart soloist.service
else
    echo "Up to date: $new"
fi
[ "${1:-}" = --update ] && exit 0

mkdir -p "$HOME/.config/systemd/user"
cp "$here/soloist.service" "$here/soloist-mpris.service" "$here/soloist-update.service" \
    "$here/soloist-update.timer" "$HOME/.config/systemd/user/"
# The updater runs this very script: point it at where the repo is
sed -i "s|@INSTALLER@|$here/install-soloist.sh|" "$HOME/.config/systemd/user/soloist-update.service"
systemctl --user daemon-reload
systemctl --user enable --now soloist-update.timer

if secret-tool lookup service soloist key api-key >/dev/null 2>&1; then
    # Its MPRIS (soloist-mpris, from the bin package) comes along with it
    systemctl --user enable --now soloist.service soloist-mpris.service
    echo "Pick \"$(hostname)\" once in the Spotify app (same network) to log it in."
else
    echo "Missing the API key: create one at https://developer.spotify.com/dashboard/soloist, then"
    echo "  secret-tool store --label=\"Spotify Soloist API key\" service soloist key api-key"
    echo "  systemctl --user enable --now soloist.service soloist-mpris.service"
fi
