"""Visible basis / as-of disclosure chip on maintained aggregates (backlog item #6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintained-counter aggregates already carry the honesty envelope
{value, basis:exact|estimated, as_of, method, n} (and rollup paths add a cache
disclosure {source, as_of, note}). The frontend now renders a small VISIBLE chip
next to those numbers on Insights -> Trends (Top terms) and Insights -> Groups
(super-groups): "exact / estimated · as of <date>", with the method / n / rollup
note on the #oo-tip hover (informed-consent-by-layering). It is a DISCLOSURE, never
a score. Pure string-assertion wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")
_CSS = (_STATIC / "app.css").read_text(encoding="utf-8")


def test_chip_host_elements_exist():
    assert 'id="trd-basis"' in _HTML, "Insights Trends needs a chip host next to Top"
    assert 'id="sg-basis"' in _HTML, "Insights Groups needs a chip host"


def test_basischip_reads_the_envelope_not_a_score():
    assert "function basisChip(" in _JS
    # reads the envelope disclosure fields, not a numeric grade
    assert "counts.basis" in _JS and "counts.as_of" in _JS
    assert "counts.method" in _JS and "counts.n" in _JS
    # exact vs estimated is the only visible verdict — never a *score* key
    assert 'counts.basis === "estimated"' in _JS
    assert 'basisScore' not in _JS and 'counts.score' not in _JS


def test_chip_wired_into_trends_and_groups():
    assert "basisChip(top.counts, top.basis || rising.basis)" in _JS
    assert "basisChip(sgs.counts)" in _JS
    assert '$("trd-basis")' in _JS and '$("sg-basis")' in _JS


def test_estimated_is_flagged_with_the_caveat_colour():
    # 'estimated' is the honest staleness signal -> it wears the theme caveat colour.
    assert ".basis-chip" in _CSS
    assert ".basis-chip.est" in _CSS and "var(--caveat)" in _CSS


def test_labels_translated_and_hover_carries_the_method():
    assert 't(est ? "estimated" : "exact")' in _JS
    assert 't("as of")' in _JS
    # the long form (method + n + rollup note) rides the title attribute (#oo-tip hover)
    assert "titleParts" in _JS and 'title="${esc(title)}"' in _JS
    en = (_STATIC / "locales" / "en.json").read_text(encoding="utf-8")
    fr = (_STATIC / "locales" / "fr.json").read_text(encoding="utf-8")
    assert '"estimated"' in en and '"estimated"' in fr
