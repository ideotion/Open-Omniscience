"""Row 419 (2026-11-24): the case-insensitive place scan finds its candidates through ONE prefilter pass.

What may not regress: for any text, ``_scan_candidates`` returns exactly the list the per-pattern ``finditer`` loop
returned -- same patterns, same spans, same order -- so ``extract_locations`` claims the same spans and writes the same
rows. The reference loop is kept here, and it is checked over the WHOLE pattern table (every name, in several cases and
surroundings, folded characters included), the golden extraction fixtures in twelve languages, and seeded random
concatenations, not only over a sample corpus."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from src.timemap import locextract as L

_FIXTURES = Path(__file__).parent / "fixtures" / "extraction_golden"


def _reference(text: str) -> list[tuple]:
    scan, _index = L._dispatch()
    return [(i, m.start(), m.end(), name, kind) for i, rx, name, kind in scan for m in rx.finditer(text)]


def _names() -> list[str]:
    return [name for _i, _rx, name, _k in L._dispatch()[0]]


def _variants(name: str) -> list[str]:
    forms = {name, name.lower(), name.upper(), name.title(), name.swapcase(), name.capitalize()}
    out = []
    for f in sorted(forms):
        out += [f, f"In {f}, today.", f"({f})", f"{f}-based", f"x{f}", f"{f}x", f"{f}{f}", f"{f} {f}", f"{f}'s", f"«{f}»"]
    return out


def test_the_prefilter_covers_the_whole_case_insensitive_half():
    head_rx, headed, rest = L._scan_prefilter()
    scan = L._dispatch()[0]
    assert head_rx is not None, "the bundled table has a case-insensitive half to prefilter"
    assert sorted(e[0] for e in headed + rest) == sorted(e[0] for e in scan), "every pattern is looked for exactly once"
    assert len(headed) >= len(scan) - 2, "nearly all of it takes the one-pass path (otherwise the row bought nothing)"


@pytest.mark.parametrize("name", _names())
def test_every_name_in_every_case_and_surrounding(name):
    for text in _variants(name):
        assert L._scan_candidates(text) == _reference(text), text


def test_case_folds_the_engine_makes_and_lower_does_not():
    # İ (dotted capital I), ſ (long s), K (Kelvin sign), ﬁ ligature, and Turkish dotless ı: the folds the _dispatch
    # docstring warns about. The prefilter compiles with the patterns' own flags, so it agrees with them.
    texts = [
        "İSTANBUL and İRAN, İndia, İtaly", "Ruſſia and Ruſsia", "KENYA KOREA", "ﬁnland Fiji ﬁji", "ıran ITALY ıtaly",
        "SAUDİ ARABİA", "ſyria ſudan", "DEUTSCHLAND", "ÇAD Türkiye TÜRKİYE",
    ]
    for t in texts:
        assert L._scan_candidates(t) == _reference(t), t


def test_the_golden_fixtures_in_twelve_languages():
    n = 0
    for f in sorted(_FIXTURES.glob("*.json")):
        for a in json.loads(f.read_text(encoding="utf-8"))["articles"]:
            text = (a.get("text") or "")[: L._MAX_SCAN]
            assert L._scan_candidates(text) == _reference(text), (f.name, a.get("id"))
            n += 1
    assert n >= 12


def test_seeded_random_concatenations_of_names_and_noise():
    rng = random.Random(419)
    names = _names()
    noise = [" ", ", ", "-", "'", ".", "\n", "x", "Ünited", "of", "the", "and", "1", "_", "é"]
    for _ in range(400):
        parts = []
        for _k in range(rng.randint(3, 25)):
            w = rng.choice(names) if rng.random() < 0.6 else rng.choice(noise)
            w = rng.choice((str.lower, str.upper, str.title, lambda s: s))(w)
            parts.append(w)
            parts.append(rng.choice(noise))
        text = "".join(parts)
        assert L._scan_candidates(text) == _reference(text), text


def test_extract_locations_is_unchanged_on_a_nested_name():
    """The claim rule still sees the same candidates: the longest name wins its span (Northern Ireland, not Ireland)."""
    out = L.extract_locations("Talks in Northern Ireland and South Sudan; the South China Sea too.")
    countries = {o["country"] for o in out}
    assert "ie" not in countries and "sd" not in countries


def test_a_name_outside_the_argument_keeps_the_per_pattern_scan(monkeypatch):
    """A case-insensitive name that does not start with a word character goes to ``rest`` and is still found."""
    odd = (9999, re.compile(r"\b\-zone\b", re.IGNORECASE), "-zone", "guard")
    scan, index = L._dispatch()
    monkeypatch.setattr(L, "_dispatch", lambda: (scan + [odd], index))
    L._scan_prefilter.cache_clear()
    try:
        head_rx, headed, rest = L._scan_prefilter()
        assert odd in rest and odd not in headed
    finally:
        monkeypatch.undo()
        L._scan_prefilter.cache_clear()
