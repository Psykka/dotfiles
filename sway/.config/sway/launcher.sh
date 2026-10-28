#!/bin/sh
# App launcher (fuzzel). Keeps the "System" entry pinned at the top: fuzzel
# sorts by how often each app was launched, so before opening it the cache
# gives System one launch more than the most used app.

cache="${XDG_CACHE_HOME:-$HOME/.cache}/fuzzel"
entry="sys-menu.desktop"

if [ -f "$cache" ]; then
    top=$(awk -F'|' -v e="$entry" '$1 != e && $2 > max { max = $2 } END { print max + 1 }' "$cache")
    awk -F'|' -v e="$entry" '$1 != e' "$cache" > "$cache.tmp"
    echo "$entry|$top" >> "$cache.tmp"
    mv "$cache.tmp" "$cache"
fi

# The apps chosen to use the VPN open through it (vpn-launch.sh)
exec fuzzel --launch-prefix="$HOME/.config/sway/vpn-launch.sh" "$@"
