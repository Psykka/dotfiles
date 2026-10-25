#!/bin/sh
# Clicks on the media island only do something while it is visible, that
# is, while something is playing (when paused, the island is hidden but
# still under the mouse). Usage: media-click.sh panel|focus|toggle
[ "$(playerctl status 2>/dev/null)" = Playing ] || exit 0
case $1 in
    panel)  exec ~/.config/waybar/panel.py media ;;
    focus)  exec ~/.config/waybar/media-focus.sh ;;
    toggle) exec playerctl play-pause ;;
esac
