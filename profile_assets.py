#!/usr/bin/env python3
"""Profile assets in the sign style: avatar (400x400) and header (1500x500).

    python profile_assets.py --censor bar --out out/
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

import render_sign as rs


def stripes(img, y0, y1, period=48):
    band = Image.new("RGB", (img.width, y1 - y0), rs.YELLOW)
    d = ImageDraw.Draw(band)
    h = y1 - y0
    for x in range(-h, img.width + period, period):
        d.polygon([(x, 0), (x + period // 2, 0), (x + period // 2 - h, h), (x - h, h)], fill=rs.BLACK)
    img.paste(band, (0, y0))


def avatar(censor: str) -> Image.Image:
    S = 800  # render 2x, X downsizes
    img = Image.new("RGB", (S, S), rs.CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, S - 1, S - 1], outline=rs.BLACK, width=22)
    stripes(img, 30, 70)
    stripes(img, S - 70, S - 30)
    d = ImageDraw.Draw(img)
    # number box
    f = rs.font("Anton-Regular.ttf", 360)
    num = "0"
    nb = f.getbbox(num)
    nw, nh = d.textlength(num, font=f), nb[3] - nb[1]
    bw, bh = 320, 390
    bx, by = (S - bw) // 2, 120
    d.rectangle([bx, by, bx + bw, by + bh], outline=rs.RED, width=14, fill=(255, 255, 255))
    d.text(((S - nw) / 2, by + (bh - nh) / 2 - nb[1]), num, font=f, fill=rs.RED)
    fl = rs.font("Oswald-Bold.ttf", 54, 600)
    rs.draw_censored(d, S / 2, 585, "DAYS SINCE THE LAST", fl, rs.BLACK, anchor="m")
    noun = rs.noun_forms(censor)[0]
    rs.draw_censored(d, S / 2, 645, f"MAJOR AI COMPANY {noun}", fl, rs.BLACK, anchor="m")
    return img.resize((400, 400), Image.LANCZOS)


def header(censor: str) -> Image.Image:
    W, H = 3000, 1000  # 2x
    img = Image.new("RGB", (W, H), rs.CREAM)
    d = ImageDraw.Draw(img)
    stripes(img, 0, 70, period=90)
    stripes(img, H - 70, H, period=90)
    d = ImageDraw.Draw(img)
    noun = rs.noun_forms(censor)[0]
    f = rs.font("Anton-Regular.ttf", 190)
    rs.draw_censored(d, W / 2, 380, "DAYS SINCE THE LAST", f, rs.BLACK, anchor="m")
    rs.draw_censored(d, W / 2, 600, f"MAJOR AI COMPANY {noun}", f, rs.BLACK, anchor="m")
    fs = rs.font("Oswald-Bold.ttf", 56, 500)
    d.text((W / 2, 820), "ONE NUMBER, ONCE A DAY. RESETS WHEN A FRONTIER COMPANY HAS TO APOLOGISE.", font=fs, fill=rs.GREY, anchor="mm")
    return img.resize((1500, 500), Image.LANCZOS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--censor", choices=rs.CENSOR_MODES, default="bar")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    avatar(a.censor).save(out / "avatar.png")
    header(a.censor).save(out / "header.png")
    print(out / "avatar.png", out / "header.png")
