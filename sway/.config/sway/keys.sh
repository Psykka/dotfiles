#!/bin/sh
# Lists the sway keybindings in fuzzel; Enter runs the selected one.
# Numbered bindings (Super+1..6) collapse into one line; picking it asks for the number.

config=${1:-$HOME/.config/sway/config}

sel=$(awk '
    # What a binding does, from its command. Unknown commands fall back
    # to the comment above them in the config, then to the raw command.
    function describe(cmd) {
        if (cmd ~ /^exec alacritty/)                  return "Open terminal"
        if (cmd ~ /^exec fuzzel$/)                    return "App launcher"
        if (cmd ~ /screenshot\.sh area$/)            return "Screenshot (area)"
        if (cmd ~ /screenshot\.sh/)                  return "Screenshot"
        if (cmd ~ /cliphist list/)                    return "Clipboard history"
        if (cmd ~ /keys\.sh$/)                        return "Show keybindings"
        if (cmd ~ /menu\.sh$/)                        return "Power menu"
        if (cmd ~ /volume\.sh up$/)                   return "Volume up"
        if (cmd ~ /volume\.sh down$/)                 return "Volume down"
        if (cmd ~ /volume\.sh mute$/)                 return "Mute audio"
        if (cmd ~ /swaylock/)                         return "Lock screen"
        if (cmd == "kill")                            return "Close window"
        if (cmd == "reload")                          return "Reload config"
        if (cmd ~ /^workspace number $/)              return "Go to workspace"
        if (cmd ~ /^move container to workspace number $/) return "Move window to workspace"
        return sec != "" ? sec : cmd
    }

    # Readable key names: Mod4+Shift+q -> Super + Shift + Q
    function keynames(k,    n, parts, i, s, out) {
        n = split(k, parts, "+")
        for (i = 1; i <= n; i++) {
            s = parts[i]
            if      (s == "Mod4")                 s = "Super"
            else if (s == "Mod1")                 s = "Alt"
            else if (s == "Control")              s = "Ctrl"
            else if (s == "Escape")               s = "Esc"
            else if (s == "space")                s = "Space"
            else if (s == "slash")                s = "/"
            else if (s == "equal")                s = "="
            else if (s == "minus")                s = "-"
            else if (s == "Return")               s = "Enter"
            else if (s == "XF86AudioRaiseVolume") s = "Volume Up key"
            else if (s == "XF86AudioLowerVolume") s = "Volume Down key"
            else if (s == "XF86AudioMute")        s = "Mute key"
            else if (length(s) == 1)              s = toupper(s)
            out = out (i > 1 ? " + " : "") s
        }
        return out
    }

    # Variables: set $mod Mod4
    $1 == "set" { vars[$2] = $3; next }

    # The comment above a binding is the fallback description ("# Lock: ..." -> "Lock")
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

        # Key and command ending in the same number: group them
        if (match(key, /[0-9]$/) && substr(line, length(line)) == substr(key, length(key))) {
            n = substr(key, length(key))
            base = substr(key, 1, length(key) - 1)
            tpl = substr(line, 1, length(line) - 1)
            id = base SUBSEP tpl
            if (!(id in lo)) {
                order[++count] = "g" SUBSEP id
                gdesc[id] = describe(tpl)
                lo[id] = hi[id] = n
            }
            if (n < lo[id]) lo[id] = n
            if (n > hi[id]) hi[id] = n
            next
        }

        order[++count] = "k" SUBSEP keynames(key) SUBSEP describe(line) SUBSEP line
    }

    END {
        for (c = 1; c <= count; c++) {
            split(order[c], f, SUBSEP)
            if (f[1] == "k") {
                printf "%-28s %s\t%s\n", f[3], f[2], f[4]
            } else {
                id = f[2] SUBSEP f[3]
                r = lo[id] ".." hi[id]
                keys = keynames(substr(f[2], 1, length(f[2]) - 1))
                printf "%-28s %s + %s\t@%s %s %s{n}\n", gdesc[id], keys, r, lo[id], hi[id], f[3]
            }
        }
    }
' "$config" | fuzzel --dmenu --with-nth=1 --match-nth=1 --accept-nth=2 -p "keys ❯ ") || exit 0

case $sel in
    "")
        exit 0 ;;
    @*)
        # Group: "@lo hi command {n}" -> ask for the number
        set -- ${sel#@}
        lo=$1 hi=$2
        tpl=${sel#@"$lo" "$hi" }
        n=$(seq "$lo" "$hi" | fuzzel --dmenu -p "${tpl%\{n\}}") || exit 0
        [ -n "$n" ] && swaymsg -- "${tpl%\{n\}}$n" >/dev/null ;;
    *)
        swaymsg -- "$sel" >/dev/null ;;
esac
