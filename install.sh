#!/bin/bash

# install dependencies
sudo pacman -S git adobe-source-han-serif-jp-fonts picom bspwm polybar sxhkd kitty dmenu base-devel --noconfirm

git clone https://aur.archlinux.org/font-awesome-5.git & cd font-awesome-5 & makepkg -si

# install
cp -r .config/* ~/.config
