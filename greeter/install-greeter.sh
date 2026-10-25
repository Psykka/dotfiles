#!/bin/sh
# Installs the login screen: greetd + tuigreet (user menu, session picker,
# password). The files go to /etc/greetd and /usr/local/bin (outside ~, so
# stow doesn't handle them) and greetd is enabled for the next boot.
#
# Usage: greeter/install-greeter.sh      (asks for the password)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
SUDO=${SUDO:-sudo}

# Console palette from the theme, for the 16 named colors tuigreet uses:
# black is the background, gray the text, darkgray the borders, white the
# highlights (format: one line each for red, green and blue, 16 values)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
python3 -I - "$stage/vtrgb" <<'PY'
import subprocess, sys
get = lambda k: subprocess.run([__import__("os").path.expanduser("~/.local/bin/theme"), "get", k],
                               capture_output=True, text=True).stdout.strip()
order = ["bg0", "red", "green", "yellow", "blue", "magenta", "cyan", "fg",
         "mute", "bright_red", "bright_green", "bright_yellow", "bright_blue", "bright_magenta", "bright_cyan", "hi"]
colors = [get(k) for k in order]
with open(sys.argv[1], "w") as f:
    for i in (0, 2, 4):
        f.write(",".join(str(int(c[i:i + 2], 16)) for c in colors) + "\n")
PY

$SUDO sh -c "
    install -d /etc/greetd
    install -m 644 '$here/config.toml' '$stage/vtrgb' /etc/greetd/
    install -m 755 '$here/login-session' /usr/local/bin/
    # tuigreet remembers the last user and sessions here
    install -d -o greetd -g greetd /var/cache/tuigreet
    systemctl enable greetd
    systemctl set-default graphical.target
"
echo "Login screen installed; it shows up at the next boot."
