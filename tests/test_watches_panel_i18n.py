"""The Watches panel shipped English-only, on a cost argument against a rule.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The panel's own comment stated the choice and its reason: "English strings here
(matching the keyword-explorer/stats sub-features) so i18n stays 100% with zero
new keys". Two things are wrong with that as a defence.

It is a COST argument against a NON-NEGOTIABLE. ``CLAUDE.md``'s informed-consent
rule says every user-facing string ships x12, and applies it to "every surface
built or reworked from now on"; this panel came after that line.

And the strings were never free. They were 24 of the 575 the untranslatable
ratchet counts, so the panel was already being paid for -- in a column nobody
reads. Translating them moved BOTH ratchets down (575 -> 570 untranslatable,
314 -> 312 unkeyed ``t()`` call sites), and both ceilings are lowered in the same
change, per the ledger's own rule that slack left behind invites the next drift
to land unseen.

VERIFIED IN CHROMIUM, 2026-09-09, in en / fr / ja / ar (ar being the RTL case):
the empty state, the create-path validation message and the check-now result all
render in the reader's language, with a clean console.

The non-English drafts are machine-written and flagged for native review -- the
same standing convention the GUI-gallery strings carry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.js_source_helper import function_source, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

#: Every string the panel puts in front of a reader.
_KEYS = [
    "never", "Disable", "Enable", "on", "off", "open set ↗",
    "No watches yet — add one above. The engine runs after every collection pass.",
    "Could not load watches: {error}",
    "Enter a condition (search query) first.",
    "Watch added. It runs after every collection pass, or use “Check now”.",
    "Could not add: {error}",
    "Could not update watch: {error}",
    "New condition (search query) — leave blank to keep:",
    "Min articles to fire (leave blank to keep):",
    "Window in days (leave blank to keep):",
    "Could not edit watch: {error}",
    "Delete this watch and its history?",
    "Could not delete watch: {error}",
    "{n} watch(es) fired — see Home, or the history below.",
    "No watches fired (no new matching articles).",
    "Check failed: {error}",
    "≥ {n} articles within {d} day(s) · last fired: {when}",
    "{n} articles ({new} new)",
    "Watch: {name}",
]

_FUNCS = ("loadWatches", "createWatch", "toggleWatch", "editWatch",
          "deleteWatch", "evaluateWatches")


def _panel() -> str:
    js = read_static("app-insights.js")
    return "\n".join(function_source(js, name) for name in _FUNCS)


def test_every_watches_string_is_keyed_in_all_twelve_locales() -> None:
    locales = sorted(_LOCALES.glob("*.json"))
    assert len(locales) == 12, f"expected 12 locale files, found {len(locales)}"
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = data.get("map", data)
        missing = [k for k in _KEYS if not mapping.get(k)]
        assert not missing, f"{path.name} is missing {len(missing)}: {missing[:4]}"


def test_no_bare_english_sentence_is_left_in_the_panel() -> None:
    """A key that exists but is not USED translates nothing.

    Comments are stripped first: this panel's own comment quotes the strings it
    is about, and the recorded house lesson is that an unstripped guard reads
    the explanation instead of the code.
    """
    src = strip_comments(_panel())
    # Any string literal of three or more ASCII words that is not inside a t()/tf()
    # call is a sentence the reader would see untranslated.
    offenders = []
    for m in re.finditer(r'"([A-Z][A-Za-z][^"]{14,})"', src):
        text = m.group(1)
        if text in _KEYS:
            continue
        if not re.search(r"[a-z] [a-z]", text):     # not prose
            continue
        before = src[max(0, m.start() - 4):m.start()]
        if before.endswith("t(") or before.endswith("tf("):
            continue
        offenders.append(text[:70])
    assert not offenders, (
        "these reader-visible sentences are still bare English:\n  " + "\n  ".join(offenders)
    )


def test_the_translated_calls_are_actually_wired() -> None:
    """Anti-vacuity for the guard above, which only proves an ABSENCE."""
    src = strip_comments(_panel())
    for needle in ('t("No watches yet', 't("Enter a condition', 'tf("Check failed:',
                   'tf("{n} articles ({new} new)"', 't("Delete this watch'):
        assert needle in src, f"{needle} is not called anywhere in the panel"
    # The prompts a screen-reader user hears first must be translated too -- they
    # were the easiest to overlook, being browser chrome rather than app markup.
    edit = strip_comments(function_source(read_static("app-insights.js"), "editWatch"))
    assert edit.count("prompt(t(") == 3, (
        "all three edit prompts must be translated; found "
        f"{edit.count('prompt(t(')} of 3"
    )


def test_both_ratchets_were_lowered_by_the_slack_this_freed() -> None:
    """The ledger's rule: lower a ratchet in the same change that frees it, or the
    next drift lands inside the slack unseen."""
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    untranslatable = re.search(r"--max-untranslatable (\d+)", ci)
    unkeyed = re.search(r"--max-unkeyed-t-calls (\d+)", ci)
    assert untranslatable and unkeyed, "the i18n ratchets are gone from ci.yml"
    assert int(untranslatable.group(1)) <= 570, (
        "translating this panel freed 5 untranslatable strings (575 -> 570); the "
        f"ceiling still reads {untranslatable.group(1)}"
    )
    assert int(unkeyed.group(1)) <= 312, (
        "translating this panel freed 2 unkeyed t() call sites (314 -> 312); the "
        f"ceiling still reads {unkeyed.group(1)}"
    )
