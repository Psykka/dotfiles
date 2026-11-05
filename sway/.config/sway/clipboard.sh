#!/bin/sh
# Clipboard history: pick an entry and copy it again
. ~/.config/waybar/texts.sh
cliphist list | fuzzel --dmenu -p "$(text clipboard.prompt)" | cliphist decode | wl-copy
