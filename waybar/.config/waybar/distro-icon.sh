#!/bin/sh
# Prints the bar logo. The choice comes from the palette (logo= in
# ~/dotfiles/themes/dark.ini, written to ~/.config/waybar/logo by `theme`):
# fedora, ubuntu, debian, redhat, centos, opensuse, tux, or auto to detect
# the running distro (anything without a Font Awesome logo, like Arch,
# gets tux). Glyphs are UTF-8 bytes because they are private-use characters.

choice=$(cat ~/.config/waybar/logo 2>/dev/null || echo auto)

if [ "$choice" = auto ]; then
    . /etc/os-release
    choice=tux
    for id in $ID ${ID_LIKE:-}; do
        case $id in
            fedora|ubuntu|debian|centos) choice=$id; break ;;
            rhel) choice=redhat; break ;;
            *suse*) choice=opensuse; break ;;
        esac
    done
fi

logo() {
    case $1 in
        fedora) printf '\357\236\230' ;;
        ubuntu) printf '\357\237\237' ;;
        debian) printf '\356\230\213' ;;
        redhat) printf '\357\236\274' ;;
        centos) printf '\357\236\211' ;;
        opensuse) printf '\357\237\226' ;;
        tux) printf '\357\205\274' ;;
        *) return 1 ;;
    esac
}
logo "$choice" || logo tux
