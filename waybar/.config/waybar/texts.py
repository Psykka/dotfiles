"""The words of the bar: every text its popups, menus and notifications
show lives in texts/en.ini next to this file, so they can be read and
reworded in one place (and, one day, come in another language).

tr("section.key", name=value) gives the text of `key` under `[section]`,
with its {name} fields filled in (str.format). In the INI each text is in
double quotes (JSON), so spaces at its ends and line breaks survive.
dev/texts-check.py checks that every key used is there, and none is left
unused. (tr, not t: t is a common name for a local, which would hide it.)
"""
import configparser
import json
import os

FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "texts", "en.ini")


def load(path=FILE):
    parser = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",), empty_lines_in_values=False)
    parser.optionxform = str  # keys as written
    parser.read(path, encoding="utf-8")
    return {sec: {k: json.loads(v) for k, v in parser[sec].items()} for sec in parser.sections()}


TEXTS = load()


def tr(key, **values):
    section, _, name = key.partition(".")
    text = TEXTS[section][name]
    return text.format(**values) if values else text
