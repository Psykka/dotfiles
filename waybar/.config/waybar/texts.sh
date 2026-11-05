# The bar's texts for shell scripts: the same texts/en.ini as texts.py.
#   . ~/.config/waybar/texts.sh
#   text menu.lock                 -> Lock
#   text volume.level level=45     -> Volume 45%
# Each text is in double quotes in the INI (JSON): the quotes come off and
# \" \n \\ are read back. dev/texts-check.py finds these calls.

TEXTS_FILE=${TEXTS_FILE:-$HOME/.config/waybar/texts/en.ini}

# text SECTION.KEY [NAME=VALUE ...]
text() {
    _key=$1
    shift
    # The fills through the environment: awk -v would read \ escapes in them
    TEXTS_FILLS=$(printf '%s\037' "$@") awk -v sec="${_key%%.*}" -v key="${_key#*.}" '
        /^\[/ { here = ($0 == "[" sec "]"); next }
        here && index($0, key " = ") == 1 {
            v = substr($0, length(key) + 4)
            v = substr(v, 2, length(v) - 2)
            # JSON escapes, \\ last held aside so it is not read twice
            gsub(/\\\\/, "\001", v); gsub(/\\"/, "\"", v); gsub(/\\n/, "\n", v); gsub(/\001/, "\\", v)
            n = split(ENVIRON["TEXTS_FILLS"], pairs, "\037")
            for (i = 1; i < n; i++) {
                eq = index(pairs[i], "=")
                name = substr(pairs[i], 1, eq - 1); value = substr(pairs[i], eq + 1)
                gsub(/&/, "\\\\&", value)
                gsub("\\{" name "\\}", value, v)
            }
            printf "%s", v
            found = 1
            exit
        }
        END { if (!found) printf "%s", sec "." key }
    ' "$TEXTS_FILE"
}
