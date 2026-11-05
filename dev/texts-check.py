#!/usr/bin/env python3
"""Checks the bar's texts (waybar/.config/waybar/texts/en.ini, read by
texts.py's tr()) against the code that uses them:

- every tr("section.key") in the code has its text in the INI;
- every text in the INI is used somewhere (none left behind);
- the {fields} of a text are exactly the names the code passes it.

Python code is read with ast (tr() calls with a literal key); shell scripts
with a regex for their `text section.key` calls (and keys.sh's T["..."]).
menu.sh builds its keys from its entries ("menu.$key"): those are listed
in ENTRIES there and read from it. Exit status 1 on any
problem. Not a stow package: nothing here is linked into ~.

Usage: dev/texts-check.py
"""
import ast
import pathlib
import re
import string
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BAR = ROOT / "waybar/.config/waybar"
sys.path.insert(0, str(BAR))
import texts  # noqa: E402


def fields(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def uses():
    """(file, line, key, names passed or None for a shell script)."""
    found = []
    for path in sorted(ROOT.glob("**/*.py")) + sorted(ROOT.glob("bin/.local/bin/*")):
        if ".git" in path.parts or not path.is_file():
            continue
        src = path.read_text(errors="replace")
        if "tr(" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue  # not Python (a shell script in bin/)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                names = {k.arg for k in node.keywords}
                found.append((path, node.lineno, node.args[0].value, names))
    for path in sorted(ROOT.glob("**/*.sh")):
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            # text menu.lock (texts.sh), and T["keys.x"] in keys.sh's awk
            for key in re.findall(r"\btext \"?([a-z0-9-]+\.[a-z0-9-]+)", line) + \
                    re.findall(r'T\["([a-z0-9-]+\.[a-z0-9-]+)"\]', line):
                found.append((path, n, key, None))
    # menu.sh: "action:icon:key" entries, read as "menu.key"
    menu = ROOT / "sway/.config/sway/menu.sh"
    entries = re.search(r'^ENTRIES="([^"]*)"', menu.read_text(), re.M)
    if entries:
        line = menu.read_text()[:entries.start()].count("\n") + 1
        for e in entries.group(1).split():
            found.append((menu, line, "menu." + e.rsplit(":", 1)[-1], None))
    return found


def main():
    problems = []
    used = set()
    for path, line, key, names in uses():
        where = f"{path.relative_to(ROOT)}:{line}"
        section, _, name = key.partition(".")
        text = texts.TEXTS.get(section, {}).get(name)
        used.add(key)
        if text is None:
            problems.append(f"{where}: {key} isn't in texts/en.ini")
        elif names is not None and fields(text) != names:
            problems.append(f"{where}: {key} has fields {sorted(fields(text))}, the code gives {sorted(names)}")
    for section, items in texts.TEXTS.items():
        for name in items:
            if f"{section}.{name}" not in used:
                problems.append(f"texts/en.ini: {section}.{name} isn't used")
    for p in problems:
        print(p)
    count = sum(len(i) for i in texts.TEXTS.values())
    print(f"texts: {'FAIL, ' + str(len(problems)) + ' problems' if problems else 'ok'} ({count} texts, {len(used)} keys used)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
