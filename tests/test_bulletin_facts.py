"""
Layer A — the Bulletin's deterministic record, over a real in-memory corpus.

The properties worth pinning are the ones a reader of the output cannot check:
that the window is genuinely half-open (so consecutive editions neither skip nor
double-count a day), that quarantined articles are excluded AND counted rather
than silently dropped, that every number is an exact count rather than the length
of a fetched page, and that a probe which cannot read reports so instead of
reporting zero.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin import facts
from src.bulletin.period import resolve_period
from src.database.models import Article, Base, Source

_END = date(2026, 8, 1)  # exclusive; the weekly period is 2026-07-25 .. 2026-07-31


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _source(s: Session, name: str, domain: str, **kw) -> Source:
    src = Source(name=name, domain=domain, **kw)
    s.add(src)
    s.flush()
    return src


def _article(
    s: Session,
    src: Source,
    day: str,
    *,
    lang: str | None = "en",
    quarantined: bool | None = False,
    published: bool = True,
    created: str | None = None,
    at: str = "12:00:00",
) -> Article:
    n = _article.counter = getattr(_article, "counter", 0) + 1
    when = datetime.fromisoformat(f"{day} {at}")
    art = Article(
        url=f"https://{src.domain}/a{n}",
        canonical_url=f"https://{src.domain}/a{n}",
        source_id=src.id,
        title=f"Article {n}",
        content="body text",
        hash=f"{n:064d}",
        language=lang,
        quarantined=quarantined,
        published_at=when if published else None,
        created_at=datetime.fromisoformat(f"{created} 12:00:00") if created else when,
    )
    s.add(art)
    s.flush()
    return art


def _corpus() -> Session:
    s = _session()
    a = _source(s, "Alpha", "alpha.test", country="fr", source_type="news")
    b = _source(s, "Beta", "beta.test", country="de", source_type="news")
    c = _source(s, "Gamma", "gamma.test", country=None, source_type="legal")

    # In period (2026-07-25 .. 2026-07-31), three days with ingest.
    for _ in range(4):
        _article(s, a, "2026-07-25")
    for _ in range(2):
        _article(s, b, "2026-07-27", lang="de")
    _article(s, c, "2026-07-31", lang=None)

    # Boundary rows: the day before the window, and the exclusive end day itself.
    _article(s, a, "2026-07-24")
    _article(s, a, "2026-08-01")

    # A quarantined article inside the period — excluded from every figure, counted.
    _article(s, b, "2026-07-26", quarantined=True)
    s.commit()
    return s


def _period():
    return resolve_period("weekly", end=_END)


# -- the window ------------------------------------------------------------- #


def test_the_window_is_half_open_on_both_ends():
    """The day before start and the exclusive end day are both outside. Getting
    this wrong makes consecutive editions overlap or leave a hole."""
    m = facts.masthead(_corpus(), _period())
    assert m["articles"] == 7, "4 + 2 + 1; the two boundary rows and the quarantined one are out"
    days = {d["day"] for d in m["articles_by_day"]}
    assert days == {"2026-07-25", "2026-07-27", "2026-07-31"}
    assert "2026-07-24" not in days and "2026-08-01" not in days


def test_the_exact_boundary_instants_decide_correctly():
    """The two rows that actually discriminate ``<`` from ``<=``.

    A fixture timestamped at noon cannot tell a half-open window from an inclusive
    one — both answer the same on every row that is not exactly midnight. So: one
    article at 00:00:00 on the START day (must be IN, the bound is inclusive) and
    one at 00:00:00 on the END day (must be OUT, the bound is exclusive). Without
    this pair the guard passes against a window that double-counts a boundary day
    in every consecutive edition.
    """
    s = _corpus()
    src = s.query(Source).filter_by(domain="alpha.test").one()
    nxt = resolve_period("weekly", end=date(2026, 8, 8))
    before = facts.masthead(s, nxt)["articles"]

    _article(s, src, "2026-07-25", at="00:00:00")
    _article(s, src, "2026-08-01", at="00:00:00")
    s.commit()

    assert facts.masthead(s, _period())["articles"] == 8, "start midnight in, end midnight out"
    # And the excluded one is not lost — it opens the NEXT period.
    assert facts.masthead(s, nxt)["articles"] == before + 1


def test_an_article_with_no_published_at_falls_back_to_created_at():
    """coalesce is the only convention that never silently drops an undated
    article — which is why it is the one with an index built for it."""
    s = _corpus()
    src = s.query(Source).filter_by(domain="alpha.test").one()
    _article(s, src, "2026-07-28", published=False, created="2026-07-28")
    s.commit()
    m = facts.masthead(s, _period())
    assert m["articles"] == 8
    assert "2026-07-28" in {d["day"] for d in m["articles_by_day"]}


def test_consecutive_periods_partition_the_articles_exactly():
    s = _corpus()
    p = _period()
    this = facts.masthead(s, p)["articles"]
    prev = facts.masthead(s, p.preceding())["articles"]
    assert this == 7 and prev == 1, "the 07-24 row belongs to the previous period, and only it"


# -- quarantine ------------------------------------------------------------- #


def test_quarantined_articles_are_excluded_from_every_figure():
    s = _corpus()
    m = facts.masthead(s, _period())
    beta = next(r for r in m["languages"] if r["language"] == "de")
    assert beta["articles"] == 2, "the quarantined de article is not counted"
    assert sum(r["articles"] for r in m["languages"]) == m["articles"]


def test_the_excluded_quarantined_set_is_counted_not_silently_dropped():
    """An excluded set is not an empty one — a withheld article that is never
    mentioned reads as an absence of events."""
    d = facts.disclosures(_corpus(), _period())
    assert d["quarantined_in_period"] == 1


def test_a_never_judged_article_is_not_treated_as_quarantined():
    """quarantined=NULL predates the column and means "never judged"; treating it
    as quarantined would delete most of an older corpus from every edition."""
    s = _corpus()
    src = s.query(Source).filter_by(domain="alpha.test").one()
    _article(s, src, "2026-07-29", quarantined=None)
    s.commit()
    assert facts.masthead(s, _period())["articles"] == 8


# -- the masthead: the lens, stated ----------------------------------------- #


def test_the_masthead_names_the_sources_that_actually_contributed():
    m = facts.masthead(_corpus(), _period())
    assert m["sources_contributing"] == 3
    assert m["top_sources"][0]["domain"] == "alpha.test"
    assert m["top_sources"][0]["articles"] == 4
    assert m["top_sources"][0]["share"] == round(4 / 7, 4)


def test_concentration_is_an_exact_proportion_with_a_denominator():
    m = facts.masthead(_corpus(), _period())
    assert m["top_3_share"] == 1.0, "three sources, so the top three are all of them"


def test_every_share_in_the_masthead_uses_the_same_denominator():
    """Two shares in one block computed over two totals is the kind of quiet
    inconsistency nobody spots by reading the output."""
    m = facts.masthead(_corpus(), _period())
    assert m["top_3_share"] == round(sum(t["share"] for t in m["top_sources"]), 4)


def test_an_untagged_language_gets_its_own_bucket_never_a_guess():
    m = facts.masthead(_corpus(), _period())
    assert m["language_unknown_articles"] == 1
    assert any(r["language"] is None for r in m["languages"])


def test_the_country_split_is_the_sources_and_unlocated_is_reported():
    m = facts.masthead(_corpus(), _period())
    assert {r["country"] for r in m["source_countries"]} == {"fr", "de"}
    assert m["source_unlocated_articles"] == 1, "Gamma has no country — reported, not dropped"
    assert "never a place the text is about" in m["method"]


def test_channels_come_from_the_source_type():
    m = facts.masthead(_corpus(), _period())
    assert {r["source_type"]: r["articles"] for r in m["channels"]} == {"news": 6, "legal": 1}


def test_days_with_ingest_is_reported_against_the_periods_own_length():
    m = facts.masthead(_corpus(), _period())
    assert (m["days_with_ingest"], m["period_days"]) == (3, 7)


def test_the_corpus_total_is_the_whole_archive_not_the_period():
    """The period's share of the corpus is the counterweight to a document that
    otherwise reads as if the period were everything."""
    m = facts.masthead(_corpus(), _period())
    assert m["corpus_articles"] == 9, "10 rows, one quarantined"
    assert m["corpus_share"] == round(7 / 9, 6)


def test_counts_are_exact_not_the_length_of_a_fetched_page():
    """A cap may bound examples; it must never bound a reported number."""
    s = _session()
    src = _source(s, "Flood", "flood.test", country="fr")
    for _ in range(250):
        _article(s, src, "2026-07-26")
    s.commit()
    m = facts.masthead(s, _period())
    assert m["articles"] == 250
    assert len(m["top_sources"]) == 1, "the EXAMPLE list is bounded, the count is not"


# -- disclosures ------------------------------------------------------------ #


def test_undated_mentions_are_counted_because_no_window_can_see_them():
    from src.database.models import Keyword, KeywordMention

    s = _corpus()
    k = Keyword(term="x", normalized_term="x")
    s.add(k)
    s.flush()
    s.add(KeywordMention(keyword_id=k.id, article_id=1, count=1, observed_on=None))
    s.add(KeywordMention(keyword_id=k.id, article_id=2, count=1, observed_on=date(2026, 7, 25)))
    s.commit()
    assert facts.disclosures(s, _period())["mentions_without_a_date"] == 1


def test_a_failing_probe_reports_none_with_its_error_never_zero(monkeypatch):
    """"Could not read" and "there were none" must not render the same — that is
    the whole point of the re-index backlog's own three-state contract."""
    monkeypatch.setattr(
        facts,
        "_corpus_earliest",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("range unreadable")),
    )
    d = facts.disclosures(_corpus(), _period())
    assert d["baseline_coverage"]["complete"] is None
    assert "range unreadable" in d["baseline_coverage"]["error"]
    assert d["quarantined_in_period"] == 1, "the other probes still reported"


def test_the_reindex_backlog_rides_the_disclosures():
    """Articles awaiting re-index carry no keywords, so they are structurally
    invisible to every keyword figure in the edition."""
    d = facts.disclosures(_corpus(), _period())
    assert "reindex_backlog" in d
    assert "available" in d["reindex_backlog"]


def test_the_baseline_shortfall_is_disclosed_on_a_young_corpus():
    d = facts.disclosures(_corpus(), resolve_period("yearly", end=_END))
    assert d["baseline_coverage"]["complete"] is False


# -- assembly --------------------------------------------------------------- #


def test_layer_a_is_model_free_and_declares_each_sections_real_window():
    """§12: a monthly edition showing a 14-day number must be VISIBLE in the
    output rather than hidden."""
    out = facts.layer_a(_corpus(), _period())
    assert out["layer"] == "A"
    assert out["period"]["days"] == 7
    rising = next(s for s in out["sections"] if s["section"] == "rising_concepts")
    assert rising["window"]["days"] == 7
    assert rising["window"]["baseline_days"] == 30
    assert "No model" in out["method"]


def test_the_rising_section_is_anchored_to_the_period_not_to_today():
    """Anchoring to today would make an edition answer a different question every
    time it is re-rendered, and would make a closed period unaskable."""
    out = facts.layer_a(_corpus(), _period())
    rising = next(s for s in out["sections"] if s["section"] == "rising_concepts")
    assert rising["window"]["end"] == "2026-08-01"
    assert rising["window"]["matches_period"] is True


def test_the_declared_window_is_read_back_not_asserted(monkeypatch):
    """§12 exists so a section showing a window that does not match its cadence is
    VISIBLE. A `matches_period` hardcoded True would report the section's intent
    rather than its behaviour, which is the blind spot itself."""
    import src.analytics.queries as q

    monkeypatch.setattr(
        q, "trending", lambda *_a, **_k: {"terms": [], "window_days": 14, "baseline_days": 30}
    )
    out = facts.rising_concepts(_corpus(), _period())
    assert out["window"]["matches_period"] is False
    assert out["window"]["days"] == 7, "the period's own window is still declared"


def test_one_failing_section_does_not_lose_the_edition(monkeypatch):
    monkeypatch.setattr(
        facts,
        "rising_concepts",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("trending exploded")),
    )
    out = facts.layer_a(_corpus(), _period())
    assert out["masthead"]["articles"] == 7
    assert "trending exploded" in out["sections"][0]["error"]


def test_no_score_shaped_field_anywhere_in_the_payload():
    out = facts.layer_a(_corpus(), _period())
    flat = json.dumps(out, default=str).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat


# -- the preview endpoint --------------------------------------------------- #


def _open_gate(monkeypatch) -> None:
    import src.bulletin.gate as gate

    monkeypatch.setattr(
        gate,
        "bulletin_available",
        lambda **_k: {"available": True, "reason": "test", "overridden": False, "warnings": []},
    )


def _freeze_today(monkeypatch) -> None:
    """Pin the endpoint's clock to the fixture's window.

    The endpoint takes no ``end``: ``resolve_period`` falls back to
    ``date.today()`` (src/bulletin/period.py). Every other test here passes
    ``end=_END`` through ``_period()``, so only this one read the REAL clock --
    and once the calendar moved past the fixture's July dates the resolved
    window stopped containing all three sources and the assertion below started
    failing on an unchanged tree (observed 2026-08-04: the window resolved to
    2026-07-28..2026-08-04, holding only Alpha's 08-01 and Gamma's 07-31, so
    ``sources_contributing`` was 2). That is the standing "never compare a
    hardcoded fixture against a real-now marker" lesson; freezing the clock
    keeps the assertion meaningful instead of weakening it to match the drift.
    """
    import src.bulletin.period as period

    class _FrozenDate(date):
        @classmethod
        def today(cls) -> date:
            return _END

    monkeypatch.setattr(period, "date", _FrozenDate)


def test_the_preview_endpoint_returns_layer_a_for_a_closed_period(monkeypatch):
    import src.api.diagnostics as diag

    _open_gate(monkeypatch)
    _freeze_today(monkeypatch)
    body = json.loads(diag.bulletin_preview(cadence="weekly", download=False, db=_corpus()).body)
    assert body["available"] is True
    assert body["layer"] == "A"
    assert body["masthead"]["sources_contributing"] == 3
    assert body["period"]["end_is_exclusive"] is True


def test_an_incapable_machine_gets_the_refusal_and_no_figures(monkeypatch):
    """The feature is gated as a whole, not merely its narration layer — so the
    refusal must not ship a masthead alongside it."""
    import src.api.diagnostics as diag
    import src.bulletin.gate as gate

    monkeypatch.setattr(
        gate,
        "bulletin_available",
        lambda **_k: {"available": False, "reason": "no accelerator", "warnings": []},
    )
    body = json.loads(diag.bulletin_preview(cadence="weekly", download=False, db=_corpus()).body)
    assert body["available"] is False
    assert "masthead" not in body
    assert "no accelerator" in body["gate"]["reason"]


def test_an_unknown_cadence_is_a_400_not_a_silently_rounded_period(monkeypatch):
    import src.api.diagnostics as diag
    from fastapi import HTTPException

    _open_gate(monkeypatch)
    try:
        diag.bulletin_preview(cadence="hourly", download=False, db=_corpus())
    except HTTPException as exc:
        assert exc.status_code == 400 and "cadence" in exc.detail
    else:
        raise AssertionError("an unknown cadence must be refused, never rounded to a known one")


def test_the_preview_is_a_bundle_member_and_the_ratchet_knows_it():
    """A GET diagnostic must be a bundle member or carry a stated exemption. This
    one is a member: its masthead IS corpus-health evidence."""
    from src.api.diagnostics import _DIAG_COVERAGE_MAP

    assert _DIAG_COVERAGE_MAP["/bulletin-preview"] == "bulletin-weekly.json"


def test_the_clock_expression_matches_the_index_definition_byte_for_byte():
    """SQLite matches an expression index ONLY when the query expression is
    written identically. Written any other way this becomes a bare SCAN articles,
    dragging every ~35 KB row through the SQLCipher codec."""
    from pathlib import Path

    from src.database.maintenance import HOT_INDEXES

    assert "coalesce(published_at, created_at)" in HOT_INDEXES["ix_article_observed"]
    src = Path("src/bulletin/facts.py").read_text(encoding="utf-8")
    assert "_CLOCK = func.coalesce(Article.published_at, Article.created_at)" in src
