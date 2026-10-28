#!/bin/sh
# The launcher's prefix (launcher.sh): the apps chosen in the menu's VPN page
# (~/.local/state/vpn-apps) open through the VPN; everything else as usual,
# without waiting on anything. fuzzel passes the app's desktop entry id in
# DESKTOP_ENTRY_ID.
apps="${XDG_STATE_HOME:-$HOME/.local/state}/vpn-apps"
if [ -n "${DESKTOP_ENTRY_ID:-}" ] && grep -qxF "$DESKTOP_ENTRY_ID" "$apps" 2>/dev/null; then
    exec "$HOME/.config/waybar/vpn.py" run -- "$@"
fi
exec "$@"
