#!/bin/sh
# On-screen indicator: a small notification with a level bar, that replaces
# the previous one of the same kind instead of piling up (mako, [category=osd]).
# Usage: osd.sh KIND TEXT PERCENT    e.g. osd.sh volume "Volume 45%" 45

kind=$1 text=$2 value=$3
idfile="${XDG_RUNTIME_DIR:-/tmp}/osd-$kind"
id=$(cat "$idfile" 2>/dev/null || echo 0)
notify-send -a OSD -c osd -e -p -r "$id" -h "int:value:$value" "$text" > "$idfile"
