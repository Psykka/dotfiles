#!/bin/sh
# System menu (Super+Escape, or "System" in the launcher): settings, tools
# and power, kept apart from the apps. Power actions ask for confirmation.
# Usage: menu.sh          the whole menu
#        menu.sh ACTION   run one entry: keybindings clipboard screenshot
#                         notifications sound displays bluetooth wallpaper logo
#                         lock logout reboot poweroff (the launcher uses this)

# Font Awesome glyphs as UTF-8 bytes, since they are private-use characters
keyboard=$(printf '\357\204\234')
clipboard=$(printf '\357\214\250')
camera=$(printf '\357\200\260')
bell=$(printf '\357\203\263')
volume=$(printf '\357\200\250')
display=$(printf '\357\204\210')
bluetooth=$(printf '\357\212\223')
shapes=$(printf '\357\230\237')
image=$(printf '\357\200\276')
lock=$(printf '\357\200\243')
logout=$(printf '\357\213\265')
reboot=$(printf '\357\213\271')
power=$(printf '\357\200\221')
check=$(printf '\357\200\214')
no=$(printf '\357\200\215')
fedora=$(printf '\357\236\230')
ubuntu=$(printf '\357\237\237')
debian=$(printf '\356\230\213')
redhat=$(printf '\357\236\274')
centos=$(printf '\357\236\211')
opensuse=$(printf '\357\237\226')
tux=$(printf '\357\205\274')
auto=$(printf '\357\203\220')

# The words (texts/en.ini, shared with the bar's popups)
. ~/.config/waybar/texts.sh

menu() {
    fuzzel --dmenu -p "$1" --placeholder=""
}

# The entries: action, its icon (a variable above), its text's key in [menu].
# A pick is known by the line it shows, built the same way: the words can
# change in the texts without touching this
ENTRIES="keybindings:keyboard:keybindings clipboard:clipboard:clipboard-history
screenshot:camera:screenshot-area notifications:bell:notifications sound:volume:sound
displays:display:displays bluetooth:bluetooth:bluetooth wallpaper:image:wallpaper
logo:shapes:bar-logo lock:lock:lock logout:logout:log-out reboot:reboot:reboot
poweroff:power:power-off"

# entry ACTION: its "icon-variable:text-key"
entry() {
    for e in $ENTRIES; do
        [ "${e%%:*}" = "$1" ] && echo "${e#*:}"
    done
}

# icon ACTION, words ACTION, line ACTION: an entry's glyph, text, menu line
icon() {
    eval "printf '%s' \"\$$(entry "$1" | cut -d: -f1)\""
}
words() {
    text "menu.$(entry "$1" | cut -d: -f2)"
}
line() {
    printf '%s  %s\n' "$(icon "$1")" "$(words "$1")"
}

# confirm ACTION: asks Yes or No, with the action's own words
confirm() {
    yes="$(icon "$1")  $(text menu.yes)"
    pick=$(printf '%s  %s\n%s\n' "$no" "$(text menu.no)" "$yes" | menu "$(text menu.ask action="$(words "$1")") ")
    [ "$pick" = "$yes" ]
}

power() {
    case $1 in
        lock)     confirm lock && exec lock ;;
        logout)   confirm logout && exec swaymsg exit ;;
        reboot)   confirm reboot && exec systemctl reboot ;;
        poweroff) confirm poweroff && exec systemctl poweroff ;;
    esac
}

# Bar logo, saved in the palette (logo= in ~/dotfiles/themes/dark.ini)
logo() {
    current=$(~/.local/bin/theme get logo)
    choice=$(for name in auto fedora ubuntu debian redhat centos opensuse tux; do
        eval "glyph=\$$name"
        mark=" "; [ "$name" = "$current" ] && mark=$check
        printf '%s  %s  %s\n' "$mark" "$glyph" "$name"
    done | menu "$(text menu.logo-prompt)") || exit 0
    exec ~/.local/bin/theme set logo "${choice##* }"
}

system() {
    for e in $ENTRIES; do
        action=${e%%:*}
        # Only where there is a Bluetooth adapter
        [ "$action" = bluetooth ] && [ -z "$(ls -A /sys/class/bluetooth 2>/dev/null)" ] && continue
        line "$action"
    done | menu "$(text menu.prompt)"
}

run() {
    case $1 in
        keybindings)   exec ~/.config/sway/keys.sh ;;
        clipboard)     exec ~/.config/sway/clipboard.sh ;;
        screenshot)    exec ~/.config/sway/screenshot.sh area ;;
        notifications) exec ~/.config/waybar/panel.py calendar ;;
        sound)         exec ~/.config/waybar/panel.py sound ;;
        displays)      exec ~/.config/waybar/panel.py displays ;;
        bluetooth)     exec ~/.config/waybar/panel.py bluetooth ;;
        wallpaper)     exec ~/.config/waybar/panel.py wallpaper ;;
        logo)          logo ;;
        lock|logout|reboot|poweroff) power "$1" ;;
        *) echo "menu.sh: unknown action $1" >&2; exit 1 ;;
    esac
}

if [ -n "${1:-}" ]; then
    run "$1"
    exit 0
fi

pick=$(system) || exit 0
for e in $ENTRIES; do
    if [ "$pick" = "$(line "${e%%:*}")" ]; then
        run "${e%%:*}"
        exit 0
    fi
done
