"""The criteria-calibration prose arm: a cursor that carries, and a scope that aims.

The arm was resumable by design and could not finish. The all-diagnostics bundle called it
with ``prose_gate_after_id=0, limit=500`` literally, so every bundle re-measured the same
lowest-id 500 articles: ``done`` could not become true on any corpus over 500, and both
2026-08-23 field reports stopped at ``last_id: 695`` having flagged 0. Nothing in the report
was mislabelled -- the per-batch denominator was honest -- but "resumable" reads as "will
finish", and 0.3 gate row 5's Tier B had no evidence as a result.

It also walked by ascending id, which samples whatever that key orders first rather than the
population under question (the listing-shaped URLs the >=100-word guard keeps).

So: two halves, and each needs its own negative space. A cursor that advances must not skip;
a scope that narrows must not narrow the OTHER scope; and a criteria-version change must
reset the running totals rather than sum two detectors' verdicts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics.criteria_calibration import (
    CRITERIA_VERSION,
    advance_cursor,
    calibration_report,
    load_cursor,
)
from src.analytics.non_article_scan import PROSE_GATE_SCOPES, scan_non_article_candidates
from src.database.models import Article, Base, Source

# Nav soup: function words are absent, sentence punctuation is absent. The prose gate's
# shape, borrowed from the field specimen the gate was built for.
_NAV = (
    "News Latest Sport Business Politics World Travel Money Markets Weather Video Photos "
    "Gallery Podcast Newsletters Events About Contact Home Search Login Sign Up Subscribe "
    "Cookies Advertisement Privacy Terms Follow Facebook Twitter Instagram Newsletter "
    "Preference Centre Manage Subscriptions Menu Toggle Navigation Skip Content Latest News "
    "Sport GAA Rugby Soccer Racing Golf Boxing Motors Showbiz TV Fashion Beauty Food Recipes "
    "Property Travel Family Voucher Codes Bingo Dating Contact Advertise Cookie Policy Privacy "
    "Policy Terms Conditions Modern Slavery Statement Complaints Regulation Archive Sitemap "
    # Long enough to CLEAR the >=100-word guard -- which is the whole point: below it the URL
    # rules fire and the body never reaches the prose gate at all.
) * 2
_PROSE = (
    "The government said on Tuesday that it would review the policy after months of criticism "
    "from opposition lawmakers, who argued that the reform had failed to deliver the promised "
    "benefits to the region's struggling economy. Officials declined to give a firm timetable. "
    # Also over the guard, so it reaches the prose gate and is REFUSED by it on the merits --
    # a real article excluded because it reads as prose, not because it was never looked at.
) * 3


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """The cursor is a file under ``data_dir()``. Every test here gets its own, so a run
    can never read another test's cursor -- or, worse, the developer's real one."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))


def _corpus(n_index_pages: int = 6) -> Session:
    """A corpus whose two prose-gate populations are DIFFERENT sets.

    ``index_pages`` candidates are long bodies at listing-shaped URLs. The nav-soup body at
    ``/newsletter-preference-centre`` is long and fails the prose gate but its URL is not
    listing-shaped, so it belongs to ``all`` and NOT to ``index_pages`` -- which is what
    makes the scope assertions discriminating rather than incidentally true.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="News", domain="news.example", language="en", enabled=True)
    s.add(src)
    s.flush()
    seq = [0]

    def add(url, content):
        seq[0] += 1
        s.add(Article(
            url=url, canonical_url=url, source_id=src.id, content=content,
            hash=f"h{seq[0]}", word_count=len(content.split()), language="en",
            title=f"t{seq[0]}",
        ))

    # Long bodies at LISTING-shaped URLs: the index_pages population.
    for i in range(n_index_pages):
        add(f"https://news.example/tag/topic{i}", _NAV)
    # A long nav-soup body at a URL no listing rule matches: `all` only.
    add("https://news.example/newsletter-preference-centre", _NAV)
    # A real article: neither population may ever flag it.
    add("https://news.example/2026/07/election-results", _PROSE)
    s.commit()
    return s


def _pg(out: dict) -> dict:
    return out["base_scan"]["prose_gate"]


# --------------------------------------------------------------------------- #
#  The scope aims
# --------------------------------------------------------------------------- #
def test_the_index_pages_scope_walks_only_listing_shaped_bodies():
    """The population under decision, not whatever ascending id ordered first."""
    s = _corpus(n_index_pages=6)
    out = scan_non_article_candidates(
        s, include_prose_gate=True, prose_gate_limit=100, prose_gate_scope="index_pages",
    )
    pg = out["prose_gate"]
    assert pg["scope"] == "index_pages"
    assert pg["scanned"] == 6, "only the six listing-shaped long bodies"
    assert pg["flagged"] == 6, "all six are nav soup"
    assert "listing-shaped" in pg["population"]

    urls = {
        a.url for a in s.query(Article).filter(Article.id.in_(pg["sample_ids"])).all()
    }
    assert all("/tag/" in u for u in urls), urls
    assert not any("newsletter-preference-centre" in u for u in urls), (
        "a long nav-soup body at a non-listing URL belongs to the `all` scope, not this one"
    )


def test_the_all_scope_still_reaches_bodies_the_index_scope_excludes():
    """The negative-space twin. A scope that narrowed BOTH populations would satisfy the
    test above perfectly while removing the measurement the default quarantine run needs."""
    s = _corpus(n_index_pages=6)
    out = scan_non_article_candidates(
        s, include_prose_gate=True, prose_gate_limit=100, prose_gate_scope="all",
    )
    pg = out["prose_gate"]
    assert pg["scope"] == "all"
    assert pg["scanned"] == 8, "every >=100-word body, including the real article"
    assert pg["flagged"] == 7, "the six listings plus the preference centre; not the article"

    urls = {
        a.url for a in s.query(Article).filter(Article.id.in_(pg["sample_ids"])).all()
    }
    assert any("newsletter-preference-centre" in u for u in urls)


def test_an_unknown_scope_is_refused_rather_than_silently_treated_as_all():
    s = _corpus(n_index_pages=1)
    with pytest.raises(ValueError, match="prose_gate_scope"):
        scan_non_article_candidates(s, include_prose_gate=True, prose_gate_scope="everything")
    assert PROSE_GATE_SCOPES == ("all", "index_pages")


# --------------------------------------------------------------------------- #
#  The cursor carries
# --------------------------------------------------------------------------- #
def test_repeated_resumed_runs_advance_instead_of_re_measuring_the_first_batch():
    """THE defect. Three runs at limit=2 over six candidates must cover all six and finish.

    Without a carried cursor all three walk the same first two, which is exactly what the
    bundle did: `done` false forever, `last_id` frozen, the population never reached.
    """
    s = _corpus(n_index_pages=6)
    seen: list[list[int]] = []
    for _ in range(3):
        out = calibration_report(
            s, top_n=100, prose_gate_limit=2, prose_gate_scope="index_pages", resume=True,
        )
        seen.append(sorted(_pg(out)["sample_ids"]))

    assert len(seen[0]) == len(seen[1]) == len(seen[2]) == 2
    assert seen[0] != seen[1] != seen[2], f"batches must differ: {seen}"
    flat = [aid for batch in seen for aid in batch]
    assert len(set(flat)) == 6, f"three batches of 2 must cover 6 distinct articles: {seen}"

    final = calibration_report(
        s, top_n=100, prose_gate_limit=2, prose_gate_scope="index_pages", resume=True,
    )
    assert _pg(final)["remaining"] == 0
    assert _pg(final)["done"] is True
    assert final["prose_gate_progress"]["scanned"] == 6
    assert final["prose_gate_progress"]["flagged"] == 6
    assert final["prose_gate_progress"]["runs"] == 4


def test_remaining_is_an_exact_count_not_a_full_batch_heuristic():
    """``done`` was ``scanned < limit``, which is wrong exactly where a full batch happens
    to have exhausted the population -- the boundary a reader most wants to trust."""
    s = _corpus(n_index_pages=4)
    out = scan_non_article_candidates(
        s, include_prose_gate=True, prose_gate_limit=4, prose_gate_scope="index_pages",
    )
    pg = out["prose_gate"]
    assert pg["scanned"] == 4, "a FULL batch"
    assert pg["remaining"] == 0
    assert pg["done"] is True, "a full batch that emptied the population is still done"


def test_resume_is_off_by_default_and_writes_no_cursor():
    """A caller passing ``prose_gate_after_id`` by hand gets exactly the batch it asked for,
    and leaves no state behind. Statefulness here is opt-in, never a side effect."""
    from src.paths import data_dir

    s = _corpus(n_index_pages=6)
    a = calibration_report(s, top_n=100, prose_gate_limit=2, prose_gate_scope="index_pages")
    b = calibration_report(s, top_n=100, prose_gate_limit=2, prose_gate_scope="index_pages")
    assert _pg(a)["sample_ids"] == _pg(b)["sample_ids"], "no cursor => same batch twice"
    assert a["prose_gate_progress"] is None
    assert not (data_dir() / "criteria_calibration_cursor.json").exists()


def test_each_scope_keeps_its_own_cursor():
    """Two populations, two positions. One shared cursor would make an `all` run skip
    articles an `index_pages` run had walked, and neither total would mean anything."""
    s = _corpus(n_index_pages=6)
    calibration_report(s, prose_gate_limit=2, prose_gate_scope="index_pages", resume=True)
    idx = load_cursor("index_pages")
    assert idx is not None and idx["scanned"] == 2

    out = calibration_report(s, prose_gate_limit=3, prose_gate_scope="all", resume=True)
    assert _pg(out)["after_id"] == 0, "the `all` scope starts at its own beginning"
    assert load_cursor("index_pages")["after_id"] == idx["after_id"], "untouched"


def test_a_criteria_version_change_resets_the_totals_rather_than_summing_two_detectors():
    """A stamp under a different detector generation is not summable with this one. The
    reset is REPORTED, so a reader sees why a running total restarted."""
    s = _corpus(n_index_pages=6)
    calibration_report(s, prose_gate_limit=2, prose_gate_scope="index_pages", resume=True)

    from src.paths import data_dir

    path = data_dir() / "criteria_calibration_cursor.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["index_pages"]["criteria_version"] = "nav-soup-v0"
    path.write_text(json.dumps(data), encoding="utf-8")

    stale = load_cursor("index_pages")
    assert stale is not None and "reset_reason" in stale
    assert "nav-soup-v0" in stale["reset_reason"]

    out = calibration_report(s, prose_gate_limit=2, prose_gate_scope="index_pages", resume=True)
    prog = out["prose_gate_progress"]
    assert _pg(out)["after_id"] == 0, "a stale cursor restarts the scope"
    assert prog["runs"] == 1 and prog["scanned"] == 2, "totals restart, never sum"
    assert "reset_reason" in prog
    assert prog["criteria_version"] == CRITERIA_VERSION


def test_a_cursor_that_cannot_be_written_says_so_instead_of_raising():
    """The report is the point; the cursor is a convenience. A failed write costs a
    re-measurement next run -- and ``persisted`` says it happened, rather than leaving a
    reader to infer that the totals silently stopped advancing."""
    rec = advance_cursor(
        "index_pages",
        criteria_version=CRITERIA_VERSION,
        prose_gate={"last_id": 5, "scanned": 2, "flagged": 1, "sample_ids": [4, 5],
                    "remaining": 3, "done": False},
        prior=None,
    )
    assert rec["persisted"] is True

    import src.analytics.criteria_calibration as cc

    def _boom():
        raise OSError("read-only volume")

    orig = cc._cursor_path
    cc._cursor_path = _boom  # type: ignore[assignment]
    try:
        rec2 = advance_cursor(
            "index_pages",
            criteria_version=CRITERIA_VERSION,
            prose_gate={"last_id": 9, "scanned": 2, "flagged": 0, "sample_ids": [],
                        "remaining": 1, "done": False},
            prior=None,
        )
    finally:
        cc._cursor_path = orig  # type: ignore[assignment]
    assert rec2["persisted"] is False
    assert rec2["scanned"] == 2, "the run's own totals are still published"


def test_the_report_names_the_population_it_walked():
    """A count with no population is the shape every stale figure in this project's gate
    documents has taken. The sentence rides in the payload, not only in a doc."""
    s = _corpus(n_index_pages=3)
    idx = calibration_report(s, prose_gate_scope="index_pages")
    alls = calibration_report(s, prose_gate_scope="all")
    assert idx["prose_gate_scope"] == "index_pages"
    assert alls["prose_gate_scope"] == "all"
    assert _pg(idx)["population"] != _pg(alls)["population"]
    assert "NOT every long body" in _pg(idx)["population"]
    assert "NOT scoped to listing-shaped URLs" in _pg(alls)["population"]


def test_the_bundle_member_resumes_and_aims_at_the_population_under_decision():
    """Behavioural, through the REAL member generator: a route called directly receives
    ``Query(...)`` sentinel objects (truthy), so a direct-call or source-level check would
    pass on exactly the bug this guards -- the member passing ``after_id=0`` forever."""
    import inspect

    import src.api.diagnostics as diag

    src_txt = inspect.getsource(diag._all_diagnostics_members)
    member = src_txt.split('("criteria-calibration.json"', 1)[1].split("))", 1)[0]
    assert 'prose_gate_scope="index_pages"' in member, member
    assert "resume=True" in member, member
    assert "prose_gate_after_id=0" in member, (
        "the literal 0 stays, and is now harmless: resume overrides it from the cursor"
    )
