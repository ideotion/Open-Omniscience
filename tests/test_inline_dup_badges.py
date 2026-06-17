"""
Inline "1 voice" near-dup badges on article rows (PR 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled: surface the near-identical-copies finding INLINE in article lists
so echo is never mistaken for independent corroboration. The analysis Articles
subtab badges clustered rows (≈N) via a reusable, non-blocking helper that reuses
the Related subtab's coordination data. Browser-unverified -> static guard.
"""

from __future__ import annotations

from pathlib import Path

_JS = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(encoding="utf-8")


def test_badge_helper_exists_and_is_wired_into_the_articles_list():
    assert "function annotateArticleDups(" in _JS, "the reusable inline-badge helper must exist"
    assert "annotateArticleDups(p, arts)" in _JS, "the Articles subtab must call the badge helper"
    assert "annotateArticleDups(p, t)" in _JS, "the search-results list must reuse the badge helper"
    # non-blocking + best-effort + idempotent per row
    assert "a.dataset.dupBadged" in _JS, "rows must not be double-badged"


def test_badge_reuses_coordination_data_no_score():
    # Reuses corpus-coordination (and the Related cache when present) — no new backend,
    # no score; the count is the cluster size only.
    assert "/api/insights/corpus-coordination" in _JS
    assert "_anRelatedClusters" in _JS, "the helper should reuse the Related subtab cache when present"
    assert "article_ids" in _JS


def test_badge_states_one_voice_honestly():
    assert "effectively one voice" in _JS, "the per-row badge must state it is one voice"
    assert "fewer independent voices than the count suggests" in _JS, (
        "the list summary must warn that near-dups inflate the apparent count"
    )
