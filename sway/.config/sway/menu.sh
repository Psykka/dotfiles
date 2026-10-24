#!/bin/sh
# Power menu. Everything asks for confirmation, except Keybindings.
# Usage: menu.sh                          pick from the menu
#        menu.sh lock|logout|reboot|poweroff  confirm and run just that

# Padlock (U+E0A2) as UTF-8 bytes, since it is a private-use character
lock=$(printf '\356\202\242')

menu() {
    fuzzel --dmenu -p "$1" --placeholder=""
}

# confirm ICON QUESTION
confirm() {
    case $(printf '✕  No\n%s  Yes\n' "$1" | menu "$2? ") in
        *Yes) return 0 ;;
        *) return 1 ;;
    esac
}

action=${1:-}
if [ -z "$action" ]; then
    case $(printf '⌨  Keybindings\n%s  Lock\n↪  Log out\n↻  Reboot\n⏻  Power off\n' "$lock" | menu "❯ ") in
        *Keybindings) exec ~/.config/sway/keys.sh ;;
        *Lock)        action=lock ;;
        *"Log out")   action=logout ;;
        *Reboot)      action=reboot ;;
        *"Power off") action=poweroff ;;
        *) exit 0 ;;
    esac
fi

case $action in
    lock)     confirm "$lock" "Lock" && exec swaylock -f ;;
    logout)   confirm "↪" "Log out" && exec swaymsg exit ;;
    reboot)   confirm "↻" "Reboot" && exec systemctl reboot ;;
    poweroff) confirm "⏻" "Power off" && exec systemctl poweroff ;;
esac
