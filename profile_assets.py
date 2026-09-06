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


def header(censor: str, credit: str = "@Actuallykeltan", ratio: float = 3.0) -> Image.Image:
    """The banner, laid out proportionally so it can be cut to a platform's shape.

    X wants 3:1. Bluesky publishes 3:1 as its spec but renders the banner into a
    4:1 box with object-fit: cover, measured on the live profile at a fixed
    600x150 that does not change with viewport width. Feeding it a 3:1 image
    therefore loses the top and bottom sixth - which took both hazard stripes
    and half the handle with it. Rendering the shape the platform actually uses
    is the fix; nothing is cropped, so nothing has to be guessed at.
    """
    W = 3000  # 2x
    H = round(W / ratio)
    # Type scales with the canvas, not just the spacing. Scaling the positions
    # alone drove the two title lines into each other at 4:1. `k` is 1.0 at the
    # 3:1 reference, so the X banner is reproduced exactly.
    k = H / 1000
    px = lambda v: max(1, round(v * k))
    img = Image.new("RGB", (W, H), rs.CREAM)
    stripes(img, 0, px(70), period=90)
    stripes(img, H - px(70), H, period=90)
    d = ImageDraw.Draw(img)
    noun = rs.noun_forms(censor)[0]
    f = rs.font("Anton-Regular.ttf", px(190))
    rs.draw_censored(d, W / 2, 0.38 * H, "DAYS SINCE THE LAST", f, rs.BLACK, anchor="m")
    rs.draw_censored(d, W / 2, 0.60 * H, f"MAJOR AI COMPANY {noun}", f, rs.BLACK, anchor="m")
    # keltan's call: a byline, not a tagline. The bio already explains the
    # account, and X crops the header hard on mobile.
    d.text((W / 2, 0.79 * H), "made by keltan", font=rs.font("Anton-Regular.ttf", px(62)), fill=rs.GREY, anchor="mm")
    # The byline points at keltan's personal account on whichever platform the
    # banner is going on. An X header advertising a Bluesky handle sends people
    # somewhere they cannot follow him from.
    d.text((W / 2, 0.868 * H), credit, font=rs.font("Oswald-Bold.ttf", px(40), 500), fill=rs.GREY, anchor="mm")
    return img.resize((W // 2, H // 2), Image.LANCZOS)


# Byline and shape per platform: the handle has to be one the reader can use,
# and the aspect has to be the one that platform actually renders.
HEADERS = {"header.png": ("@Actuallykeltan", 3.0),
           "header-bsky.png": ("@keltan.net", 4.0)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--censor", choices=rs.CENSOR_MODES, default="bar")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    avatar(a.censor).save(out / "avatar.png")
    print(out / "avatar.png")
    for name, (credit, ratio) in HEADERS.items():
        im = header(a.censor, credit, ratio)
        im.save(out / name)
        print(out / name, credit, f"{im.width}x{im.height}")
