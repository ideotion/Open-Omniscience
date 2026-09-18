"""The admission audit's strings, ×12 — including the ones NO i18n gate can see.

WHY THIS FILE EXISTS. Two classes of string on this surface are structurally invisible to
`scripts/i18n_report.py`:

  * a `tf()` FRAME. Every pattern in that script excludes `{` from its character class on
    purpose, so `"Showing {shown} of {total} admissions"` registers neither as an
    untranslatable UI string nor as an unkeyed `t()` call. Both gates report green while
    eleven locales render English (the 2026-09-18 lesson).
  * SERVER-EMITTED PROSE. The gates measure the locale FILES and the static assets; a
    sentence composed in Python and passed through `t()` on arrival never asks for a key,
    and a string that never asks for a key is not missing one.

So the gates are green either way and this file is the only thing standing between the
surface and an English-only caveat. It reads the frames out of the SHIPPED renderer and
the prose out of the SHIPPED module — never a re-typed copy, which would agree with a
defect — and it carries a positive control, because an extractor that finds nothing passes
every assertion below it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src/static/locales"
UI = ROOT / "src/static/app-ai-tools.js"

# The twelve the informed-consent non-negotiable names.
EXPECTED_LOCALES = {"en", "fr", "es", "de", "pt", "ru", "zh", "ja", "ar", "hi", "bn", "id"}

# The two renderers this surface is built from. Named explicitly: a sweep of the whole
# file would drag in every other panel's frames and stop being a claim about THIS one.
RENDERERS = ("_admissionRow", "loadAdmissionAudit")


def _locale(code: str) -> dict:
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def test_every_locale_file_is_present() -> None:
    """Anti-vacuity for every test below: they iterate this set, so an empty or shrunken
    set would make all of them pass while proving nothing."""
    found = {p.stem for p in LOCALES.glob("*.json")}
    assert found >= EXPECTED_LOCALES, f"missing locale files: {EXPECTED_LOCALES - found}"


def _renderer_bodies() -> str:
    from tests.js_source_helper import function_body, strip_comments

    src = strip_comments(UI.read_text(encoding="utf-8"))
    bodies = [function_body(src, name) for name in RENDERERS]
    assert all(bodies), f"a renderer body came back empty: {RENDERERS}"
    return "\n".join(bodies)


def test_every_tf_frame_the_audit_renders_is_keyed_in_all_twelve_locales() -> None:
    """The frames are harvested from the SHIPPED renderers, so adding one without a key
    reddens here rather than shipping English into eleven locales."""
    frames = sorted(set(re.findall(r'\btf\(\s*"([^"]+)"', _renderer_bodies())))
    # Positive control. An extraction that finds nothing satisfies the loop below for free,
    # and this surface really does use `tf` -- the count is asserted, not assumed.
    assert len(frames) >= 2, f"the frame extractor found {len(frames)}; it should find at least 2"

    en = _locale("en")
    for frame in frames:
        assert frame in en, f"tf frame not keyed in en.json: {frame!r}"
        holes = set(re.findall(r"\{(\w+)\}", frame))
        assert holes, f"a tf frame with no hole is a plain string: {frame!r}"
        for code in sorted(EXPECTED_LOCALES):
            d = _locale(code)
            assert frame in d, f"{code}.json is missing the tf frame {frame!r}"
            value = d[frame]
            assert value.strip(), f"{code}.json has an empty value for {frame!r}"
            # A REORDERED frame is legitimate -- word order is the whole reason to
            # translate a frame rather than its fragments -- so compare the hole SETS,
            # never the sequence. A lost hole renders a literal `{x}` to a reader.
            assert set(re.findall(r"\{(\w+)\}", value)) == holes, (
                f"{code}.json changed the frame holes of {frame!r}: {value!r}"
            )


def test_the_server_prose_this_surface_renders_is_keyed_in_all_twelve_locales() -> None:
    """A caveat built on the server is still a string on a translated page.

    The constants are read out of the SHIPPED modules with `ast`, because both are written
    as adjacent string literals and no particular line-wrapping of them is the value.
    """
    import ast

    wanted: list[tuple[str, str]] = []

    qual = ast.parse((ROOT / "src/catalog/qualification.py").read_text(encoding="utf-8"))
    for node in ast.walk(qual):
        if isinstance(node, ast.FunctionDef) and node.name == "admission_audit":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    for k, v in zip(sub.keys, sub.values, strict=False):
                        # Both prose fields the client renders. `method` is evidence in the
                        # payload that no surface draws, so it needs no key -- the house
                        # convention keeps it for a reader checking the number.
                        if isinstance(k, ast.Constant) and k.value in ("caveat", "coverage_note"):
                            folded = ast.literal_eval(v)
                            wanted.append((f"admission_audit {k.value}", folded))
    settings = ast.parse((ROOT / "src/scheduler/settings.py").read_text(encoding="utf-8"))
    for node in ast.walk(settings):
        # BOTH forms. `_RETIRED_KEYS: dict[str, str] = {...}` is an AnnAssign, not an
        # Assign -- and reading only the latter is exactly what this test's own positive
        # control caught on its first run, which is the argument for having one.
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_RETIRED_KEYS" for t in targets):
            continue
        assert isinstance(node.value, ast.Dict), "_RETIRED_KEYS is no longer a dict literal"
        for k, v in zip(node.value.keys, node.value.values, strict=False):
            wanted.append((f"retired:{ast.literal_eval(k)}", ast.literal_eval(v)))

    # Positive control again: if the AST walk stopped matching (a rename, a refactor into a
    # helper), an empty list would make this test a no-op that reads as coverage.
    assert len(wanted) >= 2, f"the prose extractor found {len(wanted)} strings; expected >= 2"

    for label, sentence in wanted:
        for code in sorted(EXPECTED_LOCALES):
            d = _locale(code)
            assert sentence in d, (
                f"{code}.json has no key for the server prose {label}; it would render in "
                f"English. The key must match the server constant VERBATIM: {sentence!r}"
            )
            assert d[sentence].strip(), f"{code}.json has an empty value for {label}"


def test_the_three_statuses_are_keyed_and_DISTINCT_in_every_locale() -> None:
    """`unqualified` / `qualified` / `disqualified` are a CLOSED app vocabulary, not data,
    and the audit renders the prior status as a word an operator reads.

    A Chromium walk in `ar` is what found this: `unqualified` had no key at all, so a
    fully-translated Arabic line carried the raw English token. No i18n gate can see it --
    the value sits inside a composed text node the DOM walker cannot match, and a key that
    is never requested is not a key that is missing.

    DISTINCTNESS is the second half and matters more: `unqualified` means NEVER JUDGED and
    `disqualified` means JUDGED AND REJECTED. A locale that renders both with one word
    asserts an equivalence the engine does not make.
    """
    trio = ("unqualified", "qualified", "disqualified")
    for code in sorted(EXPECTED_LOCALES):
        d = _locale(code)
        values = []
        for key in trio:
            assert key in d, f"{code}.json has no key for the status {key!r}"
            assert d[key].strip(), f"{code}.json has an empty value for {key!r}"
            values.append(d[key])
        assert len(set(values)) == 3, (
            f"{code}.json collapses the three statuses onto fewer words: {values}. "
            "'never judged' and 'judged and rejected' are different facts."
        )


def test_the_audit_renders_the_prior_status_through_the_translator() -> None:
    """A key that exists is not a key that is USED -- the defect above was exactly a
    renderer escaping the raw value onto the page while the keys sat there unread."""
    from tests.js_source_helper import function_body, strip_comments

    body = strip_comments(function_body(strip_comments(UI.read_text(encoding="utf-8")),
                                        "_admissionRow"))
    assert "t(e.prior_status)" in body, (
        "_admissionRow renders the prior status without translating it; a non-English "
        "operator sees the raw English token inside an otherwise translated line"
    )


def test_the_client_passes_the_server_caveat_through_the_translator() -> None:
    """A key that exists is not a key that is USED. The audit renders the server's caveat,
    so the renderer has to hand it to `t()` -- escaping it straight onto the page is the
    recorded defect where every gate stays green and the sentence stays English."""
    from tests.js_source_helper import strip_comments

    body = strip_comments(UI.read_text(encoding="utf-8"))
    assert "t(d.caveat" in body, (
        "the audit renders the server's caveat without translating it"
    )


@pytest.mark.parametrize(
    "key",
    [
        "Admission audit",
        "Judging has not admitted any source on its own yet.",
        "Admission undone.",
        "Collection was",
        "Status was",
        "Undo",
        "Undone",
        "never judged",
        "never set",
    ],
)
def test_each_audit_chrome_string_is_translated_in_every_locale(key: str) -> None:
    """The ordinary chrome. Gate 1 would catch a MISSING key, so what this adds is that the
    value is not simply the English echoed back in eleven locales -- which is what a
    half-done translation pass leaves behind and what no count can see."""
    en = _locale("en")
    assert key in en, f"{key!r} is not keyed in en.json"
    echoed = []
    for code in sorted(EXPECTED_LOCALES - {"en"}):
        d = _locale(code)
        assert key in d, f"{code}.json is missing {key!r}"
        assert d[key].strip(), f"{code}.json has an empty value for {key!r}"
        if d[key] == en[key]:
            echoed.append(code)
    # A legitimate copy exists (a proper noun, a unit), so this is not an absolute ban --
    # it is a bound. All eleven identical means nobody translated it.
    assert len(echoed) < 11, f"{key!r} is the untranslated English in every locale: {echoed}"
