"""WCAG contrast of every colour ROLE against each theme's panel, all 17 themes.

CORRECTED 2026-07-28: the first version measured `--warn` against the AA
4.5:1 TEXT bar. `--warn` is not a text colour -- it appears only as a
`.dot.warn` background and as border colours; TEXT uses the dedicated
`--warn-fg`. Applying a text bar to a non-text mark manufactures failures
AND hides real ones next door: `--muted`, which IS text, was below AA on
two themes and went unmeasured entirely. Each role now carries its own
correct bar (WCAG 1.4.3 for text, 1.4.11 for non-text UI components).

Themes that do not redefine a variable INHERIT :root's value -- modelling
that explicitly matters, since ignoring it under-reports failures.

Stdlib only, read-only, no arguments. Run from the repo root.
"""

import pathlib
import re

# (variable, minimum ratio, what it is)
ROLES = (
    ("fg", 4.5, "primary text"),
    ("muted", 4.5, "secondary text"),
    ("caveat", 4.5, "honesty caveats"),
    ("warn-fg", 4.5, "warning text"),
    ("warn", 3.0, "warning mark (dot/border) - non-text"),
    ("accent", 3.0, "accent mark - non-text"),
)


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def theme_tokens() -> dict:
    css = pathlib.Path("src/static/app.css").read_text(encoding="utf-8")
    blocks: dict = {}
    for m in re.finditer(r'(?::root|html\[data-theme="([a-z-]+)"\])\s*\{([^}]*)\}', css):
        name = m.group(1) or ":root"
        found = dict(re.findall(r"--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{3,8})", m.group(2)))
        if found:
            blocks.setdefault(name, {}).update(found)
    root = blocks.get(":root", {})
    return {name: {**root, **tok} for name, tok in blocks.items()}


def main() -> None:
    themes = theme_tokens()
    print(f"{len(themes)} themes parsed (with :root inheritance applied)\n")
    total_fail = 0
    for var, bar, what in ROLES:
        failures = []
        checked = 0
        for name, tok in sorted(themes.items()):
            colour, panel = tok.get(var), tok.get("panel")
            if not (colour and panel):
                continue
            checked += 1
            r = ratio(colour, panel)
            if r < bar:
                failures.append((name, round(r, 2)))
        total_fail += len(failures)
        status = "OK" if not failures else f"{len(failures)} FAIL"
        print(f"--{var:<9} bar {bar}:1  ({what})")
        print(f"    checked {checked} themes -> {status}")
        for name, r in sorted(failures, key=lambda x: x[1]):
            print(f"      {name}: {r}")
    print(f"\ntotal failures across all roles: {total_fail}")


if __name__ == "__main__":
    main()
