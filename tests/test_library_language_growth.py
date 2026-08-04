"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

The per-language corpus-growth feed (``snapshots.article_counts_by_language`` +
``GET /api/library/languages``).

WHY IT EXISTS. ``language_equilibrium`` is a live scheduler lever on a strongly
non-Anglophone corpus, and the operator tuning it had NO feedback surface: nothing
in the app answered "which languages is my corpus actually growing in". This is
that answer, derived live from ``Article.created_at`` so it is retroactive.

WHAT THESE TESTS PIN is mostly not the arithmetic -- it is the honesty of the
shape, and every claim comes with its negative-space twin:

  * one language, one bucket key (the lever's key) -- AND genuinely distinct
    languages still separate, because an over-eager key merges silently: the
    counts still sum, so nothing looks wrong;
  * an asserted language and a deduced one are never pooled -- AND the deduced
    ones are still counted somewhere, so the blind spot has a size;
  * a bucket where a language got nothing is a MEASURED ZERO and is drawn --
    AND a bucket before the corpus existed was never measured, so it is absent
    rather than a fabricated zero;
  * a ranked-out language is disclosed in ``other`` -- AND nothing is disclosed
    when nothing was ranked out, since an over-eager disclosure invents
    missing data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.database.snapshots import article_counts_by_language

_NOW = datetime(2027, 5, 20, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db():
    """A private corpus, containing only what the test in front of you seeded.

    The first version of this fixture used the shared session DB and scoped each
    test to a window opening just after the newest stored row. That isolates
    nothing, because the window runs BACKWARDS from ``now``: it swept back over a
    whole day of every other test's articles. It passed when the file ran alone
    and went red in CI with English and French panels no fixture here ever seeded
    -- the recorded rule (never assert counts against the shared ``SessionLocal``)
    wearing its other face, since the danger is being polluted as much as
    polluting.
    """
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _source(db) -> Source:
    src = Source(name=f"S {uuid.uuid4().hex[:6]}", domain=f"h-{uuid.uuid4().hex[:8]}.example")
    db.add(src)
    db.flush()
    return src


def _articles(db, src, *, lang, detected=None, at, n=1):
    for i in range(n):
        url = f"https://x.example/{uuid.uuid4().hex}"
        db.add(
            Article(
                source_id=src.id,
                url=url,
                canonical_url=url,
                hash=uuid.uuid4().hex,
                title="t",
                content="body",
                language=lang,
                detected_language=detected,
                created_at=at.replace(tzinfo=None) + timedelta(seconds=i),
            )
        )
    db.flush()


def _by_lang(out) -> dict[str, int]:
    return {s["language"]: s["total"] for s in out["series"]}


# --------------------------------------------------------------------------- #
#  One language, one key -- and not one key too many
# --------------------------------------------------------------------------- #
def test_region_subtags_are_one_language(db):
    """``Article.language`` is stored RAW from trafilatura's <html lang> read, so
    most major outlets arrive region-tagged. The equilibrium lever folds them; a
    feed that did not would show English split across three panels while the lever
    steered one."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="en", at=base, n=3)
    _articles(db, src, lang="en-US", at=base + timedelta(minutes=5), n=2)
    _articles(db, src, lang="EN_gb", at=base + timedelta(minutes=10), n=1)

    out = article_counts_by_language(db, days=1, now=base + timedelta(hours=1))
    assert _by_lang(out)["en"] == 6, "three spellings of English are one language"
    assert "en-US" not in _by_lang(out) and "en_gb" not in _by_lang(out)


def test_but_genuinely_distinct_languages_never_merge(db):
    """The twin. An over-eager key is the same defect pointing the other way and is
    INVISIBLE -- the totals still add up."""
    base = _NOW
    src = _source(db)
    for code in ("en", "eo", "es", "et"):
        _articles(db, src, lang=code, at=base, n=2)

    got = _by_lang(article_counts_by_language(db, days=1, now=base + timedelta(hours=1)))
    for code in ("en", "eo", "es", "et"):
        assert got.get(code) == 2, f"{code} must stay its own language, got {got}"


def test_the_feed_and_the_lever_bucket_a_language_the_same_way(db):
    """The cross-module property this feed exists to serve. Two modules publishing
    the same quantity under different bucket keys is the recorded defect class;
    here the feed's whole purpose is to show the operator what the lever sees, so a
    disagreement would make it worse than nothing."""
    from src.scheduler.equilibrium import corpus_language_shares

    base = _NOW
    src = _source(db)
    _articles(db, src, lang="fr", at=base, n=4)
    _articles(db, src, lang="fr-CA", at=base + timedelta(minutes=1), n=2)

    feed = _by_lang(article_counts_by_language(db, days=1, now=base + timedelta(hours=1)))
    shares = corpus_language_shares(db)
    assert "fr" in feed and "fr" in shares
    assert "fr-CA" not in feed and "fr-CA" not in shares
    assert "fr-ca" not in feed and "fr-ca" not in shares


# --------------------------------------------------------------------------- #
#  Asserted is not deduced
# --------------------------------------------------------------------------- #
def test_a_deduced_language_is_never_pooled_into_the_series(db):
    """``coalesce(language, detected_language)`` would make this feed disagree with
    the lever AND give a deduced value an asserted one's visual weight."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="de", at=base, n=2)
    _articles(db, src, lang=None, detected="de", at=base + timedelta(minutes=1), n=5)

    out = article_counts_by_language(db, days=1, now=base + timedelta(hours=1))
    assert _by_lang(out)["de"] == 2, "only the asserted German may be plotted as German"


def test_but_the_unassigned_are_counted_so_the_blind_spot_has_a_size(db):
    """The twin: excluded from the panels is not excluded from the payload. The
    number is load-bearing -- the equilibrium lever cannot see those articles
    either, so this IS the size of its blind spot."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="de", at=base, n=2)
    _articles(db, src, lang=None, detected="de", at=base + timedelta(minutes=1), n=5)
    _articles(db, src, lang=None, detected=None, at=base + timedelta(minutes=2), n=3)

    out = article_counts_by_language(db, days=1, now=base + timedelta(hours=1))
    assert out["unassigned"]["articles"] == 8
    assert out["unassigned"]["with_deduced_language"] == 5


# --------------------------------------------------------------------------- #
#  A measured zero is drawn; an unmeasured bucket is not invented
# --------------------------------------------------------------------------- #
def test_a_quiet_bucket_is_a_real_zero_and_keeps_the_axis_true(db):
    """An omit-the-empties series compresses the axis: hour 1 and hour 5 render
    adjacent, so a gap in coverage reads as continuous activity. Here the count is
    genuinely 0 -- the language was measured and got nothing -- so it is emitted."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="it", at=base, n=1)
    _articles(db, src, lang="it", at=base + timedelta(hours=4), n=1)

    out = article_counts_by_language(db, days=1, now=base + timedelta(hours=4))
    pts = next(s for s in out["series"] if s["language"] == "it")["points"]
    ts = [p["t"] for p in pts]
    assert len(set(ts)) == len(ts), "buckets must not repeat"
    tail = pts[-5:]
    assert [p["n"] for p in tail] == [1, 0, 0, 0, 1], f"the three quiet hours are zeros: {tail}"


def test_the_series_never_starts_before_the_corpus_did(db):
    """The counter-rule. Zero-filling back through a 30-day window on a corpus that
    is hours old would publish weeks of "we measured and got nothing" for a period
    in which nothing was measuring."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="pt", at=base, n=1)

    out = article_counts_by_language(db, days=3650, now=base + timedelta(hours=1))
    assert out["corpus_began_at"] is not None
    began = datetime.fromisoformat(out["begins_at"])
    assert began >= datetime.fromisoformat(out["corpus_began_at"]).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # A ten-year window over a corpus that is not ten years old must not emit ten
    # years of points.
    assert len(out["series"][0]["points"]) < 3650
    # And it SAYS so, so the UI never has to re-derive the clamp from two
    # timestamps and get the bucket arithmetic subtly wrong.
    assert out["clamped_to_corpus_start"] is True


def test_a_window_inside_the_corpus_is_not_reported_as_clamped(db):
    """The twin: an unconditional "the corpus begins here" note would explain a
    late start that is not happening, on every ordinary short window.

    Needs a corpus OLDER than the window, hence the article seeded well in the
    past: this fixture's corpus is born empty, so a 1-day window over articles
    stored only at ``base`` really would begin before the corpus and really would
    be clamped -- the assertion would pass for the wrong reason.
    """
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="pt", at=base - timedelta(days=40), n=1)
    _articles(db, src, lang="pt", at=base, n=1)

    out = article_counts_by_language(db, days=1, now=base + timedelta(hours=1))
    assert out["clamped_to_corpus_start"] is False


def test_every_counted_article_has_a_slot_to_be_drawn_in(db):
    """A panel's stated total and its drawn bars must be the same number.

    They diverge if the axis stops at ``now`` while an article carries a created_at
    ahead of the clock -- skew, or a corpus restored from a machine that was ahead.
    The article is counted (it is inside the window) and then has no bucket on the
    axis, so the panel silently claims more than its bars add up to.
    """
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="fi", at=base, n=2)
    _articles(db, src, lang="fi", at=base + timedelta(hours=3), n=1)  # "ahead of the clock"

    out = article_counts_by_language(db, days=1, now=base + timedelta(minutes=1))
    panel = next(s for s in out["series"] if s["language"] == "fi")
    assert sum(p["n"] for p in panel["points"]) == panel["total"] == 3


def test_the_bucket_is_named_so_a_point_can_be_read(db):
    """Binning is permitted when labelled; downsampling is not. Every article in
    the window is still counted, in one bin or another -- the payload just has to
    say which bin."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="nl", at=base, n=1)
    assert article_counts_by_language(db, days=1, now=base)["bucket"] == "hour"
    assert article_counts_by_language(db, days=90, now=base)["bucket"] == "day"


# --------------------------------------------------------------------------- #
#  Ranked out is not dropped
# --------------------------------------------------------------------------- #
def test_a_ranked_out_language_is_disclosed_never_silently_dropped(db):
    base = _NOW
    src = _source(db)
    # Six languages, descending volume, asking for the top two.
    for i, code in enumerate(["aa", "ab", "ae", "af", "ak", "am"]):
        _articles(db, src, lang=code, at=base + timedelta(minutes=i), n=6 - i)

    out = article_counts_by_language(db, days=1, top_n=2, now=base + timedelta(hours=1))
    assert [s["language"] for s in out["series"]] == ["aa", "ab"]
    assert out["other"]["languages"] == 4
    assert out["other"]["articles"] == 3 + 2 + 1 + 4  # ae+af+ak+am


def test_and_nothing_is_disclosed_when_nothing_was_ranked_out(db):
    """The twin: an over-eager disclosure invents missing data."""
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="sv", at=base, n=2)

    out = article_counts_by_language(db, days=1, top_n=12, now=base + timedelta(hours=1))
    assert out["other"] == {"languages": 0, "articles": 0}


def test_every_article_in_the_window_lands_in_exactly_one_published_figure(db):
    """The conservation property, and the reason any single figure can be trusted.

    A reader looking at twelve panels has no way to tell a language that was ranked
    out from one that was quietly dropped. So the drawn totals, the ranked-out tail,
    the un-tagged articles and the un-bucketable ones must ADD UP to the window's
    real count -- a claim that survives every future change to how the rows are
    folded, which no per-figure assertion does.
    """
    from sqlalchemy import func as sa_func

    base = _NOW
    src = _source(db)
    _articles(db, src, lang="en", at=base, n=5)
    _articles(db, src, lang="en-GB", at=base + timedelta(minutes=1), n=2)
    _articles(db, src, lang="fr", at=base + timedelta(minutes=2), n=3)
    _articles(db, src, lang="de", at=base + timedelta(minutes=3), n=1)
    _articles(db, src, lang=None, detected="es", at=base + timedelta(minutes=4), n=4)
    _articles(db, src, lang=None, at=base + timedelta(minutes=5), n=2)

    now = base + timedelta(hours=1)
    out = article_counts_by_language(db, days=1, top_n=2, now=now)
    since = datetime.fromisoformat(out["begins_at"])
    real = int(
        db.query(sa_func.count(Article.id))
        .filter(Article.created_at >= since, Article.created_at <= now.replace(tzinfo=None))
        .scalar()
    )
    accounted = (
        sum(s["total"] for s in out["series"])
        + out["other"]["articles"]
        + out["unassigned"]["articles"]
        + out["undated"]
    )
    assert accounted == real, (
        f"{real - accounted} articles vanished between the query and the payload"
    )
    # And the drawn bars are the panel's own claim, not a second number.
    for s in out["series"]:
        assert sum(p["n"] for p in s["points"]) == s["total"]


def test_an_article_whose_date_will_not_parse_is_counted_not_dropped(db):
    """The ``undated`` branch, reproduced rather than asserted.

    SQLite is dynamically typed, so a malformed ``created_at`` can genuinely be
    stored; ``strftime`` then yields NULL and the row has no bucket. It still
    matches the window (string comparison puts 'not-a-date' above a timestamp), so
    it is IN the count and must appear somewhere -- dropping it would make the
    conservation property above pass while an article quietly vanished.
    """
    from sqlalchemy import text

    base = _NOW
    src = _source(db)
    _articles(db, src, lang="cs", at=base, n=2)
    _articles(db, src, lang="cs", at=base + timedelta(minutes=1), n=1)
    broken = db.query(Article.id).order_by(Article.id.desc()).first()[0]
    db.execute(text("UPDATE articles SET created_at = 'not-a-date' WHERE id = :i"), {"i": broken})

    out = article_counts_by_language(db, days=1, now=base + timedelta(hours=1))
    assert out["undated"] == 1, "the unbucketable article must be counted, not dropped"
    assert next(s for s in out["series"] if s["language"] == "cs")["total"] == 2


def test_panels_are_ordered_by_volume_then_deterministically(db):
    """A view whose panels reshuffle on refresh cannot be read for change.

    The codes are chosen so ALPHABETICAL order and VOLUME order disagree: SQLite's
    GROUP BY already emits languages alphabetically, so a test seeded with equal
    volumes passes whether or not anything ranks them (it did, until a mutation
    that removed the sort left it green). ``zz`` must lead because it is the
    busiest, and the two tied codes must still order deterministically.
    """
    base = _NOW
    src = _source(db)
    _articles(db, src, lang="aa", at=base, n=1)
    _articles(db, src, lang="zz", at=base + timedelta(minutes=1), n=9)
    _articles(db, src, lang="mm", at=base + timedelta(minutes=2), n=4)
    _articles(db, src, lang="bb", at=base + timedelta(minutes=3), n=4)

    order = [s["language"] for s in article_counts_by_language(db, days=1, now=base + timedelta(hours=1))["series"]]
    assert order == ["zz", "bb", "mm", "aa"], f"ranked by volume, ties on the code: {order}"

    again = [s["language"] for s in article_counts_by_language(db, days=1, now=base + timedelta(hours=1))["series"]]
    assert order == again, "identical calls must not reshuffle the panels"


# --------------------------------------------------------------------------- #
#  The endpoint
# --------------------------------------------------------------------------- #
def test_the_endpoint_serves_the_feed_with_its_method_and_caveat(client):
    r = client.get("/api/library/languages?days=7&top_n=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bucket"] in {"hour", "day"}
    assert isinstance(body["series"], list)
    assert body["method"] and body["caveat"]
    assert "other" in body and "unassigned" in body


def test_top_n_is_bounded_but_the_measurement_is_not(client):
    """The ceiling bounds the RESPONSE. Every language is still counted -- an
    out-of-range ask is clamped, and whatever the clamp excluded is in ``other``."""
    r = client.get("/api/library/languages?days=7&top_n=100000")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["top_n"] <= 60
    assert body["other"]["languages"] >= 0


# --------------------------------------------------------------------------- #
#  The covering index: all three creators, and the plan that proves it
# --------------------------------------------------------------------------- #
def test_the_covering_index_exists_after_init(client):
    from sqlalchemy import text

    from src.database.session import engine

    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert "idx_article_created_lang" in names


def test_ensure_hot_indexes_self_heals_the_covering_index(client):
    """An install that never runs `make migrate` still gets it, at boot."""
    from sqlalchemy import text

    from src.database.maintenance import ensure_hot_indexes
    from src.database.session import engine

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_article_created_lang"))
    assert ensure_hot_indexes(engine) == ["idx_article_created_lang"]
    assert ensure_hot_indexes(engine) == []  # idempotent


def test_migration_matches_the_model_index():
    """Drift guard: the model, the boot self-heal and the migration are three
    independent creators of one index, and nothing but a test makes them agree."""
    from pathlib import Path

    from src.database.maintenance import HOT_INDEXES
    from src.database.models import Article

    model_cols = None
    for idx in Article.__table_args__:
        if getattr(idx, "name", "") == "idx_article_created_lang":
            model_cols = [c.name for c in idx.columns]
    assert model_cols == ["created_at", "language", "detected_language"]

    ddl = HOT_INDEXES["idx_article_created_lang"]
    mig = Path("migrations/versions/7b1e4a93c26d_article_created_lang_covering.py").read_text(encoding="utf-8")
    for col in model_cols:
        assert col in ddl, f"{col} missing from the boot self-heal DDL"
        assert col in mig, f"{col} missing from the migration"


def test_the_real_query_plan_is_index_only(tmp_path):
    """The assertion that proves the fix rather than the index's existence.

    Drives the REAL function against an isolated engine and EXPLAINs the SQL it
    actually emitted -- a hand-written lookalike would pass while the shipped query
    stayed on the heap, which is not hypothetical: a standalone probe of this same
    SQL reported the index covering BOTH the series and the deduced tally, and
    driving the real function showed the tally served from idx_article_language and
    reading the heap. Without this index the plan is a plain ``SEARCH ... USING
    INDEX idx_article_created_at``: SQLite finds the rows by date and then fetches
    each full article row to read one 10-char column, which under SQLCipher decrypts
    the whole ~35 KB row (content sits before language). Measured on a 60k-article
    PLAINTEXT store, with the shape that actually ships: 152 ms -> 71 ms. An
    encrypted store wins proportionally more, per the documented codec cost.
    """
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    eng = create_engine(f"sqlite:///{tmp_path/'plan.db'}")
    Base.metadata.create_all(eng)
    Local = sessionmaker(bind=eng)
    s = Local()
    src = Source(name="S", domain="plan.example")
    s.add(src)
    s.flush()
    at = datetime(2027, 6, 1)
    for i in range(400):
        u = f"https://plan.example/{i}"
        s.add(
            Article(
                source_id=src.id, url=u, canonical_url=u, hash=f"h{i}", title="t",
                content="c" * 400, language=("en" if i % 3 else None),
                detected_language=("fr" if i % 3 == 0 else None),
                created_at=at + timedelta(minutes=i),
            )
        )
    s.commit()

    seen: list[tuple[str, object]] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if "FROM articles" in statement and statement.lstrip().upper().startswith("SELECT"):
            seen.append((statement, parameters))

    article_counts_by_language(s, days=30, now=(at + timedelta(hours=8)).replace(tzinfo=UTC))
    s.close()

    grouped = [(q, p) for q, p in seen if "GROUP BY" in q.upper()]
    assert grouped, "the series query was never issued"
    assert "detected_language IS NOT NULL" in grouped[0][0], (
        "the deduced tally must ride the SAME grouped scan -- split into its own "
        "query, the planner picks idx_article_language and reads the heap"
    )
    assert len(seen) <= 2, f"one covered pass over articles, plus the MIN(created_at): {len(seen)}"

    with eng.connect() as conn:
        for label, (q, p) in (("series", grouped[0]),):
            plan = " | ".join(r[3] for r in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + q, p))
            assert "COVERING INDEX idx_article_created_lang" in plan, f"{label} not index-only: {plan}"

    # And the negative: with the index gone the same query falls back to a bare
    # table scan -- so the assertion above is about THIS index, not about any index
    # happening to be usable.
    #
    # dispose() is load-bearing, not tidiness. pysqlite caches compiled statements
    # per connection and the pool hands the same one back, so EXPLAIN QUERY PLAN
    # keeps reporting the DROPPED index by name (verified: sqlite_master is empty
    # while the plan still cites it). Without a fresh connection this negative half
    # passes whatever the planner would really do -- a guard that cannot fail.
    with eng.begin() as conn:
        conn.execute(text("DROP INDEX idx_article_created_lang"))
    eng.dispose()
    with eng.connect() as conn:
        q, p = grouped[0]
        plan = " | ".join(r[3] for r in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + q, p))
        assert "COVERING" not in plan, f"expected a bare scan without the index: {plan}"


# --------------------------------------------------------------------------- #
#  The tile (source-level: no browser here -- fork-3/Q6a)
# --------------------------------------------------------------------------- #
def test_the_disclosure_node_suite_actually_runs():
    """Drives tests/lang_growth_notes_node_test.js.

    The disclosures are tested for what they SAY, in node, because the source-level
    version of these guards was vacuous: asserting that ``d.other`` appears in the
    tile survived a mutation that kept the binding and dropped the sentence.
    """
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("node") is None:
        pytest.skip("node not available")
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["node", str(root / "tests" / "lang_growth_notes_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout



def test_the_tile_renders_the_feed_neutrally_and_states_what_it_omits():
    """Scoped to ``_libLanguageTile``'s own body via the shared slicer -- a
    whole-file substring would match any of the other Library tiles and prove
    nothing about this one.
    """
    from tests.js_source_helper import assert_present, function_body, read_static

    body = function_body(read_static("app.js"), "_libLanguageTile")
    assert len(body) > 400, "the slice is suspiciously small -- a vacuous guard"

    assert_present(body, "/api/library/languages", why="the tile must read the feed endpoint")
    assert_present(body, "smallMultiplesSvg", why="one panel per language on one shared scale")
    assert_present(body, "neutral: true", why="a slower-growing language is not 'bad' -- no up=green semantics")
    assert_present(body, "ooLangName", why="panels are labelled with the language name, not the bare code")
    # WHAT the tile says about the data it does not draw is proven behaviourally in
    # tests/lang_growth_notes_node_test.js; this only pins that the tile still
    # ROUTES through that helper. Asserting the sentences here as substrings is what
    # was vacuous: the identifiers survived a mutation that dropped the sentences.
    assert_present(body, "_libLangNotes", why="the disclosures must actually be rendered")


def test_the_language_window_chips_re_render_only_their_own_tile():
    """``_libSetWindow`` re-renders ONE tile in place; a new tile that is not
    routed there silently falls back to the metric branch and requests
    ``/api/library/history?metric=__lang``, which 400s."""
    from tests.js_source_helper import assert_present, function_body, read_static

    body = function_body(read_static("app.js"), "_libSetWindow")
    assert_present(body, "__lang", why="the language tile must be routed by its own key")
    assert_present(body, "_libLanguageTile", why="routed to its own renderer, not the metric one")


def test_no_score_anywhere_in_the_payload(client):
    body = client.get("/api/library/languages?days=7").json()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                low = str(k).lower()
                for banned in ("score", "ranking", "rating", "grade"):
                    assert banned not in low, f"a composite score leaked as a key: {k}"
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(body)
