#!/usr/bin/env python3
"""Render the "DAYS SINCE THE LAST MAJOR AI LAB F**KUP" sign as a PNG.

Usage:
    python render_sign.py --days 12 --record 47 --last "2026-01-08 · xAI" \
        --last-title "Grok mass-generates sexualised images of real people" -o sign.png
    python render_sign.py --days 0 --somber -o reset.png
    python render_sign.py --days 12 --censor bar        # see CENSOR_MODES

Pure PIL. Fonts (Anton, Oswald — OFL) are downloaded into ./fonts on first use.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"

# Fonts are OFL (Google Fonts) and are fetched on first use rather than
# committed to the repo. Cached in ./fonts (gitignored).
FONT_URLS = {
    "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "Oswald-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
}


def ensure_fonts() -> None:
    import urllib.request
    FONTS.mkdir(exist_ok=True)
    for name, url in FONT_URLS.items():
        dest = FONTS / name
        if not dest.exists() or dest.stat().st_size < 10_000:
            urllib.request.urlretrieve(url, dest)

W, H = 1600, 900
CREAM = (247, 243, 232)
BLACK = (18, 18, 18)
RED = (196, 30, 30)
YELLOW = (245, 197, 24)
GREY = (110, 110, 110)
DARK = (60, 60, 60)
SOMBER = (70, 70, 70)

# mode → (sign form, tweet/text form). "bar" is drawn as a real black bar on the
# sign; in text it uses unicode block characters.
CENSOR_MODES = {
    "stars":    ("F**KUP", "f**kup"),
    "grawlix":  ("F#@%UP", "f#@%up"),
    "bar":      ("F\u2588KUP", "f\u2588\u2588kup"),   # \u2588 on the sign = draw a bar over "UC"
    "fup":      ("F-UP", "f-up"),
    "stuffup":  ("STUFF-UP", "stuff-up"),
    "incident": ("INCIDENT", "incident"),
    "none":     ("FUCKUP", "fuckup"),
}


def noun_forms(mode: str) -> tuple[str, str]:
    return CENSOR_MODES[mode]


def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    if not (FONTS / name).exists():
        ensure_fonts()
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight is not None:
        try:  # variable fonts (Oswald, Inter)
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def fit(draw, text: str, name: str, max_w: int, start: int, min_size: int = 24,
        weight: int | None = None) -> ImageFont.FreeTypeFont:
    """Largest font size (<= start) at which `text` fits in `max_w`."""
    size = start
    while size > min_size:
        f = font(name, size, weight)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(name, min_size, weight)


def wrap_balanced(draw, text: str, f, max_w: int) -> list[str]:
    """One line if it fits; otherwise the two-line split with the most even widths."""
    if draw.textlength(text, font=f) <= max_w:
        return [text]
    words = text.split()
    best, best_diff = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        wa, wb = draw.textlength(a, font=f), draw.textlength(b, font=f)
        if wa <= max_w and wb <= max_w:
            diff = abs(wa - wb)
            if best is None or diff < best_diff:
                best, best_diff = [a, b], diff
    return best or wrap(draw, text, f, max_w)


def wrap(draw, text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=f) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def hazard_stripes(img: Image.Image, y0: int, y1: int, period: int = 70) -> None:
    band = Image.new("RGB", (W, y1 - y0), YELLOW)
    d = ImageDraw.Draw(band)
    h = y1 - y0
    for x in range(-h, W + period, period):
        d.polygon([(x, 0), (x + period // 2, 0), (x + period // 2 - h, h), (x - h, h)], fill=BLACK)
    img.paste(band, (0, y0))


def text_h(f, text):
    b = f.getbbox(text)
    return b[3] - b[1], b[1]


def centered(draw, text, f, cy, fill):
    tw = draw.textlength(text, font=f)
    th, top = text_h(f, text)
    draw.text(((W - tw) / 2, cy - th / 2 - top), text, font=f, fill=fill)


BAR = "\u2588"


def draw_censored(draw, x: float, y: float, text: str, f, fill, anchor: str = "l") -> float:
    """Draw text at (x, y) [y = vertical centre]; a BAR sentinel becomes a real
    black rectangle the width of "UC". anchor: l / m / r horizontal."""
    parts = text.split(BAR)
    bar_w = draw.textlength("UC", font=f) if len(parts) > 1 else 0
    total = sum(draw.textlength(pt, font=f) for pt in parts) + bar_w * (len(parts) - 1)
    if anchor == "m":
        x -= total / 2
    elif anchor == "r":
        x -= total
    th, top = text_h(f, "DAYS")
    ty = y - th / 2 - top
    for i, pt in enumerate(parts):
        draw.text((x, ty), pt, font=f, fill=fill)
        x += draw.textlength(pt, font=f)
        if i < len(parts) - 1:
            pad = th * 0.08
            draw.rectangle([x + 2, ty + top - pad, x + bar_w - 2, ty + top + th + pad], fill=BLACK)
            x += bar_w
    return total


def render(days: int, *, record: int | None = None, last: str | None = None,
           last_title: str | None = None, somber: bool = False, censor: str = "stars",
           handle: str | None = None) -> Image.Image:
    noun_sign, _ = noun_forms(censor)
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    # frame
    d.rectangle([0, 0, W - 1, H - 1], outline=BLACK, width=18)
    d.rectangle([32, 32, W - 33, H - 33], outline=BLACK, width=4)
    if not somber:
        hazard_stripes(img, 46, 86)
        hazard_stripes(img, H - 86, H - 46)
        d = ImageDraw.Draw(img)

    accent = SOMBER if somber else RED

    # header
    centered(d, "THIS INDUSTRY HAS GONE", font("Oswald-Bold.ttf", 42, 600), 138, BLACK)

    # the number, boxed
    num = str(days)
    f_num = fit(d, num, "Anton-Regular.ttf", 520, 380, min_size=180)
    nb = f_num.getbbox(num)
    nw = d.textlength(num, font=f_num)
    nh = nb[3] - nb[1]
    box_w, box_h = max(int(nw) + 120, 360), 330
    bx0, by0 = (W - box_w) // 2, 180
    d.rectangle([bx0, by0, bx0 + box_w, by0 + box_h], outline=accent, width=10, fill=(255, 255, 255))
    d.text(((W - nw) / 2, by0 + (box_h - nh) / 2 - nb[1]), num, font=f_num, fill=accent)

    # main line
    prefix = "DAYS SINCE THE LAST MAJOR AI LAB "
    f_main = fit(d, (prefix + noun_sign).replace(BAR, "UC"), "Anton-Regular.ttf", W - 200, 92, min_size=48)
    draw_censored(d, W / 2, 590, prefix + noun_sign, f_main, BLACK, anchor="m")

    # footer: record (left) + last-incident label (right), then the description
    f_lab = font("Oswald-Bold.ttf", 28, 500)
    fy = 672
    if not somber and record is not None:
        d.text((110, fy), f"PREVIOUS RECORD: {record} DAYS", font=f_lab, fill=GREY, anchor="lm")
    if last:
        draw_censored(d, W - 110, fy, f"LAST {noun_sign}: {last}", f_lab, GREY, anchor="r")

    if last_title:
        max_w = W - 220
        f_desc = font("Oswald-Bold.ttf", 34, 500)
        lines = wrap_balanced(d, last_title, f_desc, max_w)
        size = 34
        while len(lines) > 2 and size > 24:
            size -= 2
            f_desc = font("Oswald-Bold.ttf", size, 500)
            lines = wrap_balanced(d, last_title, f_desc, max_w)
        if len(lines) > 2:
            lines = lines[:2]
            lines[-1] = lines[-1].rstrip(" ,;:") + "…"
        lh = size + 10
        y0 = 700 + (2 - len(lines)) * lh / 2
        for i, line in enumerate(lines):
            tw = d.textlength(line, font=f_desc)
            d.text(((W - tw) / 2, y0 + i * lh), line, font=f_desc, fill=DARK)

    if handle:  # small, top-right, out of the way of the footer
        d.text((W - 110, 138), handle, font=font("Oswald-Bold.ttf", 24, 400), fill=GREY, anchor="rm")
    return img


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, required=True)
    p.add_argument("--record", type=int)
    p.add_argument("--last", help='e.g. "2026-01-08 · xAI"')
    p.add_argument("--last-title", help="one-line description of the last incident")
    p.add_argument("--somber", action="store_true")
    p.add_argument("--censor", choices=CENSOR_MODES, default="stars")
    p.add_argument("--handle")
    p.add_argument("-o", "--out", default="sign.png")
    a = p.parse_args()
    render(a.days, record=a.record, last=a.last, last_title=a.last_title, somber=a.somber,
           censor=a.censor, handle=a.handle).save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
