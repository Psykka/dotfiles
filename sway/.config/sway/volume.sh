#!/bin/sh
# Volume: up, down or mute (steps of 5, max 100%)

case $1 in
    up)   wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ ;;
    down) wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- ;;
    mute) wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle ;;
    *)    echo "usage: $0 up|down|mute" >&2; exit 1 ;;
esac
