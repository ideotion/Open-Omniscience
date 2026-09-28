"""The theme cull (Q1123 = b, 0.5 gate row I, brief S05-09 S3; invariant #12 amended 2026-09-15).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ruling: cull the near-duplicate themes to a floor of 10 named themes, name each culled
theme with its nearest survivor, and map a stored pick of a culled theme to that survivor,
never silently to the default. What a "near-duplicate" is was MEASURED, not chosen by name:
the mean CIE76 colour difference over the six surface tokens (bg, bg2, panel, panel2, panel3,
border), sRGB -> CIELAB (D65). Three pairs sat under 2 (light/mist 1.25, ink/arctic 1.81,
ink/slate 1.92; slate/arctic 1.76) and the next closest pair is paper/dawn at 3.87 -- a gap,
and 2.3 is the usual just-noticeable difference for ΔE76. The audit's other suspects
(midnight, aubergine, garnet, forest) measure 7.5 to 9.7 from their neighbours, so they stay.

The retired palettes are kept below as the record of what was measured; the test re-derives
each one's nearest survivor from the live stylesheet, so a survivor that later drifts is seen.
"""

from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
SURFACE = ("bg", "bg2", "panel", "panel2", "panel3", "border")
JND = 2.3  # the just-noticeable ΔE76

# The three culled palettes as they stood in app.css before the cull (main @ 00af1d9).
RETIRED = {
    "slate": {"bg": "#0e1116", "bg2": "#11151c", "panel": "#161b23", "panel2": "#1e2531",
              "panel3": "#28323f", "border": "#28303d"},
    "arctic": {"bg": "#0f1216", "bg2": "#12161b", "panel": "#171c22", "panel2": "#1e242c",
               "panel3": "#262e38", "border": "#262e3a"},
    "mist": {"bg": "#eceff2", "bg2": "#e4e8ee", "panel": "#f9fafc", "panel2": "#eff2f6",
             "panel3": "#e3e8ef", "border": "#d8dee7"},
}
SURVIVOR = {"slate": "ink", "arctic": "ink", "mist": "light"}


def _css() -> str:
    return (STATIC / "app.css").read_text(encoding="utf-8")


_TOKEN = re.compile(r"--(bg|bg2|panel|panel2|panel3|border):(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b")


def _tokens(body: str) -> dict[str, str]:
    return {k: (v if len(v) == 7 else "#" + "".join(c * 2 for c in v[1:])) for k, v in _TOKEN.findall(body)}


def _palettes() -> dict[str, dict[str, str]]:
    css = _css()
    root = css.split(":root {", 1)[1].split("}", 1)[0]
    ink = _tokens(root)
    out = {"ink": ink}
    for name, body in re.findall(r'html\[data-theme="(\w+)"\]\{([^}]*)\}', css):
        out[name] = {**ink, **_tokens(body)}
    assert set(SURFACE) <= set(ink), "the :root (Ink) surface tokens must parse"
    return out


def _lab(h: str) -> tuple[float, float, float]:
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return (116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z)))


def _dist(a: dict[str, str], b: dict[str, str]) -> float:
    return sum(math.dist(_lab(a[k]), _lab(b[k])) for k in SURFACE) / len(SURFACE)


def test_the_culled_themes_are_gone_and_the_floor_holds():
    pal = _palettes()
    for gone in RETIRED:
        assert gone not in pal, f"{gone} was culled (Q1123 = b) and must not come back as a CSS block"
    shell = (STATIC / "app-shell.js").read_text(encoding="utf-8")
    themes = shell.split("const THEMES = [", 1)[1].split("];", 1)[0]
    ids = re.findall(r'id:"(\w+)"', themes)
    for gone in RETIRED:
        assert gone not in ids, f"{gone} must not be offered in the Graphics picker"
    named = [i for i in ids if i != "system"]
    assert len(named) >= 10, "Q1123 = b: the catalogue's floor is 10 named themes"
    assert set(named) == set(pal), "every offered theme has a palette and every palette is offered"


def test_no_two_survivors_are_near_duplicates():
    pal = _palettes()
    close = [(a, b, round(_dist(pal[a], pal[b]), 2))
             for a, b in itertools.combinations(sorted(pal), 2) if _dist(pal[a], pal[b]) < JND]
    assert not close, f"surviving themes under the ΔE76 {JND} bar are near-duplicates: {close}"


def test_each_culled_theme_is_named_with_its_nearest_survivor():
    pal = _palettes()
    for gone, old in RETIRED.items():
        nearest = min(pal, key=lambda t: _dist(old, pal[t]))
        assert nearest == SURVIVOR[gone], f"{gone}'s nearest survivor measures as {nearest}"
        assert _dist(old, pal[nearest]) < JND, f"{gone} was culled as a near-duplicate of {nearest}"


def test_a_stored_culled_pick_maps_to_its_survivor_everywhere_the_look_is_read():
    shell = (STATIC / "app-shell.js").read_text(encoding="utf-8")
    block = shell.split("const RETIRED_THEMES = {", 1)[1].split("};", 1)[0]
    shell_map = dict(re.findall(r'(\w+):\s*\{theme:"(\w+)"', block))
    assert shell_map == SURVIVOR
    # the retired theme's own accent rides along, never over one the operator chose
    assert 'slate:  {theme:"ink",   accent:"#7aa2f7"}' in block
    assert 'arctic: {theme:"ink",   accent:"#88c0d0", face:"inter"}' in block
    getui = shell.split("function getUi()", 1)[1].split("function announceRetiredTheme", 1)[0]
    assert "if (!ui.accent && r.accent)" in getui and "if (!ui.face && r.face)" in getui
    assert "saveUi(ui)" in getui, "the mapping is persisted, so it happens once"
    # ... and said out loud once, after the locale is ready
    boot = (STATIC / "app-boot.js").read_text(encoding="utf-8")
    assert "announceRetiredTheme" in boot
    for page in ("taskmanager.html", "investigate.html"):
        text = (STATIC / page).read_text(encoding="utf-8")
        m = re.search(r"RETIRED_THEMES = \{([^}]*)\}", text)
        assert m, f"{page} reads oo.ui itself and must map a culled pick too"
        assert dict(re.findall(r'(\w+):\s*"(\w+)"', m.group(1))) == SURVIVOR, page


def test_the_retirement_notice_ships_in_every_locale():
    import json

    key = ("The {old} theme was retired as a near-duplicate of {new}, "
           "so you are now on {new} with its accent kept.")
    shell = (STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert key in shell
    for loc in sorted((STATIC / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        assert d.get(key), f"{loc.name}: the retirement notice is missing"
        assert "{old}" in d[key] and "{new}" in d[key], f"{loc.name}: placeholders lost"
