#!/bin/sh
# Screenshot of the whole screen or of an area: saves it, copies it to
# the clipboard and shows a notification.
# Usage: screenshot.sh screen|area

dir="$HOME/Pictures/Screenshots"
file="$dir/$(date +'%Y-%m-%d_%H-%M-%S').png"
mkdir -p "$dir"

# Selection colors from the palette
. ~/.config/sway/theme.env

case $1 in
    area)
        # shellcheck disable=SC2086
        geometry=$(slurp $SLURP_ARGS) || exit 0  # Esc cancels
        grim -g "$geometry" "$file" ;;
    *)
        grim "$file" ;;
esac || exit 1

wl-copy --type image/png < "$file"
notify-send -a Screenshot -i "$file" "Screenshot" "Saved to ~/Pictures/Screenshots and copied"
