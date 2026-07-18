"""Field report 2026-07-17: clicking through the first-launch legal screen (a
browser-driven WebDriver-BiDi session against a real, freshly-built store) showed
stray literal "**" characters and wrongly-bolded phrases in the rendered legal
documents -- e.g. the MENTIONS_LEGALES.md translation banner rendered as
"**Machine-drafted translation ... authoritative text.**" verbatim instead of
bold, and CGU.md's clause 9.3 rendered "liability in the event of **wilful
misconduct (dol)** or **gross" (stray asterisks) instead of two clean bold spans.

Root cause: renderLegalMarkdown() (src/static/unlock.html) ran its inline
**bold**/`code`/[link]() parser on each RAW PHYSICAL source line independently.
The legal docs are hand-wrapped at ~80 columns, so a **bold** span or a list
item routinely continues onto the next physical line with no blank line
between (normal markdown soft-wrap) -- splitting it mid-span left an unmatched
"**" on each line, which then paired wrongly with an unrelated "**" later in
the paragraph.

This test EXTRACTS the real function from unlock.html and runs it through
node, so a regression in the shipped source is caught -- not a
hand-reimplementation that could silently drift from the real code (the
established pattern in tests/test_agenda_month_shift.py / test_ooviz.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_UNLOCK_HTML = _ROOT / "src" / "static" / "unlock.html"


def _extract(src: str, signature: str) -> str:
    start = src.index(signature)
    # Every function this test needs closes at a "\n    }\n" at the top level
    # of the <script> (4-space indented body, matching the file's own style).
    end = src.index("\n    }\n", start) + len("\n    }\n")
    return src[start:end]


def _extract_renderer() -> str:
    html = _UNLOCK_HTML.read_text(encoding="utf-8")
    return _extract(html, "function escHtml(s) {") + "\n" + _extract(html, "function renderLegalMarkdown(md) {")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_renderLegalMarkdown_source_exists_and_is_extractable():
    fn = _extract_renderer()
    assert "function renderLegalMarkdown(md)" in fn
    assert "quoteBuf" in fn  # the fixed implementation, not the old per-line one


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bold_span_wrapped_across_a_blockquote_line_break_renders_clean(tmp_path):
    """The exact MENTIONS_LEGALES.md banner shape: a **bold** span spanning 3
    wrapped blockquote lines must become ONE clean <b> with no literal "**"."""
    fn = _extract_renderer()
    md = (
        "> **Machine-drafted translation — pending native review. The French version\n"
        "> ([`../MENTIONS_LEGALES.md`](../MENTIONS_LEGALES.md)) is the legally authoritative\n"
        "> text.**"
    )
    harness = f"""
{fn}
console.log(renderLegalMarkdown({json.dumps(md)}));
"""
    script = tmp_path / "render_test.js"
    script.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    out = r.stdout.strip()
    assert "**" not in out, f"stray literal ** survived: {out}"
    assert "<b>Machine-drafted translation" in out
    assert out.count("<blockquote>") == 1 and out.count("</blockquote>") == 1
    # exactly one bold span covering the whole banner (no premature split)
    assert out.count("<b>") == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bold_span_wrapped_across_a_list_item_line_break_renders_clean(tmp_path):
    """The exact CGU.md clause 9.3 shape: two **bold** phrases in one list item,
    the second one split across the wrap -- both must render as clean bold,
    with the following sibling item unaffected."""
    fn = _extract_renderer()
    md = (
        "- liability in the event of **wilful misconduct (dol)** or **gross negligence (faute\n"
        "  lourde)**;\n"
        "- liability in the event of **personal injury**;"
    )
    harness = f"""
{fn}
console.log(renderLegalMarkdown({json.dumps(md)}));
"""
    script = tmp_path / "render_test2.js"
    script.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    out = r.stdout.strip()
    assert "**" not in out, f"stray literal ** survived: {out}"
    assert "<b>wilful misconduct (dol)</b>" in out
    assert "<b>gross negligence (faute lourde)</b>" in out
    assert "<b>personal injury</b>" in out
    assert out.count("<li>") == 2 and out.count("</li>") == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_blank_quote_line_starts_a_new_paragraph_within_the_same_blockquote(tmp_path):
    """A bare '>' line inside a blockquote is a paragraph break WITHIN the quote
    (docs/legal/MENTIONS_LEGALES.md has this), not a quote-then-quote merge, and
    not two separate <blockquote> elements."""
    fn = _extract_renderer()
    md = "> **First paragraph of the\n> quote.**\n>\n> Second paragraph, plain."
    harness = f"""
{fn}
console.log(renderLegalMarkdown({json.dumps(md)}));
"""
    script = tmp_path / "render_test3.js"
    script.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    out = r.stdout.strip()
    assert out.count("<blockquote>") == 1 and out.count("</blockquote>") == 1
    assert out.count("<div>") == 2  # two paragraphs within the one blockquote
    assert "<b>First paragraph of the quote.</b>" in out
    assert "<div>Second paragraph, plain.</div>" in out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_headings_and_single_line_bold_are_unaffected_by_the_fix(tmp_path):
    """Regression guard: ordinary single-line constructs (heading, one-line
    bold paragraph, hr) must render exactly as before."""
    fn = _extract_renderer()
    md = "## Article 4\n\nThe **Software** is provided as-is.\n\n---\n"
    harness = f"""
{fn}
console.log(renderLegalMarkdown({json.dumps(md)}));
"""
    script = tmp_path / "render_test4.js"
    script.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    out = r.stdout.strip()
    assert "<h2>Article 4</h2>" in out
    assert "<p>The <b>Software</b> is provided as-is.</p>" in out
    assert "<hr>" in out
