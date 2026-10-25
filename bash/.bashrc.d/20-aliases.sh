# Aliases. `ls` stays the plain one.

# Listings with eza: details, and a tree two levels deep
if command -v eza >/dev/null; then
    alias ll='eza -lah --group-directories-first --git'
    alias lt='eza --tree --level=2 --group-directories-first'
else
    alias ll='ls -lah'
fi

# cat with syntax highlighting (bat is called batcat on Debian)
command -v batcat >/dev/null && ! command -v bat >/dev/null && alias bat='batcat'
if command -v bat >/dev/null || command -v batcat >/dev/null; then
    alias cat='bat --paging=never --style=plain'
fi

# System info
alias f='ufetch'
