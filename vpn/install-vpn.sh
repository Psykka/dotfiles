#!/bin/sh
# Installs the VPN daemon: builds vpn/ (Go) into /usr/local/bin/vpn, the
# system service vpnd.service, and vpn-anchor.service for every user (it
# keeps vpn.slice, where apps mode runs apps). The current user may then
# control it without sudo (/etc/vpn/users). Outside ~, so stow doesn't
# handle it.
#
# Usage: vpn/install-vpn.sh      (asks for the password)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
SUDO=${SUDO:-sudo}
user=${SUDO_USER:-$(id -un)}

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
# A static binary: it runs as root and owes nothing to the libraries around
CGO_ENABLED=0 go build -C "$here" -trimpath -o "$stage/vpn" .
printf '%s\n' "$user" > "$stage/users"

$SUDO sh -c "
    set -e
    install -m 755 '$stage/vpn' /usr/local/bin/vpn
    install -m 644 '$here/vpnd.service' /etc/systemd/system/vpnd.service
    install -m 644 '$here/vpn-anchor.service' /etc/systemd/user/vpn-anchor.service
    install -d -m 755 /etc/vpn
    [ -f /etc/vpn/users ] || install -m 644 '$stage/users' /etc/vpn/users
    systemctl daemon-reload
    systemctl enable vpnd.service
    systemctl restart vpnd.service
    systemctl --global enable vpn-anchor.service
"
systemctl --user daemon-reload 2>/dev/null && systemctl --user start vpn-anchor.service 2>/dev/null || true
echo "VPN daemon installed. Try: vpn import some.conf; vpn up"
