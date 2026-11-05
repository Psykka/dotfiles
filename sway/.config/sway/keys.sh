#!/bin/sh
# Lists the sway keybindings in fuzzel; Enter runs the selected one.
# Numbered bindings (Super+1..6) collapse into one line; picking it asks for the number.

config=${1:-$HOME/.config/sway/config}
# The words (texts/en.ini, shared with the bar's popups): its [keys] section
. ~/.config/waybar/texts.sh

sel=$(awk '
    # First file: the texts, [keys] into T, by "keys." and their key (JSON-quoted values)
    FNR == NR {
        if ($0 ~ /^\[/) { here = ($0 == "[keys]"); next }
        if (here && (eq = index($0, " = ")) > 0) {
            v = substr($0, eq + 3); v = substr(v, 2, length(v) - 2)
            gsub(/\\"/, "\"", v)
            T["keys." substr($0, 1, eq - 1)] = v
        }
        next
    }

    # What a binding does, from its command. Unknown commands fall back
    # to the comment above them in the config, then to the raw command.
    function describe(cmd) {
        if (cmd ~ /^exec alacritty/)                  return T["keys.open-terminal"]
        if (cmd ~ /^exec files/)                     return T["keys.open-files"]
        if (cmd ~ /launcher\.sh$/)                    return T["keys.app-launcher"]
        if (cmd ~ /screenshot\.sh area$/)            return T["keys.screenshot-area"]
        if (cmd ~ /screenshot\.sh/)                  return T["keys.screenshot"]
        if (cmd ~ /clipboard\.sh$/)                  return T["keys.clipboard-history"]
        if (cmd ~ /keys\.sh$/)                        return T["keys.show-keybindings"]
        if (cmd ~ /menu\.sh$/)                        return T["keys.system-menu"]
        if (cmd ~ /volume\.sh up$/)                   return T["keys.volume-up"]
        if (cmd ~ /volume\.sh down$/)                 return T["keys.volume-down"]
        if (cmd ~ /volume\.sh mute$/)                 return T["keys.mute-audio"]
        if (cmd ~ /(^| )lock$/)                       return T["keys.lock-screen"]
        if (cmd == "kill")                            return T["keys.close-window"]
        if (cmd == "floating toggle")                 return T["keys.toggle-floating"]
        if (cmd == "fullscreen toggle")               return T["keys.toggle-fullscreen"]
        if (cmd ~ /workspaces\.py prev$/)           return T["keys.previous-workspace"]
        if (cmd ~ /workspaces\.py next$/)           return T["keys.next-workspace"]
        if (cmd ~ /^move container to output left/)  return T["keys.window-to-left"]
        if (cmd ~ /^move container to output right/) return T["keys.window-to-right"]
        if (cmd ~ /^move container to output up/)    return T["keys.window-up"]
        if (cmd ~ /^move container to output down/)  return T["keys.window-down"]
        if (cmd == "reload")                          return T["keys.reload-config"]
        if (cmd ~ /workspaces\.py go $/)            return T["keys.go-to-workspace"]
        if (cmd ~ /workspaces\.py move $/)          return T["keys.window-to-workspace"]
        if (cmd ~ /playerctl play-pause$/)           return T["keys.play-pause"]
        if (cmd ~ /playerctl next$/)                 return T["keys.next-song"]
        if (cmd ~ /playerctl previous$/)             return T["keys.previous-song"]
        if (cmd ~ /panel\.py spotify search$/)      return T["keys.spotify-search"]
        return sec != "" ? sec : cmd
    }

    # Readable key names: Mod4+Shift+q -> Super + Shift + Q
    function keynames(k,    n, parts, i, s, out) {
        n = split(k, parts, "+")
        for (i = 1; i <= n; i++) {
            s = parts[i]
            if      (s == "Mod4")                 s = T["keys.key-super"]
            else if (s == "Mod1")                 s = T["keys.key-alt"]
            else if (s == "Control")              s = T["keys.key-ctrl"]
            else if (s == "Escape")               s = T["keys.key-esc"]
            else if (s == "space")                s = T["keys.key-space"]
            else if (s == "slash")                s = "/"
            else if (s == "equal")                s = "="
            else if (s == "minus")                s = "-"
            else if (s == "Return")               s = T["keys.key-enter"]
            else if (s == "Left")                 s = "←"
            else if (s == "Right")                s = "→"
            else if (s == "Up")                   s = "↑"
            else if (s == "Down")                 s = "↓"
            else if (s == "button4")              s = T["keys.key-scroll-up"]
            else if (s == "button5")              s = T["keys.key-scroll-down"]
            else if (s == "XF86AudioRaiseVolume") s = T["keys.key-volume-up"]
            else if (s == "XF86AudioLowerVolume") s = T["keys.key-volume-down"]
            else if (s == "XF86AudioMute")        s = T["keys.key-mute"]
            else if (s == "XF86AudioPlay")        s = T["keys.key-play"]
            else if (s == "XF86AudioPause")       s = T["keys.key-pause"]
            else if (s == "XF86AudioNext")        s = T["keys.key-next"]
            else if (s == "XF86AudioPrev")        s = T["keys.key-previous"]
            else if (s == "period")               s = "."
            else if (s == "comma")                s = ","
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
' "$TEXTS_FILE" "$config" | fuzzel --dmenu --with-nth=1 --match-nth=1 --accept-nth=2 -p "$(text keys.prompt)") || exit 0

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
