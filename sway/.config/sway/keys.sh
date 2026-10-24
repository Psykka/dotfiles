#!/bin/sh
# Lists the sway keybindings in fuzzel; Enter runs the selected one.
# Numbered bindings (Super+1..6) collapse into one line; picking it asks for the number.

config=${1:-$HOME/.config/sway/config}

sel=$(awk '
    # Variables: set $mod Mod4
    $1 == "set" { vars[$2] = $3; next }

    # The comment above a binding becomes its description ("# Lock: ..." -> "Lock")
    /^#[^#]/ {
        sec = $0
        sub(/^# */, "", sec)
        sub(/ *[:(].*$/, "", sec)
        next
    }

    $1 == "bindsym" {
        i = 2
        while ($i ~ /^--/) i++
        key = $i
        line = $0
        sub(/^[ \t]*bindsym[ \t]+/, "", line)
        while (line ~ /^--/) sub(/^[^ \t]+[ \t]+/, "", line)
        sub(/^[^ \t]+[ \t]+/, "", line)

        for (v in vars) {
            while ((p = index(key, v)) > 0)
                key = substr(key, 1, p - 1) vars[v] substr(key, p + length(v))
            while ((p = index(line, v)) > 0)
                line = substr(line, 1, p - 1) vars[v] substr(line, p + length(v))
        }
        sub(/Mod4/, "Super", key)
        sub(/Mod1/, "Alt", key)

        # Key and command ending in the same number: group them
        if (match(key, /[0-9]$/) && substr(line, length(line)) == substr(key, length(key))) {
            n = substr(key, length(key))
            id = substr(key, 1, length(key) - 1) SUBSEP substr(line, 1, length(line) - 1)
            if (!(id in lo)) {
                order[++count] = "g" SUBSEP id
                gsec[id] = sec
                lo[id] = hi[id] = n
            }
            if (n < lo[id]) lo[id] = n
            if (n > hi[id]) hi[id] = n
            next
        }

        order[++count] = "k" SUBSEP key SUBSEP sec SUBSEP line
    }

    END {
        for (c = 1; c <= count; c++) {
            split(order[c], f, SUBSEP)
            if (f[1] == "k") {
                printf "%-16s %-26s %s\t%s\n", f[2], f[3], f[4], f[4]
            } else {
                id = f[2] SUBSEP f[3]
                r = lo[id] ".." hi[id]
                printf "%-16s %-26s %s\t@%s %s %s{n}\n", f[2] r, gsec[id], f[3] r, lo[id], hi[id], f[3]
            }
        }
    }
' "$config" | fuzzel --dmenu --with-nth=1 --match-nth=1 --accept-nth=2 \
    -w 90 -l 15 -p "keys ❯ ") || exit 0

case $sel in
    "")
        exit 0 ;;
    @*)
        # Group: "@lo hi command {n}" -> ask for the number
        set -- ${sel#@}
        lo=$1 hi=$2
        tpl=${sel#@"$lo" "$hi" }
        n=$(seq "$lo" "$hi" | fuzzel --dmenu -l "$((hi - lo + 1))" --minimal-lines \
            -w 40 -p "${tpl%\{n\}}") || exit 0
        [ -n "$n" ] && swaymsg -- "${tpl%\{n\}}$n" >/dev/null ;;
    *)
        swaymsg -- "$sel" >/dev/null ;;
esac
