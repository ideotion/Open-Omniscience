"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

S6 of the law-vertical brief: the generated vetting board (one page carrying every
law-catalog row that needs a maintainer decision).

The thing being guarded is that the page cannot lie. A decision table is the format
most likely to grow a back-filled cell — the shape has a slot for every intersection
and an empty one reads as an omission — so every row must resolve to a real catalog
entry, and the committed file must still be what the generator produces.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "law_vetting_board", _ROOT / "scripts" / "law_vetting_board.py"
)
board = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(board)

BOARD_MD = _ROOT / "docs" / "product" / "LAW_VETTING_BOARD.md"


def _all_sources() -> list[dict]:
    return board._rows(board.GENERATED) + board._rows(board.CURATED)


def _rendered() -> str:
    data = yaml.safe_load(board.GENERATED.read_text(encoding="utf-8")) or {}
    return board.render(_all_sources(), as_of=str(data.get("as_of", "unknown")))


def test_the_committed_board_is_what_the_generator_produces():
    """A generated artifact that is allowed to drift is worse than none: a reader
    trusts a committed page more than a script they would have to run."""
    assert BOARD_MD.exists(), "run: python3 scripts/law_vetting_board.py > " + str(BOARD_MD)
    assert BOARD_MD.read_text(encoding="utf-8") == _rendered(), (
        "docs/product/LAW_VETTING_BOARD.md is stale — regenerate it with "
        "`python3 scripts/law_vetting_board.py > docs/product/LAW_VETTING_BOARD.md`"
    )


def test_every_row_on_the_board_resolves_to_a_real_catalog_entry():
    """The correspondence asserted in the direction a READER travels: they see a domain
    on the page and go looking for it in the catalog. A count check cannot see a row
    that names a source which does not exist — that is exactly the cell that gets
    back-filled."""
    sources = _all_sources()
    known_domains = {str(s.get("domain")) for s in sources if s.get("domain")}
    known_countries = {str(s.get("country")) for s in sources if s.get("country")}
    rows = 0
    for line in _rendered().splitlines():
        if not line.startswith("| ") or line.startswith("| ---") or line.startswith("| Country"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        country, domain = cells[0], cells[1]
        rows += 1
        assert country in known_countries or country == "—", country
        if domain != "_(none — deliberate)_":
            assert domain in known_domains, f"the board names a domain the catalog lacks: {domain}"
    assert rows >= 40, f"anti-vacuity: the walk found only {rows} rows to check"


def test_a_row_lands_in_at_most_one_bucket():
    """Otherwise the maintainer is asked the same question twice and the header count
    over-states the backlog."""
    buckets = board.classify(_all_sources())
    seen: list[int] = []
    for rows in buckets.values():
        seen.extend(id(r) for r in rows)
    assert len(seen) == len(set(seen))


def test_the_two_honest_gaps_are_both_data_and_both_on_the_board():
    """North Korea's gap used to live ONLY in a YAML comment, so no tool could read it
    while Yemen's identical record was a domain-less lead row. Both are rows now."""
    gaps = {str(s.get("country")) for s in board.classify(_all_sources())["gap"]}
    assert gaps == {"kp", "ye"}, gaps
    text = _rendered()
    assert "North Korea" in text and "Yemen" in text


def test_grenada_appears_because_its_own_evidence_says_the_site_is_down():
    """A `fetched` row can still need a decision. laws.gov.gd is a real .gov.gd domain
    that serves a maintenance placeholder, which no status field records — only the
    prose does."""
    down = {str(s.get("domain")) for s in board.classify(_all_sources())["down"]}
    assert "laws.gov.gd" in down, sorted(down)


def test_the_triage_predicates_actually_discriminate():
    """Anti-vacuity for buckets 3 and 4. A regex that matched everything, or nothing,
    would produce a page that looks exactly as complete as a working one."""
    assert board.BLOCKED_RE.search("robots.txt disallows automated fetch")
    assert board.BLOCKED_RE.search("returns HTTP 403 to non-browser agents")
    assert not board.BLOCKED_RE.search("loaded the enumeration page and counted 76 codes")
    assert board.DOWN_RE.search("returns a static 'Upgrading...' maintenance placeholder")
    assert not board.DOWN_RE.search("a working feed with dated items")
    # and the buckets are non-degenerate on the real catalog
    counts = {k: len(v) for k, v in board.classify(_all_sources()).items()}
    assert all(n > 0 for n in counts.values()), counts
    assert counts["blocked"] < len(_all_sources()) / 2, (
        f"a triage that flags half the catalog is not triage: {counts}"
    )


def test_a_truncated_cell_says_it_is_truncated():
    """A clipped sentence read as the whole record is how a maintainer decides on half
    the evidence."""
    long_text = "x" * 400
    cell = board._cell(long_text)
    assert "truncated, 400 chars in the catalog" in cell
    assert board._cell("short") == "short"
    assert board._cell("") == "—"


def test_the_page_states_that_its_triage_is_not_exhaustive():
    """Sections 3 and 4 are a keyword pass over prose. Presenting them as the complete
    list of blocked or dead domains would be a fabricated completeness claim."""
    text = _rendered()
    assert "keyword triage" in text
    assert "not an exhaustive list" in text
    assert re.search(r"never evades|scraped around", text), (
        "the page must say the block is respected, not worked around"
    )
