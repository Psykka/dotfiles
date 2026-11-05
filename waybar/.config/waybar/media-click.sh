#!/bin/sh
# Clicks on the media island: it shows while something is playing or
# paused (dimmed), and is hidden when nothing is loaded; a click then (the
# bar redrawing late) does nothing. Usage: media-click.sh panel|focus|toggle
case "$(playerctl status 2>/dev/null)" in Playing|Paused) ;; *) exit 0 ;; esac
case $1 in
    panel)  exec ~/.config/waybar/panel.py media ;;
    focus)  exec ~/.config/waybar/media-focus.sh ;;
    toggle) exec playerctl play-pause ;;
esac
