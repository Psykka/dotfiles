#!/bin/sh
# Volume: up, down or mute (steps of 5, max 100%), with the on-screen indicator

case $1 in
    up)   wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ ;;
    down) wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- ;;
    mute) wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle ;;
    *)    echo "usage: $0 up|down|mute" >&2; exit 1 ;;
esac

# "Volume: 0.45" or "Volume: 0.45 [MUTED]"
set -- $(wpctl get-volume @DEFAULT_AUDIO_SINK@)
level=$(awk -v v="$2" 'BEGIN { printf "%d", v * 100 + 0.5 }')
if [ "${3:-}" = "[MUTED]" ]; then
    ~/.config/sway/osd.sh volume "Muted" 0
else
    ~/.config/sway/osd.sh volume "Volume $level%" "$level"
fi
