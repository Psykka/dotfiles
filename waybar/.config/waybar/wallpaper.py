#!/usr/bin/env python3
"""Wallpapers: Wallhaven search and downloads, the ones already here, edits
of the picture (brightness, saturation, blur), colors taken from it, and
trying one out before keeping it.

Used by the wallpaper panel (panel.py wallpaper). Nothing is saved until
save(): preview() and show() only change the screen, revert() puts back
what is saved. Saved choices go to ~/.local/state/theme-local.ini through
`theme local`, on top of the palette, so the repo stays as it is.

Downloads go to ~/Pictures/Wallpapers, edited copies to its "edited"
folder, thumbnails to ~/.cache/wallpaper. Edits need ImageMagick; colors
use it too when it is there. NSFW results need a Wallhaven API key in
~/.local/state/wallhaven-key.

Usage: wallpaper.py colors FILE      main colors of a picture
       wallpaper.py search [QUERY]   first page of Wallhaven results
"""
import colorsys
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

HOME = pathlib.Path.home()
THEME = str(HOME / ".local/bin/theme")
DOWNLOADS = HOME / "Pictures/Wallpapers"
EDITED = DOWNLOADS / "edited"
BUILTIN = HOME / ".local/share/wallpapers"  # wallpapers package
CACHE = HOME / ".cache/wallpaper"
KEY_FILE = HOME / ".local/state/wallhaven-key"
IMAGES = (".jpg", ".jpeg", ".png", ".webp")

API = "https://wallhaven.cc/api/v1/search"
SORTS = [("date_added", "Latest"), ("toplist", "Top"), ("views", "Views"),
         ("favorites", "Favorites"), ("random", "Random")]
RANGES = [("1d", "Day"), ("1w", "Week"), ("1M", "Month"), ("3M", "3 months"), ("1y", "Year")]
SIZES = [("", "Any"), ("1920x1080", "1080p"), ("2560x1440", "1440p"), ("3840x2160", "4K")]
RATIOS = [("", "Any"), ("16x9", "16:9"), ("16x10", "16:10"), ("21x9", "21:9"), ("9x16", "Portrait")]
# The only colors Wallhaven searches by
COLORS = ["660000", "990000", "cc0000", "cc3333", "ea4c88", "993399", "663399", "333399",
          "0066cc", "0099cc", "66cccc", "77cc33", "669900", "336600", "666600", "999900",
          "cccc33", "ffff00", "ffcc33", "ff9900", "ff6600", "cc6633", "996633", "663300",
          "000000", "999999", "cccccc", "ffffff", "424153"]
FILTERS = {"q": "", "general": True, "anime": False, "people": False,
           "sfw": True, "sketchy": False, "nsfw": False,
           "sorting": "toplist", "range": "1M", "atleast": "", "ratio": "", "color": ""}

# Palette keys the colors from a wallpaper replace: the grays keep their
# lightness (so contrast stays as the theme has it) and take the
# wallpaper's hue; the accent is one of the wallpaper's colors
GRAYS = ["bg0", "bg1", "surface", "bg2", "line", "faint", "off", "mute", "sub", "fg", "hi", "island"]
COLOR_KEYS = GRAYS + ["accent"]
STYLE = {"tint": 0.12, "shade": 0.0, "light": 0.75}
PRESETS = [("Subtle", {"tint": 0.06, "shade": 0.0, "light": 0.78}),
           ("Tinted", {"tint": 0.14, "shade": 0.0, "light": 0.74}),
           ("Vivid", {"tint": 0.24, "shade": 0.01, "light": 0.68}),
           ("Pastel", {"tint": 0.10, "shade": 0.02, "light": 0.84}),
           ("Dim", {"tint": 0.08, "shade": -0.03, "light": 0.70})]
EDIT = {"brightness": 100, "saturation": 100, "blur": 0}

# Thumbnails downloaded at once
SLOTS = threading.Semaphore(6)


def has_magick():
    return bool(shutil.which("magick") or shutil.which("convert"))


def magick(*args):
    cmd = ["magick"] if shutil.which("magick") else ["convert"]
    return subprocess.run(cmd + [str(a) for a in args], capture_output=True, text=True)


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "dotfiles-wallpaper"})
    return urllib.request.urlopen(req, timeout=timeout)


# --------------------------------------------------------------- wallhaven

def api_key():
    try:
        return KEY_FILE.read_text().strip()
    except OSError:
        return ""


def search(f, page=1, seed=None):
    """One page of results: {"items", "page", "last", "total", "seed"}.
    Raises OSError when Wallhaven can't be reached."""
    def bits(*names):
        out = "".join("1" if f[n] else "0" for n in names)
        return out if "1" in out else "1" + "0" * (len(names) - 1)

    params = {"q": f["q"], "categories": bits("general", "anime", "people"),
              "purity": bits("sfw", "sketchy", "nsfw"), "sorting": f["sorting"],
              "order": "desc", "page": page}
    if f["sorting"] == "toplist":
        params["topRange"] = f["range"]
    if f["atleast"]:
        params["atleast"] = f["atleast"]
    if f["ratio"]:
        params["ratios"] = f["ratio"]
    if f["color"]:
        params["colors"] = f["color"]
    if seed:
        params["seed"] = seed
    if api_key():
        params["apikey"] = api_key()
    try:
        with fetch(API + "?" + urllib.parse.urlencode(params)) as r:
            data = json.load(r)
    except ValueError as e:
        raise OSError(f"bad answer from Wallhaven ({e})")
    meta = data.get("meta", {})
    items = [{"id": w["id"], "url": w["url"], "path": w["path"], "thumb": w["thumbs"]["small"],
              "resolution": w["resolution"], "size": w["file_size"], "category": w["category"]}
             for w in data.get("data", [])]
    return {"items": items, "page": meta.get("current_page", page), "last": meta.get("last_page", 1),
            "total": meta.get("total", len(items)), "seed": meta.get("seed")}


def file_of(item):
    """Where a Wallhaven wallpaper is (or will be) once downloaded."""
    return DOWNLOADS / os.path.basename(item["path"])


def download(item, progress=None):
    """Downloads a Wallhaven wallpaper (once) and returns its path;
    progress(fraction) is called along the way."""
    dest = file_of(item)
    if dest.exists():
        return dest
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with fetch(item["path"], timeout=30) as r, open(part, "wb") as out:
        total = int(r.headers.get("Content-Length") or item.get("size") or 0)
        done = 0
        while chunk := r.read(65536):
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(min(1.0, done / total))
    part.rename(dest)
    return dest


# ------------------------------------------------------------ local files

def downloaded():
    """Wallpapers here: downloads, newest first, then the wallpapers package."""
    def images(folder):
        try:
            return [p for p in folder.iterdir() if p.suffix.lower() in IMAGES and p.is_file()]
        except OSError:
            return []
    mine = sorted(images(DOWNLOADS), key=lambda p: -p.stat().st_mtime)
    return mine + sorted(images(BUILTIN))


def can_delete(path):
    return pathlib.Path(path).parent in (DOWNLOADS, EDITED)


def delete(path):
    path = pathlib.Path(path)
    if can_delete(path):
        path.unlink(missing_ok=True)
        # And its edited copies
        for p in EDITED.glob(path.stem + "-b*.jpg") if path.parent == DOWNLOADS else []:
            p.unlink(missing_ok=True)


def thumb(source):
    """A small copy (about 300px wide) of a file or a URL, cached; None when
    it can't be had."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if str(source).startswith("http"):
        out = CACHE / ("wh-" + os.path.basename(source))
        if not out.exists():
            with SLOTS:
                try:
                    with fetch(source, timeout=15) as r:
                        data = r.read()
                except OSError:
                    return None
                out.write_bytes(data)
        return out
    path = pathlib.Path(source)
    try:
        stamp = f"{path.resolve()}:{path.stat().st_mtime}"
    except OSError:
        return None
    out = CACHE / ("local-" + hashlib.md5(stamp.encode()).hexdigest() + ".jpg")
    if not out.exists():
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 320, 320, True)
            pix.savev(str(out), "jpeg", ["quality"], ["88"])
        except Exception:  # GLib.Error, or a file that is not an image
            return None
    return out


def square(source, size=128):
    """A square cut from the middle of a picture, cached: the biggest an icon
    gets in a notification (mako shows up to 64px)."""
    small = thumb(source)
    if not small:
        return None
    out = CACHE / ("square-" + small.stem + ".png")
    if not out.exists():
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file(str(small))
        except Exception:
            return None
        side = min(pix.get_width(), pix.get_height())
        cut = pix.new_subpixbuf((pix.get_width() - side) // 2, (pix.get_height() - side) // 2, side, side)
        cut.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR).savev(str(out), "png", [], [])
    return out


# ------------------------------------------------------------------- edits

def edit(path, brightness=100, saturation=100, blur=0):
    """The picture with these edits (a copy in the edited folder), or the
    picture itself when nothing changes."""
    path = pathlib.Path(path)
    if (brightness, saturation, blur) == (100, 100, 0) or not has_magick():
        return path
    out = EDITED / f"{path.stem}-b{brightness}-s{saturation}-r{blur}.jpg"
    if not out.exists():
        EDITED.mkdir(parents=True, exist_ok=True)
        args = [path, "-modulate", f"{brightness},{saturation},100"]
        if blur:
            args += ["-blur", f"0x{blur}"]
        if magick(*args, "-quality", "92", out).returncode != 0:
            return path
    return out


def original(path):
    """(picture, edits) behind a wallpaper: an edited copy names both."""
    path = pathlib.Path(path)
    m = re.fullmatch(r"(.+)-b(\d+)-s(\d+)-r(\d+)", path.stem)
    if path.parent == EDITED and m:
        for folder in (DOWNLOADS, BUILTIN):
            for p in folder.glob(m.group(1) + ".*") if folder.is_dir() else []:
                if p.suffix.lower() in IMAGES:
                    return p, {"brightness": int(m.group(2)), "saturation": int(m.group(3)),
                               "blur": int(m.group(4))}
    return path, dict(EDIT)


# ------------------------------------------------------------------ colors

def rgb(hexa):
    return tuple(int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hexa(r, g, b):
    return "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in (r, g, b))


def luminance(color):
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(lin, rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def swatches(path, n=6):
    """The main colors of a picture: [(hex, share)], biggest first."""
    counts = {}
    if has_magick():
        out = magick(path, "-resize", "160x160", "-colors", "16", "-format", "%c", "histogram:info:-").stdout
        for m in re.finditer(r"(\d+):\s*\([^)]*\)\s*#([0-9A-Fa-f]{6})", out):
            counts[m.group(2).lower()] = counts.get(m.group(2).lower(), 0) + int(m.group(1))
    if not counts:
        # Without ImageMagick: average of each 3-bit bucket of a small copy
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 80, 80, True)
        except Exception:
            return []
        data, stride, nc = pix.get_pixels(), pix.get_rowstride(), pix.get_n_channels()
        buckets = {}
        for y in range(pix.get_height()):
            for x in range(pix.get_width()):
                i = y * stride + x * nc
                r, g, b = data[i], data[i + 1], data[i + 2]
                s = buckets.setdefault((r >> 5, g >> 5, b >> 5), [0, 0, 0, 0])
                s[0] += r
                s[1] += g
                s[2] += b
                s[3] += 1
        for r, g, b, k in buckets.values():
            counts[hexa(r / k / 255, g / k / 255, b / k / 255)] = k
    total = sum(counts.values()) or 1
    out = []
    # Close colors count as one
    for color, k in sorted(counts.items(), key=lambda c: -c[1]):
        near = next((o for o in out if sum((a - b) ** 2 for a, b in zip(rgb(o[0]), rgb(color))) < 0.012), None)
        if near:
            near[1] += k / total
        else:
            out.append([color, k / total])
    return [tuple(o) for o in sorted(out, key=lambda o: -o[1])[:n]]


def hls(color):
    return colorsys.rgb_to_hls(*rgb(color))


def from_hls(h, l, s):
    return hexa(*colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s))))


def chroma(color):
    """How much color there is (HLS saturation calls near-black "vivid")."""
    return max(rgb(color)) - min(rgb(color))


def vivid(found):
    """Index of the swatch that makes the best accent."""
    def score(c):
        l = hls(c[0])[1]
        return chroma(c[0]) * c[1] ** 0.3 * (1 if 0.15 < l < 0.9 else 0.3)
    return max(range(len(found)), key=lambda i: score(found[i])) if found else 0


def derive(base, found, accent=None, tint=STYLE["tint"], shade=STYLE["shade"], light=STYLE["light"]):
    """Palette colors from the swatches of a wallpaper: {key: hex}."""
    if not found:
        return {}
    # Hue of the backgrounds: the biggest color that has some color in it
    dom = max(found, key=lambda c: c[1] * (0.05 + chroma(c[0])))
    dh = hls(dom[0])[0]
    strength = min(1.0, chroma(dom[0]) / 0.12)
    out = {}
    for key in GRAYS:
        _, l, _ = hls(base[key])
        dark = l < 0.5
        out[key] = from_hls(dh, l + shade * (1 if dark else 0.3), tint * strength * (1 if dark else 0.4))
    pick = found[accent if accent is not None and accent < len(found) else vivid(found)][0]
    ah, _, sat = hls(pick)
    # A gray accent stays gray
    sat = min(0.8, max(0.3, sat)) if chroma(pick) > 0.06 else 0.0
    # Bright enough to read on the background, and to hold dark text
    color = from_hls(ah, light, sat)
    while contrast(color, out["bg0"]) < 4.5 and light < 0.95:
        light += 0.02
        color = from_hls(ah, light, sat)
    out["accent"] = color
    return out


# ------------------------------------------------- on screen, and saved

def theme(*args):
    return subprocess.run([THEME, *args], capture_output=True, text=True).stdout


def base_palette():
    """The repo's palette, without this machine's choices."""
    try:
        return json.loads(theme("dump", "base"))
    except ValueError:
        return {}


def saved():
    """(wallpaper, {color key: hex}) as saved."""
    local = dict(l.split("=", 1) for l in theme("local").splitlines() if "=" in l)
    wall = os.path.expanduser(theme("get", "wallpaper").strip())
    return wall, {k: v for k, v in local.items() if k in COLOR_KEYS}


def values(path, colors):
    # An empty value means the palette's own color
    return [f"wallpaper={path}"] + [f"{k}={colors.get(k, '')}" for k in COLOR_KEYS]


def show(path, bg):
    """Just the picture, when the colors stay as they are."""
    subprocess.run(["swaymsg", f"output * bg {path} fill #{bg}"], stdout=subprocess.DEVNULL)


def preview(path, colors):
    theme("preview", *values(path, colors))


def save(path, colors):
    theme("local", *values(path, colors))


def revert():
    theme("preview")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "colors" and len(sys.argv) == 3:
        for color, share in swatches(sys.argv[2]):
            print(f"#{color}  {share:5.1%}")
    elif cmd == "search":
        res = search({**FILTERS, "q": " ".join(sys.argv[2:])})
        print(f"page {res['page']} of {res['last']}, {res['total']} wallpapers")
        for w in res["items"]:
            print(w["id"], w["resolution"], w["path"])
    else:
        sys.exit(__doc__.split("\n\n")[-1])


if __name__ == "__main__":
    main()
