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

menu() {
    fuzzel --dmenu -p "$1" --placeholder=""
}

# confirm ICON QUESTION
confirm() {
    case $(printf '%s  No\n%s  Yes\n' "$no" "$1" | menu "$2? ") in
        *Yes) return 0 ;;
        *) return 1 ;;
    esac
}

power() {
    case $1 in
        lock)     confirm "$lock" "Lock" && exec lock ;;
        logout)   confirm "$logout" "Log out" && exec swaymsg exit ;;
        reboot)   confirm "$reboot" "Reboot" && exec systemctl reboot ;;
        poweroff) confirm "$power" "Power off" && exec systemctl poweroff ;;
    esac
}

# Bar logo, saved in the palette (logo= in ~/dotfiles/themes/dark.ini)
logo() {
    current=$(~/.local/bin/theme get logo)
    choice=$(for name in auto fedora ubuntu debian redhat centos opensuse tux; do
        eval "glyph=\$$name"
        mark=" "; [ "$name" = "$current" ] && mark=$check
        printf '%s  %s  %s\n' "$mark" "$glyph" "$name"
    done | menu "logo ❯ ") || exit 0
    exec ~/.local/bin/theme set logo "${choice##* }"
}

system() {
    {
        printf '%s  Keybindings\n' "$keyboard"
        printf '%s  Clipboard history\n' "$clipboard"
        printf '%s  Screenshot (area)\n' "$camera"
        printf '%s  Notifications\n' "$bell"
        printf '%s  Sound\n' "$volume"
        printf '%s  Displays\n' "$display"
        # Only where there is a Bluetooth adapter
        [ -n "$(ls -A /sys/class/bluetooth 2>/dev/null)" ] && printf '%s  Bluetooth\n' "$bluetooth"
        printf '%s  Wallpaper\n' "$image"
        printf '%s  Bar logo\n' "$shapes"
        printf '%s  Lock\n%s  Log out\n%s  Reboot\n%s  Power off\n' "$lock" "$logout" "$reboot" "$power"
    } | menu "system ❯ "
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

case $(system) in
    *Keybindings)   run keybindings ;;
    *Clipboard*)    run clipboard ;;
    *Screenshot*)   run screenshot ;;
    *Notifications) run notifications ;;
    *Sound)         run sound ;;
    *Displays)      run displays ;;
    *Bluetooth)     run bluetooth ;;
    *Wallpaper)     run wallpaper ;;
    *"Bar logo")    run logo ;;
    *Lock)          run lock ;;
    *"Log out")     run logout ;;
    *Reboot)        run reboot ;;
    *"Power off")   run poweroff ;;
esac
