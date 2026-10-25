#!/bin/sh
# System-wide package manager settings (outside ~, so stow doesn't handle
# them). Fedora: dnf downloads 10 packages at once and Enter means yes.
# Arch: pacman downloads 10 at once, with color (Enter is yes already).
# Debian: apt has nothing to change (Enter is yes; no parallel downloads).
#
# Usage: system/install-system.sh      (asks for the password)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
SUDO=${SUDO:-sudo}
. /etc/os-release

case "$ID ${ID_LIKE:-}" in
    *fedora*)
        $SUDO install -D -m 644 "$here/dnf.conf" /etc/dnf/libdnf5.conf.d/20-dotfiles.conf ;;
    *arch*)
        $SUDO sed -i -e 's/^#\?ParallelDownloads.*/ParallelDownloads = 10/' -e 's/^#Color$/Color/' /etc/pacman.conf ;;
esac
echo "Package manager settings applied."
