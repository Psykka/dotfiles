#!/bin/bash

# install dependencies
pacman -S picom bspwm polybar sxhkd base-devel --noconfirm

git clone https://aur.archlinux.org/font-awesome-5.git & cd font-awesome-5 & makepkg -si

# install
cp -r .config ~/.config
