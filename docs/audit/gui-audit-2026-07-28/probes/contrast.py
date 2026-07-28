"""WCAG contrast of --warn against each theme's panel, across all 17 themes.

Mirrors the method used for the shipped invariant-#23 --caveat fix: relative
luminance -> contrast ratio, computed from the CSS variables themselves.
Themes that do not redefine a variable INHERIT :root's value -- getting that
inheritance wrong under-reports the failures, so it is modelled explicitly.

Stdlib only, read-only, no arguments. Run from the repo root.
"""
import re
import pathlib


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> None:
    css = pathlib.Path("src/static/app.css").read_text(encoding="utf-8")
    blocks: dict[str, dict[str, str]] = {}
    for m in re.finditer(r'(?::root|\[data-theme="([a-z-]+)"\])\s*\{([^}]*)\}', css):
        name = m.group(1) or "__root__"
        found = dict(re.findall(r"--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{3,8})", m.group(2)))
        if found:
            blocks.setdefault(name, {}).update(found)

    root = blocks.pop("__root__", {})
    rows = [(":root (default)", root.get("warn"), root.get("panel"))]
    for name, v in sorted(blocks.items()):
        rows.append((name, v.get("warn") or root.get("warn"),
                     v.get("panel") or root.get("panel")))

    print(f"{'theme':<20}{'--warn':<9}{'--panel':<9}{'ratio':>7}  AA(4.5:1)")
    fails = []
    for name, warn, panel in rows:
        if not (warn and panel):
            print(f"{name:<20}{'?':<9}{'?':<9}{'--':>7}  undetermined")
            continue
        r = ratio(warn, panel)
        if r < 4.5:
            fails.append((name, round(r, 2)))
        print(f"{name:<20}{warn:<9}{panel:<9}{r:7.2f}  {'PASS' if r >= 4.5 else 'FAIL'}")

    print(f"\n--warn fails WCAG AA on {len(fails)} of {len(rows)} themes")
    if fails:
        for name, r in sorted(fails, key=lambda x: x[1]):
            print(f"  {name}: {r}")


if __name__ == "__main__":
    main()
