#!/usr/bin/env python3
"""
Render assets/icon.png from the same motif as assets/icon.svg.

Why this exists: the .desktop launcher points at an icon, and while SVG is the
source of truth, many Linux file managers and minimal desktops (including some
Qubes AppVM setups) render PNG far more reliably than SVG. So we ship a PNG
fallback. This generator is committed (not just its output) so the raster is
reproducible and inspectable -- in keeping with the project's "read it before you
trust it" stance -- and it depends only on Pillow, which is already a core dep.

Run:  python scripts/make_icon_png.py   (writes assets/icon.png, 256x256)

The drawing mirrors icon.svg: a rounded-square night-blue background, a wireframe
globe (radial-shaded disc + graticule) clipped to an almond eye, a dark pupil with
a catch-light, and a bright eye outline on top.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.png"

SIZE = 256
SS = 4                      # supersample factor for crisp antialiasing
N = SIZE * SS


def s(v: float) -> float:
    """Scale a 256-space coordinate into supersampled space."""
    return v * SS


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rgb(c0: tuple[int, int, int], c1: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(lerp(c0[i], c1[i], t)) for i in range(3))  # type: ignore[return-value]


def grad_color(stops: list[tuple[float, tuple[int, int, int]]], t: float) -> tuple[int, int, int]:
    """Multi-stop colour lookup, clamped at both ends."""
    t = max(0.0, min(1.0, t))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            return lerp_rgb(c0, c1, (t - t0) / (t1 - t0))
    return stops[-1][1]


def quad(p0, p1, p2, steps: int = 140):
    """Sample a quadratic Bezier into a polyline (Pillow has no native beziers)."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        pts.append((s(x), s(y)))
    return pts


# Almond eye outline (two quadratic arcs), in supersampled coords.
EYE = quad((24, 128), (128, 40), (232, 128)) + quad((232, 128), (128, 216), (24, 128))


def vertical_gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (N, N))
    d = ImageDraw.Draw(img)
    for y in range(N):
        d.line([(0, y), (N, y)], fill=lerp_rgb(top, bottom, y / (N - 1)))
    return img


def main() -> None:
    # Black & white by design (mirrors assets/icon.svg): a near-black rounded
    # square, a white wireframe globe clipped to an almond eye, a white pupil with
    # a dark catch-light, and a white eye outline on top.

    # --- background: rounded near-black square ---------------------------- #
    base = vertical_gradient((0x12, 0x12, 0x12), (0x00, 0x00, 0x00)).convert("RGBA")

    # --- globe disc: a faint white sphere for depth ----------------------- #
    globe = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    gd = ImageDraw.Draw(globe)
    gd.ellipse(
        [s(128 - 92), s(128 - 92), s(128 + 92), s(128 + 92)], fill=(0xFF, 0xFF, 0xFF, 16)
    )

    group = Image.alpha_composite(Image.new("RGBA", (N, N), (0, 0, 0, 0)), globe)

    # --- graticule (latitudes, meridians) in white ----------------------- #
    grat = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    gr = ImageDraw.Draw(grat)
    line_col = (0xFF, 0xFF, 0xFF, 255)
    w = max(1, round(s(3.5)))
    gr.line(quad((36, 88), (128, 76), (220, 88)), fill=line_col, width=w, joint="curve")
    gr.line(quad((36, 108), (128, 100), (220, 108)), fill=line_col, width=w, joint="curve")
    gr.line([(s(30), s(128)), (s(226), s(128))], fill=line_col, width=w)
    gr.line(quad((36, 148), (128, 156), (220, 148)), fill=line_col, width=w, joint="curve")
    gr.line(quad((36, 168), (128, 180), (220, 168)), fill=line_col, width=w, joint="curve")
    gr.line([(s(128), s(28)), (s(128), s(228))], fill=line_col, width=w)
    for rx, ry in ((34, 100), (66, 100)):
        gr.ellipse([s(128 - rx), s(128 - ry), s(128 + rx), s(128 + ry)], outline=line_col, width=w)
    grat.putalpha(grat.getchannel("A").point(lambda a: int(a * 0.92)))
    group = Image.alpha_composite(group, grat)

    # --- pupil (white) + dark catch-light -------------------------------- #
    pd = ImageDraw.Draw(group)
    pd.ellipse([s(128 - 20), s(128 - 20), s(128 + 20), s(128 + 20)], fill=(0xFF, 0xFF, 0xFF, 255))
    pd.ellipse([s(120 - 6.5), s(120 - 6.5), s(120 + 6.5), s(120 + 6.5)],
               fill=(0x00, 0x00, 0x00, 215))

    # --- clip the whole globe group to the almond eye --------------------- #
    eye_mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(eye_mask).polygon(EYE, fill=255)
    group.putalpha(ImageChops.multiply(group.getchannel("A"), eye_mask))
    base = Image.alpha_composite(base, group)

    # --- bright eye outline on top ---------------------------------------- #
    ImageDraw.Draw(base).line(
        EYE + [EYE[0]], fill=(0xFF, 0xFF, 0xFF, 255), width=round(s(9)), joint="curve"
    )

    # --- rounded-square alpha mask (rx=48) -------------------------------- #
    corner = Image.new("L", (N, N), 0)
    ImageDraw.Draw(corner).rounded_rectangle([0, 0, N - 1, N - 1], radius=s(48), fill=255)
    base.putalpha(corner)

    base.resize((SIZE, SIZE), Image.LANCZOS).save(OUT)
    print(f"wrote {OUT} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
