#!/bin/bash

# update
cp -r ~/.config/polybar .config
cp -r ~/.config/bspwm .config
cp -r ~/.config/sxhkd .config
cp -r ~/.config/kitty .config
cp -r ~/.config/picom .config

# git push
git add .
git commit -S -m "update files"
git push origin main

