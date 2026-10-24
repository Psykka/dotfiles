#!/bin/sh
# Clipboard history: pick an entry and copy it again
cliphist list | fuzzel --dmenu -p "clipboard ❯ " | cliphist decode | wl-copy
