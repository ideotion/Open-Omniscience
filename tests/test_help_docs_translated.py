"""Row E (S06-05 S3): the Help documents x the twelve locales, counted honestly.

The serving seam already exists (``?lang=fr`` serves ``docs/i18n/fr/<FILE>`` when it is there, English otherwise, and ``X-OO-Doc-Lang``
says which). What was missing is anything that says how much of the 10 documents x 11 non-English locales is actually translated, and that
refuses a draft that is only a fragment. Three states, decided by the files themselves:

* COMPLETE: ``docs/i18n/<lang>/<FILE>`` exists, is UTF-8 Markdown and has the SAME HEADING SKELETON as the English (the same sequence of
  heading levels, headings in code fences not counted): the omnibar's Help-content group lands on headings, so a translated document with a
  different skeleton would send a reader to the wrong place. Only these count toward the ratchet.
* PARTIAL: the file exists but its skeleton differs (``fr/QUICKSTART.md`` was an 8-heading abridgement of a 17-heading document until 2026-11-13). It is served, and
  it is LISTED in ``PARTIAL`` below with the reason; it is never counted as translated.
* ABSENT: no file. The gap is the complement of the other two, named in every failure message.

``PARTIAL`` is exact, not a floor: a draft that becomes complete, or a new partial, must change this file in the same commit, so the listing
cannot go stale in either direction. The ratchet (``FLOOR``) is per tranche and may only rise; the tranche membership is the PROPOSED
staging of the gate's row E (Q1122 = b), not a ruling. Drafts are AI-drafted in a build session and flagged for native review
(R677, 2026-11-13: the loopback rule governs the app at run time, not how its public documentation is written); no draft here
was cut short to move a number.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
_DOCS = _ROOT / "docs"

#: PROPOSED staging (row E; measured 2026-11-04 in characters: tranche 1 = 250,293, tranche 2 = 150,490, tranche 3 = 349,446).
TRANCHES: dict[int, tuple[str, ...]] = {
    1: ("user-manual", "quickstart"),
    2: ("governance", "ethics", "security", "contributing", "architecture"),
    3: ("design", "roadmap", "changes"),
}
#: COMPLETE (slug, lang) drafts per tranche that must always exist. Raise it with the drafts; lowering it needs a ruling.
FLOOR: dict[int, int] = {1: 22, 2: 0, 3: 0}
#: Drafts that exist and are served but are NOT complete: the reason is the measurement, never a judgement of the translation.
PARTIAL: dict[tuple[str, str], str] = {}

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_HEADING = re.compile(r"^(#{1,6}) +(.*\S)\s*$")


def _locales() -> list[str]:
    """The UI's locale files are the list of languages; English is the authoritative text, not a translation."""
    codes = sorted(p.stem for p in (_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert "en" in codes and len(codes) == 12, codes
    return [c for c in codes if c != "en"]


def _served_docs() -> dict[str, str]:
    """slug -> file, read out of the API's own allow-list (``_DOCS``), so a new Help document inherits this test."""
    from src.api.main import _DOCS as DOCS

    return {slug: meta["file"] for slug, meta in DOCS.items()}


def _skeleton(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def skeleton_problem(english: str, draft: str) -> str | None:
    """None when the draft has the English document's heading skeleton, else a sentence naming the first English heading it lacks."""
    en, tr = _skeleton(english), _skeleton(draft)
    if [lv for lv, _ in en] == [lv for lv, _ in tr]:
        return None
    for i, (lv, title) in enumerate(en):
        if i >= len(tr) or tr[i][0] != lv:
            return f"heading {i + 1} of {len(en)} ({'#' * lv} {title}) has no counterpart at the same level: the draft has {len(tr)} headings"
    return f"the draft has {len(tr)} headings, the English {len(en)}: the extra ones start at heading {len(en) + 1}"


def _state(slug: str, file: str, lang: str) -> tuple[str, str]:
    path = _DOCS / "i18n" / lang / file
    if not path.exists():
        return "absent", ""
    text = path.read_text(encoding="utf-8")  # UnicodeDecodeError = not UTF-8 = a red, by name
    problem = skeleton_problem((_DOCS / file).read_text(encoding="utf-8"), text)
    return ("complete", "") if problem is None else ("partial", problem)


def _table() -> dict[tuple[str, str], tuple[str, str]]:
    return {(slug, lang): _state(slug, file, lang) for slug, file in _served_docs().items() for lang in _locales()}


def test_every_served_document_belongs_to_exactly_one_tranche():
    placed = [s for slugs in TRANCHES.values() for s in slugs]
    assert sorted(placed) == sorted(_served_docs()), (
        f"a Help document is in no tranche, or in two: tranches hold {sorted(placed)}, _DOCS serves {sorted(_served_docs())}"
    )


def test_the_partial_listing_is_exact_and_names_the_headings():
    table = _table()
    actual = {k for k, (state, _) in table.items() if state == "partial"}
    assert actual == set(PARTIAL), (
        f"PARTIAL is out of date. On disk but not listed: {sorted(actual - set(PARTIAL))}; listed but no longer partial: "
        f"{sorted(set(PARTIAL) - actual)}. A complete draft leaves the list in the same commit that finishes it."
    )
    for key in PARTIAL:
        assert table[key][1], f"{key} is partial but no heading is named"


def test_a_translated_of_total_ratchet_per_tranche_that_never_falls():
    table = _table()
    langs = _locales()
    lines = []
    for n, slugs in TRANCHES.items():
        complete = sum(1 for s in slugs for lg in langs if table[(s, lg)][0] == "complete")
        total = len(slugs) * len(langs)
        lines.append(f"tranche {n}: {complete} of {total} complete")
        gaps = [f"{s}/{lg}" for s in slugs for lg in langs if table[(s, lg)][0] != "complete"]
        assert complete >= FLOOR[n], f"tranche {n} fell below its floor {FLOOR[n]}: {complete} of {total}. Gaps: {gaps}"
    assert lines, "no tranche"  # the figure rides every failure message above; the gate's section 3 carries the same numbers


@pytest.mark.parametrize("lang", _locales())
def test_every_existing_draft_is_utf8_markdown_with_a_banner_comment_and_belongs_to_a_served_document(lang):
    folder = _DOCS / "i18n" / lang
    if not folder.exists():
        pytest.skip(f"no drafts for {lang}: every document is an absent gap")
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<!--"), f"{path.relative_to(_ROOT)} has no banner comment (a draft says what it is)"
        assert path.name in _served_docs().values(), f"{path.relative_to(_ROOT)} is a draft of a document Help does not serve"


def test_the_skeleton_check_reddens_by_name_when_one_heading_is_removed():
    """Mutation check: delete one heading from a copy of a real, complete document and the comparison names it."""
    english = (_DOCS / "QUICKSTART.md").read_text(encoding="utf-8")
    assert skeleton_problem(english, english) is None
    lines = english.splitlines()
    idx = next(i for i, line in enumerate(lines) if line.startswith("## ") and i > 3)
    mutated = "\n".join(lines[:idx] + lines[idx + 1 :])
    problem = skeleton_problem(english, mutated)
    assert problem is not None, "removing a heading went unnoticed"
    assert f"the English {len(_skeleton(english))}" in problem or "has no counterpart" in problem, problem
    # a heading inside a code fence is not part of the skeleton (the same document, one fenced fake heading added)
    assert skeleton_problem(english, english + "\n```\n# not a heading\n```\n") is None


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_the_served_language_header_and_the_list_flag_tell_the_truth(client):
    """``X-OO-Doc-Lang`` is the language of the file ACTUALLY served and ``translated`` is its negation of English, for every
    slug x locale: a missing draft falls back to English and says so; an existing one (complete or partial) says its own."""
    table = _table()
    for lang in _locales():
        listed = {d["slug"]: d["translated"] for d in client.get(f"/api/docs?lang={lang}").json()["docs"]}
        for slug in _served_docs():
            r = client.get(f"/api/docs/{slug}?lang={lang}")
            assert r.status_code == 200, (slug, lang)
            exists = table[(slug, lang)][0] != "absent"
            assert r.headers["x-oo-doc-lang"] == (lang if exists else "en"), (slug, lang, r.headers["x-oo-doc-lang"])
            assert listed[slug] is exists, (slug, lang)
    # English asks for nothing translated
    assert client.get("/api/docs/quickstart?lang=en").headers["x-oo-doc-lang"] == "en"


def test_the_locale_list_is_the_uis_twelve():
    meta = json.loads((_ROOT / "src" / "static" / "locales" / "en.json").read_text(encoding="utf-8"))["_meta"]
    assert meta["status"] == "source"
    assert len(_locales()) == 11
