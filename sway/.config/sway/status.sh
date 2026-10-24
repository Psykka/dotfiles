#!/bin/sh
# Minimal swaybar status: volume + date/time + menu button
# Uses the swaybar JSON protocol to receive clicks

printf '{"version":1,"click_events":true}\n[\n'

# Output: refreshes every 5s, or right away on SIGUSR1 (volume.sh)
(
    trap : USR1
    while :; do
        vol=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null | awk '{
            v = int($2 * 100 + 0.5)
            printf "%s%d%%", ($3 == "[MUTED]" ? "mute " : "vol "), v
        }')
        printf '[{"name":"vol","full_text":"%s","separator":false,"separator_block_width":20},' "$vol"
        printf '{"full_text":"%s","separator":false,"separator_block_width":16},' "$(LC_TIME=C date +'%a %d/%m  %H:%M')"
        printf '{"name":"menu","full_text":"<span font_size=\\"15pt\\" rise=\\"-2pt\\">⏻</span> ","markup":"pango","color":"#89b4fa","separator":false}],\n'
        sleep 5 &
        wait $!
        kill $! 2>/dev/null
    done
) &
echo $! > "${XDG_RUNTIME_DIR:-/tmp}/sway-status.pid"

# The signal is only for the output loop
trap '' USR1

# Input: one JSON event per line for each click/scroll
while read -r ev; do
    ev=$(printf '%s' "$ev" | tr -d ' ')
    case $ev in
        *'"name":"menu"'*) swaymsg exec ~/.config/sway/menu.sh >/dev/null ;;
        *'"name":"vol"'*)
            case $ev in
                *'"button":4'*) ~/.config/sway/volume.sh up ;;
                *'"button":5'*) ~/.config/sway/volume.sh down ;;
            esac ;;
    esac
done
