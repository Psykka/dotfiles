#!/bin/sh
# Focuses the window of the app that is playing media

# Most recent player, as tracked by playerctld
player=$(busctl --user get-property org.mpris.MediaPlayer2.playerctld /org/mpris/MediaPlayer2 \
    com.github.altdesktop.playerctld PlayerNames 2>/dev/null | awk -F'"' '{print $2}')
player=${player#org.mpris.MediaPlayer2.}
[ -n "$player" ] || player=$(playerctl -l 2>/dev/null | head -n 1)
[ -n "$player" ] || exit 0

# The window whose process owns the player on D-Bus
pid=$(busctl --user call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus \
    GetConnectionUnixProcessID s "org.mpris.MediaPlayer2.$player" 2>/dev/null | awk '{print $2}')
[ -n "$pid" ] && swaymsg "[pid=$pid] focus" >/dev/null 2>&1 && exit 0

# Otherwise match the app name ("firefox.instance_1_23" -> firefox)
app=${player%%.*}
swaymsg "[app_id=\"(?i)^$app\"] focus" >/dev/null 2>&1 ||
    swaymsg "[class=\"(?i)^$app\"] focus" >/dev/null 2>&1
