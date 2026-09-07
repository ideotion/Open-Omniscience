"""Every dialog wears the theme, and no rule may name a token nobody defines.

Both halves of this file come from ONE browser session (2026-09-07, PRH-32) and
neither was visible to a source read:

  * Nine of the eleven ``<dialog>`` elements carried ``background``/``color`` in an
    inline ``style=`` attribute and TWO did not (``#ux-import``, ``#ux-export``).
    Those two alone fell back to the UA's ``Canvas``/``CanvasText``, so they rendered
    IDENTICALLY on all 17 themes -- measured ground ``rgb(18,18,18)`` on the twelve
    dark themes and ``rgb(255,255,255)`` on the five light ones, never the theme's own
    ``--panel``.  The palette reached nine dialogs and stopped at two, because the
    property lived at the call site instead of at a chokepoint.

  * All eleven declared ``border:1px solid var(--line)`` and ``--line`` is defined
    NOWHERE in ``app.css``.  A ``var()`` that resolves to nothing makes the whole
    shorthand invalid at computed-value time, so ``getComputedStyle`` reported
    ``border-top-style: none`` / ``border-top-width: 0px`` on every one of them: nine
    dialogs declared a border that has never once rendered.  Measured, not inferred.

The repair is a single ``dialog { ... }`` rule, so a twelfth dialog is themed by
construction rather than by whoever adds it remembering to inline four declarations.
The census below is what makes that durable: it is the guard that would have caught
``--line`` the day it was written.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

from tests.js_source_helper import css_rule, read_static

HTML = read_static("index.html")
CSS = read_static("app.css")


def _strip_comments(css: str) -> str:
    """A source guard must read comment-stripped CSS: the comment recording a fix
    necessarily quotes the declarations the fix is about, and satisfies -- or trips --
    every needle written for them (the recorded trap, in both directions)."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _dialog_open_tags() -> list[tuple[str, str]]:
    """``(id, style-attribute)`` for every ``<dialog>`` in the shell."""
    out = []
    for m in re.finditer(r"<dialog\b([^>]*)>", HTML):
        attrs = m.group(1)
        did = re.search(r'id="([^"]+)"', attrs)
        style = re.search(r'style="([^"]*)"', attrs)
        out.append((did.group(1) if did else "", style.group(1) if style else ""))
    return out


# --------------------------------------------------------------------------- #
#  the chokepoint
# --------------------------------------------------------------------------- #
def test_one_rule_themes_every_dialog():
    """The base rule exists and names the theme tokens, so a dialog added tomorrow is
    on-palette without its author doing anything."""
    rule = css_rule(CSS, "dialog")
    flat = rule.replace(" ", "")
    assert "background:var(--panel)" in flat, "a dialog must sit on the theme's panel colour"
    assert "color:var(--fg)" in flat, "a dialog's text must be the theme's foreground"
    assert "border:1pxsolidvar(--border)" in flat, "and carry the theme's border"


def test_no_dialog_re_inlines_the_theme_at_its_own_call_site():
    """The half that actually regressed.  An inline ``style=`` beats every stylesheet
    rule, so one dialog re-declaring ``background``/``color``/``border`` is one dialog
    the chokepoint no longer governs -- which is exactly how two of eleven came to be
    off-palette while nine were fine.

    Sizing and padding stay inline: those are genuinely per-dialog, and forbidding them
    would be a fabricated rule.
    """
    tags = _dialog_open_tags()
    assert len(tags) >= 11, f"expected the shell's dialogs to be found, got {len(tags)}"
    owned = {"background", "background-color", "color", "border", "border-radius"}
    for did, style in tags:
        declared = {d.split(":", 1)[0].strip().lower() for d in style.split(";") if ":" in d}
        clash = declared & owned
        assert not clash, (
            f"#{did or '(unnamed)'} re-declares {sorted(clash)} inline, so the `dialog` rule "
            "cannot reach it -- move it to the stylesheet or state why this dialog differs"
        )


def test_the_two_export_import_dialogs_are_reachable_by_the_rule():
    """Named, because they are the two PRH-32 records and the two that were broken.

    An assertion over the whole set passes the day someone re-inlines exactly these two
    and leaves the other nine clean, so the specific pair gets its own line.
    """
    by_id = dict(_dialog_open_tags())
    for did in ("ux-import", "ux-export"):
        assert did in by_id, f"#{did} is gone from the shell -- update this guard deliberately"
        assert "background" not in by_id[did] and "color" not in by_id[did], (
            f"#{did} is the dialog that rendered on the browser's Canvas on all 17 themes; "
            "it must inherit the theme from the stylesheet"
        )


# --------------------------------------------------------------------------- #
#  the census that would have caught --line
# --------------------------------------------------------------------------- #
def _defined_tokens(css: str) -> set[str]:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", css, re.I))


# A var() WITH a fallback is valid whether or not the token exists -- `var(--hover,
# rgba(255,255,255,.04))` is a deliberate default, not a defect, and `--lead-h` is set
# by JS at runtime.  Flagging those would be a fabricated failure, which is exactly as
# dishonest as a fabricated pass; the first cut of this census did flag all three and
# the correction is the reason the pattern is anchored on the closing paren.
_BARE_VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*\)", re.I)


def _referenced_tokens(text: str) -> set[str]:
    """Only FALLBACK-LESS references — the ones that void their whole declaration."""
    return set(_BARE_VAR.findall(text))


# The one token the SPA bundle references and nobody defines, with the count measured
# 2026-09-07.  It is an ALLOWLIST, not an exemption: a NEW undefined token fails
# immediately, and this one cannot grow.  It is not repaired here because the repair is
# a VISIBLE change -- 41 declarations that currently evaporate would start drawing a
# 1px border across the shell, the task manager and seven JS modules at once -- and that
# belongs in its own reviewed slice rather than riding along inside a type-scale PR.
# Recorded in docs/ledger/OPEN_QUEUE.md the same day.
_KNOWN_UNDEFINED = {"--line": 41}

_SPA_FILES = (
    "app.css", "index.html", "taskmanager.html", "unlock.html", "investigate.html",
    "app-agenda.js", "app-ai-tools.js", "app-analysis.js", "app-backup.js", "app-boot.js",
    "app-core.js", "app-corpus.js", "app-diagnostics.js", "app-gov-law.js", "app-home.js",
    "app-insights.js", "app-library.js", "app-map.js", "app-markets.js", "app-settings.js",
    "app-shell.js", "app-sources.js", "ooviz.js", "i18n.js",
)


def test_every_custom_property_the_spa_uses_is_defined_somewhere():
    """``var(--line)`` is referenced 41 times FALLBACK-LESSLY across ten files of the SPA
    bundle (12 further references in ``taskmanager.html`` carry a fallback and are fine --
    a distinction worth the reconciliation, since the raw grep said 53) and is
    defined in NONE of them.  It is defined only in the two SERVER-RENDERED pages
    (``src/api/main.py``'s reader and ``src/api/law.py``), which carry their own
    ``:root`` block -- so ``reader.css`` is correct and everything the SPA loads is not.
    Nothing failed, nothing logged, and every declaration that named it evaporated:
    measured live, all eleven dialogs' ``border:1px solid var(--line)`` computed to
    ``border-top-style: none``.

    This is the ``class="small"`` defect one level down -- a NAME with no definition,
    where the markup keeps making a claim the stylesheet never honours -- and the guard
    is the thing that closes the class, since the last one closed only its instance.
    """
    defined: set[str] = set()
    referenced: dict[str, int] = {}
    for name in _SPA_FILES:
        text = _strip_comments(read_static(name))
        defined |= _defined_tokens(text)
        for tok in _BARE_VAR.findall(text):
            referenced[tok] = referenced.get(tok, 0) + 1
    assert "--fg" in defined and "--panel" in defined, (
        "ANTI-VACUITY: the scan found none of the tokens this app certainly defines, so "
        "an empty 'undefined' set would prove nothing"
    )
    assert len(referenced) > 20, f"ANTI-VACUITY: only {len(referenced)} var() references found"

    undefined = {t: n for t, n in referenced.items() if t not in defined}
    new = sorted(set(undefined) - set(_KNOWN_UNDEFINED))
    assert not new, (
        f"{new} are referenced by the SPA bundle and defined nowhere it loads. A var() that "
        "resolves to nothing voids the WHOLE declaration it sits in, silently -- so this is "
        "not a lint nit, it is a rule that will never render. Define it, or use --border."
    )
    for tok, budget in _KNOWN_UNDEFINED.items():
        got = undefined.get(tok, 0)
        assert got <= budget, (
            f"{tok} grew from {budget} to {got} references; it is defined nowhere the SPA "
            "loads, so every one of them is a declaration that silently does nothing"
        )
        assert got == budget or got == 0, (
            f"{tok} fell from {budget} to {got}: lower the budget in the same commit that "
            "frees the slack, or the next drift lands in the gap"
        )


def test_the_census_can_actually_fail():
    """The anti-vacuity twin, because the assertion above is the shape that passes for
    free.  Feed it the real defect and it must name the token."""
    broken = ":root { --fg:#fff; --panel:#000; }\n.x { border:1px solid var(--nope); }"
    defined = _defined_tokens(broken)
    assert sorted(_referenced_tokens(broken) - defined) == ["--nope"], (
        "the census cannot see an undefined token, so its green run over the bundle means "
        "nothing"
    )
