"""0.5 row G — the ONE version reader, wired into both readers (Q918's note; brief S05-07 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q918's note is a requirement, not a style preference: the law reader must be "homogenous
with other parts of the app's ability to track change, such as wikipedia articles". The
way that regresses is quiet — somebody gives one of the two readers its own selector or
its own diff, and the two drift apart one disclosure at a time. So these guards pin that
BOTH surfaces mount the same component, and that the component keeps the disclosures the
ruling lists, with its words keyed ×12.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_COMPONENT = (_STATIC / "ooversions.js").read_text(encoding="utf-8")
_LIVING = (_STATIC / "app-living.js").read_text(encoding="utf-8")
_MAP = (_STATIC / "app-map.js").read_text(encoding="utf-8")
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_LAW_API = (_ROOT / "src" / "api" / "law.py").read_text(encoding="utf-8")


def test_both_readers_mount_the_one_component():
    # The Living sources Law panel and the Wikipedia tracked-changes panel...
    assert re.search(r"ooVersionReader\(host, base, \{ onLanguage", _LIVING)
    assert "/api/law/documents/${Number(id)}" in _LIVING
    assert "/api/wiki/pages/${Number(pageId)}" in _LIVING
    assert "livingMountWikiVersions(id)" in _MAP
    # ... and the standalone law reader page, which mounts itself from its markup.
    assert 'data-ov-base="/api/law/documents/' in _LAW_API
    assert '<script src="/static/ooversions.js" defer></script>' in _LAW_API
    # No second, law-only comparison widget.
    assert "function ooVersionReader" not in _LIVING and "window.ooVersionReader = mount" in _COMPONENT


def test_the_component_is_loaded_before_its_callers_and_precached():
    assert _INDEX.index("/static/ooversions.js") < _INDEX.index("/static/app-living.js")
    assert '"/static/ooversions.js"' in (_STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_component_draws_every_disclosure_the_ruling_lists():
    """Q918 (a): version selector · side-by-side diff · provision navigation · an ELI /
    CELEX permalink · the licence line · "AI-derived · unreliable" · translation provenance."""
    for needle in (
        'data-ov="from"',
        'data-ov="to"',
        "ov-grid",
        "data-ov-part",
        '"Permalink"',
        '"Identifier"',
        '"Licence"',
        '"Provenance"',
        "to.summary.label",
        "data-ov-lang",
    ):
        assert needle in _COMPONENT, needle


def test_the_component_uses_no_inline_handlers_and_shields_data_from_the_walker():
    assert not re.search(r"\son[a-z]+=", _COMPONENT), "inline handler in ooversions.js (row I's CSP ratchet)"
    assert 'setAttribute("data-i18n-dyn", "")' in _COMPONENT
    assert "oo:langchange" in _COMPONENT


def test_the_language_switch_shows_only_for_more_than_one_language():
    assert "langs.length > 1" in _COMPONENT


def test_a_missing_summary_draws_nothing():
    assert 'if (!to || !to.summary) return "";' in _COMPONENT


def test_every_new_string_is_keyed_in_all_twelve_locales():
    keys = [
        "≈ AI-derived · unreliable",
        "Compare versions",
        "ELI / CELEX permalink",
        "Search the laws as they stood on a day",
        "What changed this week in the laws you follow",
        "Amendment activity on the map",
        "from {from} until {until}",
        "the edit's own timestamp, as the source records it",
    ]
    for path in sorted((_STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), f"{path.name} lacks {k!r}"
