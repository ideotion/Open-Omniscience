"""``AiKeyword.evidence`` gets a writer, and the confirm endpoint gets a consumer (PRH-07).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

TWO DEAD ENDS. The column was documented as "the snippet the model drew the term from"
and had ZERO writers; ``POST /api/ai/keywords/confirm`` had no frontend consumer; and
``GET /api/ai/articles/{id}/keywords`` had none either -- while the analysis window's own
success line already said "Open an article to see its AI-derived metadata".

THE WRITER IS NOT THE MODEL, and that decision is what these tests mostly pin. Asking the
model for a snippet would have added a second unverifiable claim beside the first. This
searches the article's OWN stored text, so the stored fact is "the term appears HERE in
your copy" -- checkable by the reader.

THE NEGATIVE SPACE IS THE POINT. A term that does NOT occur in the text stores NOTHING,
because that absence is the honest signal: the term was inferred, translated or invented.
A fabricated snippet, or a snippet that merely looks plausible, would destroy exactly the
distinction the lens exists to show.
"""

from __future__ import annotations

import pytest

from src.ai_layer.store import evidence_for

_BODY = (
    "The Ministry of Health said on Tuesday that İSTANBUL would host the summit. "
    "Weiß und groß. Later, the ministry confirmed the date."
)


# --------------------------------------------------------------------------- #
#  Grounded terms
# --------------------------------------------------------------------------- #
def test_a_term_in_the_text_gets_the_surrounding_sentence() -> None:
    ev = evidence_for(_BODY, "Ministry of Health")
    assert ev and "Ministry of Health" in ev
    assert "said on Tuesday" in ev, "context, not the bare term"


def test_the_match_is_case_insensitive_without_moving_the_offsets() -> None:
    """``"İ".lower()`` is ``i`` PLUS a combining dot and ``ß``.casefold() is ``ss``, so
    both change LENGTH -- lowering the text and indexing back into it would slice at the
    wrong place. The IGNORECASE search runs over the ORIGINAL string, so the offsets are
    true by construction. These two characters are the whole reason for that choice."""
    for needle in ("istanbul", "İstanbul", "Weiß", "ministry"):
        ev = evidence_for(_BODY, needle)
        assert ev, f"{needle!r} occurs in the text and must be found"
        assert "summit" in ev or "confirmed the date" in ev


def test_the_snippet_is_bounded_and_marks_where_it_was_cut() -> None:
    body = "x" * 5000 + " Ministry of Health " + "y" * 5000
    ev = evidence_for(body, "Ministry of Health")
    assert ev is not None
    assert len(ev) <= 302, "bounded: a lens over twenty terms must stay readable"
    assert ev.startswith("…") and ev.endswith("…"), "an excerpt says it is an excerpt"


# --------------------------------------------------------------------------- #
#  The negative space -- the load-bearing half
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "term"),
    [
        (_BODY, "Atlantis"),          # never mentioned
        (_BODY, "weiss"),             # a DIFFERENT spelling, not a case variant
        (_BODY, ""),                  # nothing to look for
        ("", "Ministry of Health"),   # nothing to look in
        (None, "x"),
    ],
    ids=["absent", "different-spelling", "empty-term", "empty-text", "no-text"],
)
def test_a_term_that_is_not_in_the_text_stores_NOTHING(text, term) -> None:
    """No snippet is the answer, and it is the informative one. Anything else here --
    an empty string, a placeholder, the article's opening line -- would report a term
    the model invented as though the text supported it."""
    assert evidence_for(text, term) is None


def test_a_gap_is_never_stored_as_an_empty_string(tmp_path) -> None:
    """``None`` and ``""`` are different facts at the render boundary: a consumer that
    receives an empty string will happily draw an empty evidence line, which reads as
    "we looked and there is nothing here" rather than "this term is not in your text"."""
    assert evidence_for(_BODY, "Atlantis") is not None or True  # readability
    assert evidence_for(_BODY, "Atlantis") is None


# --------------------------------------------------------------------------- #
#  The writer, driven through the real store helper
# --------------------------------------------------------------------------- #
def _session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _article(session, body: str) -> int:
    from src.database.models import Article, Source

    src = Source(name="s", domain="e.invalid")
    session.add(src)
    session.flush()
    a = Article(
        source_id=src.id,
        url="https://e.invalid/a",
        canonical_url="https://e.invalid/a",
        title="T",
        content=body,
        hash="h1",
    )
    session.add(a)
    session.flush()
    return a.id


def test_record_keywords_stores_evidence_only_for_grounded_terms() -> None:
    """Both directions in ONE call, because the discriminating property is that they
    differ: a writer that stored a snippet for everything, and one that stored none,
    each pass a test that only looks at one of these terms."""
    from src.ai_layer.store import record_keywords
    from src.database.models import AiKeyword

    s = _session()
    aid = _article(s, _BODY)
    added = record_keywords(
        s, aid, ["Ministry of Health", "Atlantis"], model="m", evidence_text=_BODY
    )
    assert added == 2
    rows = {r.term: r.evidence for r in s.query(AiKeyword).all()}
    assert rows["Ministry of Health"] and "said on Tuesday" in rows["Ministry of Health"]
    assert rows["Atlantis"] is None, "an ungrounded term is stored WITHOUT evidence"


def test_omitting_the_text_leaves_every_row_exactly_as_before() -> None:
    """The parameter is optional so no existing caller changes behaviour by omission --
    and a caller that passes nothing must not get an invented snippet from somewhere."""
    from src.ai_layer.store import record_keywords
    from src.database.models import AiKeyword

    s = _session()
    aid = _article(s, _BODY)
    record_keywords(s, aid, ["Ministry of Health"], model="m")
    assert s.query(AiKeyword).one().evidence is None


def test_the_extraction_job_hands_the_article_text_to_the_store() -> None:
    """The WIRING, not the helper: a writer nobody calls with the text stores nothing,
    and every assertion above would still pass. Asserted from the call site's parse tree
    rather than a substring, because the comment beside it necessarily names the same
    argument (the recorded 'a must-be-present guard is satisfied by its own explanation'
    trap, which fails OPEN)."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "ai_layer" / "jobs.py").read_text(
        encoding="utf-8"
    )
    calls = [
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "record_keywords"
    ]
    assert calls, "the extraction job must still call record_keywords"
    for call in calls:
        assert any(kw.arg == "evidence_text" for kw in call.keywords), (
            "record_keywords must be handed the article text, or evidence is never written"
        )


# --------------------------------------------------------------------------- #
#  The endpoints have a consumer
# --------------------------------------------------------------------------- #
def test_ai_lens_node_suite() -> None:
    """Drives ``tests/ai_lens_node_test.js`` -- the BEHAVIOURAL half, and the driver the
    node-suite ratchet requires.

    The source-grep version of these two guards is in that file's header, with the
    mutations that refuted it: ``"loadAiLens()" in src`` is satisfied by the function's
    own declaration, and ``'"POST"' in src`` by a different request in the same file.
    """
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("node") is None:
        pytest.skip("node not available")
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["node", str(root / "tests" / "ai_lens_node_test.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_the_lens_never_merges_into_the_trusted_keyword_list() -> None:
    """The ruling: a confirmed row STAYS AI-derived. The lens renders into its own host
    under its own heading; nothing here appends to the trusted list."""
    from tests import js_source_helper as J

    js = J.read_static("reader.js")
    # Through the shared slicer: a hand-rolled `index(...)` slice is what the slicing
    # ratchet counts, and it is counted because the naive version takes the first `{`
    # after the name (a default parameter truncates it to the signature) or ends at a
    # guessed delimiter. `function_source` brace-matches from the BODY brace.
    lens = J.strip_comments(J.function_source(js, "renderAiLens"))
    assert 'id="r-ailens"' in js, "the pane must give the lens its own host"
    assert "r-ailens" in lens, "and the lens must render into it"
    assert "AI-derived — unreliable" in lens, "labelled at the point of display"
    assert "r-kn" not in lens, "the trusted list's own row furniture must not be reused here"


# ---------------------------------------------------------------------------
# READ-TIME EVIDENCE RESOLUTION (the three-state fix).
#
# The defect these guard: `AiKeyword.evidence` is written only at insert time, so every
# row stored before that writer existed holds NULL -- and the reader rendered NULL as
# "Not found in your stored copy of this article", stating a search that never ran.
# Resolving at read time removes the ambiguity instead of describing it.
# ---------------------------------------------------------------------------


def _article_with(session, *, title, body, compressed=False):
    """An article whose text lives where a real one's does."""
    from src.database.models import Article, Source

    src = Source(name="s", domain="e.invalid")
    session.add(src)
    session.flush()
    url = f"https://e.invalid/{abs(hash((title, body, compressed)))}"
    a = Article(
        source_id=src.id,
        url=url,
        canonical_url=url,
        title=title,
        content=body,
        hash=url[-12:],
    )
    if compressed:
        a.compress_content()
        a.content = ""  # a compressed row leaves the column empty
    session.add(a)
    session.flush()
    return a


def test_a_legacy_row_is_searched_at_read_time_not_reported_absent():
    """The defect itself: a row written with no evidence must not be reported as
    'searched and not found' -- it must be searched, and found."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(session, title="Water policy", body="The aquifer is falling.")
    store.record_keywords(
        session, a.id, ["aquifer"], model="m"
    )  # NO evidence_text -> legacy shape, evidence stays NULL
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    assert rows[0].evidence is None, "fixture must reproduce the legacy NULL"

    found, has_text = store.evidence_for_rows(session, a.id, rows)
    assert has_text is True
    assert rows[0].id in found and "aquifer" in found[rows[0].id]


def test_a_term_absent_from_the_text_stays_absent():
    """The informative case must NOT be filled in -- absence is the finding."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(session, title="Water policy", body="The aquifer is falling.")
    store.record_keywords(session, a.id, ["Montenegro"], model="m")
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    found, has_text = store.evidence_for_rows(session, a.id, rows)
    assert has_text is True
    assert found == {}, "a term not in the text must get no snippet"


def test_an_article_with_no_text_reports_the_third_state():
    """`has_text=False` is a DIFFERENT fact from 'searched and not found'. Collapsing
    them is the defect; this is the guard that keeps them apart."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(session, title=None, body="")
    store.record_keywords(session, a.id, ["anything"], model="m")
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    found, has_text = store.evidence_for_rows(session, a.id, rows)
    assert has_text is False
    assert found == {}


def test_compressed_articles_are_searched_through_get_content():
    """Searching `Article.content` directly would report every term of every COMPRESSED
    article as absent -- fabricating the exact absence this lens exists to report."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(
        session, title="Water policy", body="The aquifer is falling.", compressed=True
    )
    assert a.content == "" and a.compressed_content, "fixture must be compressed"
    store.record_keywords(session, a.id, ["aquifer"], model="m")
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    found, has_text = store.evidence_for_rows(session, a.id, rows)
    assert has_text is True, "a compressed article HAS text"
    assert rows[0].id in found


def test_a_headline_term_is_grounded_in_the_title():
    """The extractor is shown title + body, so a term taken from the headline must not
    be reported absent from the article."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(session, title="Aquifer collapse", body="Rain fell.")
    store.record_keywords(session, a.id, ["Aquifer"], model="m")
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    found, _ = store.evidence_for_rows(session, a.id, rows)
    assert rows[0].id in found


def test_resolution_never_writes():
    """Read-only by design: persisting would make a GET mutate, and the nearest
    precedent (autoIndexInsights) needed a cooldown after the P0-5 write storm."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(session, title="Water policy", body="The aquifer is falling.")
    store.record_keywords(session, a.id, ["aquifer"], model="m")
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    store.evidence_for_rows(session, a.id, rows)
    session.commit()
    fresh = store.keywords_for_article(session, a.id)
    assert fresh[0].evidence is None, "resolution must not persist"


def test_a_stored_snippet_is_preferred_and_agrees_with_recomputation():
    """New rows already carry evidence; the resolver must reuse it, and because both
    paths go through evidence_for they cannot disagree."""
    from src.ai_layer import store

    session = _session()
    a = _article_with(session, title="Water policy", body="The aquifer is falling.")
    store.record_keywords(
        session, a.id, ["aquifer"], model="m",
        evidence_text="Water policy\n\nThe aquifer is falling.",
    )
    session.commit()
    rows = store.keywords_for_article(session, a.id)
    assert rows[0].evidence, "writer must have stored one"
    found, _ = store.evidence_for_rows(session, a.id, rows)
    assert found[rows[0].id] == rows[0].evidence


# ---------------------------------------------------------------------------
# THE HTTP CONTRACT — the three states as the reader actually receives them.
# The store-level tests above pin the resolution; these pin what the endpoint SAYS,
# which is where the false sentence was rendered from.
# ---------------------------------------------------------------------------


def _seed(title: str, body: str) -> int:
    import uuid

    from src.database.models import Article, Source
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        domain = f"ev-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=domain, domain=domain, language="en")
        s.add(src)
        s.flush()
        a = Article(
            url=f"https://{domain}/a", canonical_url=f"https://{domain}/a",
            source_id=src.id, title=title, content=body, language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        return a.id


def _lens(aid: int) -> list[dict]:
    from fastapi.testclient import TestClient

    from src.api.main import app

    r = TestClient(app).get(f"/api/ai/articles/{aid}/keywords")
    assert r.status_code == 200, r.text
    return r.json()["keywords"]


def _legacy_row(aid: int, term: str) -> None:
    """A row exactly as it was written before the evidence writer existed."""
    from src.ai_layer.store import record_keywords
    from src.database.session import session_scope

    with session_scope() as s:
        record_keywords(s, aid, [term], model="m")  # no evidence_text -> NULL


def test_http_a_grounded_legacy_row_carries_evidence() -> None:
    aid = _seed("Water policy", "The aquifer is falling fast this year.")
    _legacy_row(aid, "aquifer")
    (k,) = _lens(aid)
    assert "aquifer" in k["evidence"]
    assert "evidence_absent" not in k


def test_http_an_ungrounded_term_is_reported_as_searched_and_absent() -> None:
    aid = _seed("Water policy", "The aquifer is falling fast this year.")
    _legacy_row(aid, "Montenegro")
    (k,) = _lens(aid)
    assert "evidence" not in k
    assert k["evidence_absent"] is True, (
        "the copy WAS searched and the term is not in it — the informative case"
    )


def test_http_an_untextual_article_asserts_no_search_at_all() -> None:
    """THE DEFECT. With no text to search, the endpoint must emit NEITHER key, so the
    reader cannot say 'not found in your stored copy' about a search nobody ran."""
    aid = _seed("", "")
    _legacy_row(aid, "Montenegro")
    (k,) = _lens(aid)
    assert "evidence" not in k
    assert "evidence_absent" not in k, (
        "claiming absence here would state a search that never happened"
    )


def test_http_reading_the_lens_does_not_write() -> None:
    """The endpoint's docstring promises a read never writes. Persisting evidence would
    break that and make a GET mutate — the P0-5 storm is the precedent against it."""
    from src.database.models import AiKeyword
    from src.database.session import session_scope

    aid = _seed("Water policy", "The aquifer is falling fast this year.")
    _legacy_row(aid, "aquifer")
    _lens(aid)
    with session_scope() as s:
        row = s.query(AiKeyword).filter_by(article_id=aid).one()
        assert row.evidence is None, "resolution is read-only"
