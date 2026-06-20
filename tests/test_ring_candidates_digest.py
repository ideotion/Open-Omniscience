"""The ring-GAP digest in the keyword-diagnostics log (2026-06-20): the worklist
for the corpus-driven ring expansion + the translation-coverage self-check.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure over the digest function — no DB, no network. Uses the live equivalence rings
so a real ringed concept (election/economy) is excluded and a made-up term is the gap.
"""

from __future__ import annotations

from src.api.diagnostics import _ring_candidates


def _mk():
    # survivors: (kid, mentions, articles, first, last); meta: (term, norm, lang, is_ent, ent_type)
    survivors = [
        (1, 100, 50, None, None),  # election  -> ringed (en) -> coverage, not a gap
        (2, 90, 45, None, None),   # economy   -> ringed (en) -> coverage
        (3, 80, 40, None, None),   # zzwidgetry-> gap (en)
        (4, 70, 35, None, None),   # qqgizmo   -> gap (en)
        (5, 60, 30, None, None),   # NATO      -> entity -> excluded entirely
        (6, 10, 2, None, None),    # rarey     -> below min articles -> excluded
        (7, 50, 25, None, None),   # spamword  -> stoplisted (hidden) -> excluded
    ]
    meta = {
        1: ("election", "election", "en", False, None),
        2: ("economy", "economy", "en", False, None),
        3: ("zzwidgetry", "zzwidgetry", "en", False, None),
        4: ("qqgizmo", "qqgizmo", "en", False, None),
        5: ("NATO", "NATO", "en", True, "org"),
        6: ("rarey", "rarey", "en", False, None),
        7: ("spamword", "spamword", "en", False, None),
    }
    dom = {k: "en" for k in meta}
    hidden = {"spamword"}
    return survivors, meta, dom, (lambda n: n in hidden)


def test_ring_candidates_surfaces_gap_excludes_ringed_entities_stopwords():
    out = _ring_candidates(*_mk())
    en = out["by_language"]["en"]
    cands = {c["normalized"] for c in en["candidates"]}

    assert {"zzwidgetry", "qqgizmo"} == cands          # only the real gaps
    assert "election" not in cands and "economy" not in cands  # already ringed
    assert "NATO" not in cands                          # entity excluded
    assert "rarey" not in cands                         # below the spread gate
    assert "spamword" not in cands                      # stoplisted

    # coverage = ring-covered / gated terms (election+economy covered; 4 gated)
    assert en["ring_covered"] == 2 and en["gap_total"] == 2
    assert en["coverage"] == 0.5
    assert out["translation_coverage"] == 0.5
    assert out["gated_terms"] == 4
    assert "ring" in out["method"].lower()


def test_lowest_coverage_language_comes_first():
    # en fully covered (no gap); xx all-gap (0 coverage) -> xx must sort first
    survivors = [
        (1, 100, 50, None, None),  # election -> en, covered
        (2, 80, 40, None, None),   # foreigna -> xx, gap
        (3, 70, 35, None, None),   # foreignb -> xx, gap
    ]
    meta = {
        1: ("election", "election", "en", False, None),
        2: ("foreigna", "foreigna", "xx", False, None),
        3: ("foreignb", "foreignb", "xx", False, None),
    }
    dom = {1: "en", 2: "xx", 3: "xx"}
    out = _ring_candidates(survivors, meta, dom, lambda n: False)
    assert list(out["by_language"])[0] == "xx"  # lowest coverage first = the worklist
    assert out["by_language"]["xx"]["coverage"] == 0.0
