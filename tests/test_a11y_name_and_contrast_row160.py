"""Row 160: the axe serious findings of the 2026-11-18 encrypted rehearsal, pinned at the source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

* label-content-name-mismatch: the language button showed "EN" and was named "Change language", and a Lead
  card's front showed type, title, summary and signal but was named by its title alone. A speech user says
  what they see, so the name must contain the visible text. The button keeps its visible text and adds the
  phrase in a visually hidden span; the card front drops its aria-label and is named by its content.
* link-in-text-block: evidence links on a Lead's back were set apart by colour only; they are underlined.
* color-contrast: the task manager's own pill styles drew white on the raw --warn (2.24:1); the standalone
  reader's light palette kept the dark palette's light amber --warn for the deduced heading.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _lang_button(html: str) -> str:
    start = html.index('id="lang-switch"')
    return html[html.rindex("<button", 0, start) : html.index("</button>", start)]


def test_language_button_name_contains_its_visible_code():
    for name, hidden in (("index.html", '<span class="sr-only">Change language</span>'),
                         ("taskmanager.html", '<span class="sr-only" data-i18n>Change language</span>')):
        btn = _lang_button((_STATIC / name).read_text(encoding="utf-8"))
        assert "aria-label=" not in btn, f"{name}: an aria-label without the visible code is the mismatch"
        assert 'id="lang-code"' in btn and hidden in btn, f"{name}: name = visible code + hidden phrase"
        assert 'id="lang-flag" aria-hidden="true"' in btn, f"{name}: the flag stays out of the name"


def test_lead_card_front_is_named_by_its_own_text():
    js = (_STATIC / "app-home.js").read_text(encoding="utf-8")
    front = js[js.index('class="card-face card-front"') :]
    front = front[: front.index(">")]
    assert "aria-label" not in front and 'role="button"' in front, front


def test_evidence_links_are_underlined_at_rest():
    css = (_STATIC / "app.css").read_text(encoding="utf-8")
    rule = re.search(r"\.card \.evid a \{([^}]*)\}", css)
    assert rule and "text-decoration:underline" in rule.group(1).replace(" ", ""), rule


def test_task_manager_pills_never_paint_white_on_a_state_fill():
    html = (_STATIC / "taskmanager.html").read_text(encoding="utf-8")
    for state, var in (("ok", "--ok-text"), ("warn", "--warn-fg"), ("err", "--err-text")):
        rules = re.findall(r"\.pill\." + state + r" \{([^}]*)\}", html)
        assert rules, state
        joined = " ".join(rules)
        assert "#fff" not in joined and f"var({var}" in joined, (state, joined)


def _lum(hex_: str) -> float:
    rgb = [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_reader_warn_text_clears_aa_in_both_palettes():
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    dark_root = src[src.index(":root {{ color-scheme: light dark;") :]
    dark_root = dark_root[: dark_root.index("}}")]
    light_root = src[src.index("@media (prefers-color-scheme: light) {{ :root {{") :]
    light_root = light_root[: light_root.index("}}")]

    def var(block: str, name: str) -> str:
        m = re.search(name + r":#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", block)
        assert m, (name, block)
        h = m.group(1)
        return "#" + (h if len(h) == 6 else "".join(c * 2 for c in h))

    for block, fallback in ((dark_root, dark_root), (light_root, dark_root)):
        warn = var(block, "--warn")
        for bg in ("--paper", "--card"):
            colour = var(block, bg) if re.search(bg + ":#", block) else var(fallback, bg)
            assert _ratio(warn, colour) >= 4.5, (warn, bg, colour, _ratio(warn, colour))
