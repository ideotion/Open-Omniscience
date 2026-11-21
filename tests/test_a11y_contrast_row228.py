"""Row 228: the a11y sweep's colour findings C1, C2 and C3 (docs/audit/a11y-sweep-2026-11-20, 2026-11-20).

- C1: the task manager dimmed text with ``opacity``, which fell below 4.5:1 in light, dawn, mint, paper and solar
  (44 nodes). Its dimmed text is now a real colour, and those colours clear 4.5:1 on ``--bg`` and ``--panel`` in
  every theme.
- C2: the agenda's "today" day number (11 px bold, so 4.5:1 applies) was ``--accent``, short in solar, dawn and
  paper. It is now ``--accent-text``, the text-safe accent.
- C3: dawn's card-back "open corpus" action measured 4.49:1 on its family tint. The tint is lighter, and the
  check below runs over every theme and every family hue (``famHue`` is ``hsl(h 60% 55%)``), not only the one
  pair the sweep saw.

The ratios are computed from app.css by the resolver the theme-contrast test already trusts.
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from tests.test_theme_contrast_and_donut_guard import _ratio, _theme_tokens

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "src/static/app.css").read_text(encoding="utf-8")
TM = (ROOT / "src/static/taskmanager.html").read_text(encoding="utf-8")
AA = 4.5


def _tm_style() -> str:
    style = TM.split("<style", 1)[1].split("</style>", 1)[0]
    return re.sub(r"/\*.*?\*/", "", style, flags=re.S)


def test_the_task_manager_dims_no_text_with_opacity():
    """C1: opacity composites against whatever is behind it, so a theme can drop it below AA; a colour cannot."""
    assert "opacity" not in _tm_style(), "the task manager dims with opacity again: use var(--muted) instead"


def test_the_task_managers_dimmed_colours_clear_aa_in_every_theme():
    used = set(re.findall(r"color:\s*var\(--([a-z-]+)", _tm_style()))
    assert {"muted", "fg-soft"} <= used
    failures = []
    for name, tok in sorted(_theme_tokens().items()):
        for var in ("muted", "fg-soft"):
            for bg in ("bg", "panel"):
                r = _ratio(tok[var], tok[bg])
                if r < AA:
                    failures.append(f"{name} --{var} on --{bg} {r:.2f}")
    assert not failures, failures


def test_todays_day_number_uses_the_text_safe_accent_and_clears_aa():
    """C2."""
    rule = re.search(r"\.ag-cell\.today \.ag-dn \{([^}]*)\}", CSS)
    assert rule and "var(--accent-text)" in rule.group(1), "today's number must use --accent-text"
    failures = []
    for name, tok in sorted(_theme_tokens().items()):
        colour = tok.get("accent-text") or tok["accent"]  # :root sets --accent-text: var(--accent)
        for bg in ("bg", "panel"):
            r = _ratio(colour, tok[bg])
            if r < AA:
                failures.append(f"{name} on --{bg} {r:.2f}")
    assert not failures, failures


def _hex(c: str) -> tuple[int, ...]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a: str, share: float, b: str) -> str:
    A, B = _hex(a), _hex(b)
    return "#" + "".join(f"{round(A[i] * share + B[i] * (1 - share)):02x}" for i in range(3))


def _fam(h: int) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360, 0.55, 0.60)
    return "#" + "".join(f"{round(x * 255):02x}" for x in (r, g, b))


def _panel2() -> dict[str, str]:
    out = {":root": re.search(r":root\s*\{[^}]*?--panel2:(#[0-9a-fA-F]{6})", CSS).group(1)}
    for m in re.finditer(r'html\[data-theme="(\w+)"\]\{([^}]*)\}', CSS):
        p2 = re.search(r"--panel2:(#[0-9a-fA-F]{6})", m.group(2))
        if p2:
            out[m.group(1)] = p2.group(1)
    return out


def test_the_card_back_action_clears_aa_on_every_family_tint_in_every_theme():
    """C3, for the resting and the hover tint, every theme and all 360 family hues."""
    rest = re.search(r"\.lead-open \{ background:color-mix\(in srgb, var\(--fam,var\(--accent\)\) (\d+)%", CSS)
    hover = re.search(r"\.lead-open:hover \{ background:color-mix\(in srgb, var\(--fam,var\(--accent\)\) (\d+)%", CSS)
    assert rest and hover
    assert re.search(r"\.lead-open \{[^}]*color:var\(--fg\)", CSS), "the action's text is --fg"
    tokens, p2 = _theme_tokens(), _panel2()
    assert set(tokens) <= set(p2), f"no --panel2 read for {sorted(set(tokens) - set(p2))}"
    failures = []
    for pct in (int(rest.group(1)), int(hover.group(1))):
        for name, tok in sorted(tokens.items()):
            worst = min((_ratio(tok["fg"], _mix(_fam(h), pct / 100, p2[name])), h) for h in range(360))
            if worst[0] < AA:
                failures.append(f"{name} at {pct}%: {worst[0]:.2f} (hue {worst[1]})")
    assert not failures, failures
