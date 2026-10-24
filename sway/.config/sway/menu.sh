#!/bin/sh
# Menu for the ⏻ bar button. Everything asks for confirmation, except Keybindings.

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

case $(printf '⌨  Keybindings\n%s  Lock\n↪  Log out\n↻  Reboot\n⏻  Power off\n' "$lock" | menu "❯ ") in
    *Keybindings) exec ~/.config/sway/keys.sh ;;
    *Lock)        confirm "$lock" "Lock" && exec swaylock -f ;;
    *"Log out")   confirm "↪" "Log out" && exec swaymsg exit ;;
    *Reboot)      confirm "↻" "Reboot" && exec systemctl reboot ;;
    *"Power off") confirm "⏻" "Power off" && exec systemctl poweroff ;;
esac
