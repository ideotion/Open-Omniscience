"""The three law L0 defects (Q917, brief S04-10 S1) — reproduced, then pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q917 = a: *"The reader shows ``latest_text`` with a version selector; diffs run against
the previous revision (the baseline diff kept as a derived view); the adapter's three
dates are persisted. Confirm, in 0.4 before anything else in this section."*

Each defect's SHAPE, because the shapes are what the guards below are aimed at and all
three fail toward a plausible answer rather than toward an error:

1. **The reader showed the first snapshot ever taken.** ``view_law_document`` rendered
   ``doc.baseline_text`` under the document's own title, with every later amendment
   visible only as a diff underneath. A much-amended Act was therefore shown as its
   superseded self — complete, plausible and wrong — while ``latest_text``, which the
   tracker has materialised since the versioned-sources ruling, was read by nothing.
2. **Every change was measured against the baseline.** ``delta_bytes`` and ``diff`` both
   anchored on the immutable first capture, so a document that grows a little at each
   amendment reported +100, +200, +300 on rows that each read as ONE amendment, and
   ``flag_revision`` — which judges that number — fired forever once a document had
   drifted far from its first capture.
3. **The adapter's dates were parsed and dropped.** ``_document_text`` returned
   ``parsed.text`` and discarded the :class:`~src.law.adapters.ParsedLaw`, so the three
   dates whose separation the adapter's package docstring is largely about reached
   nothing that could store them.

WHAT IS DELIBERATELY NOT ASSERTED HERE: that a change's ``diff`` differs from the
baseline diff *in general*. On a two-revision document they are the same string by
construction (the previous revision IS the baseline), so a fixture with two revisions
cannot discriminate and a guard written over one would pass against the unfixed code.
Every anchoring test below therefore drives at least THREE versions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.law.track import baseline_diff, track_document

# ---------------------------------------------------------------------------
# Fixtures: a real session, and a fetcher double that answers a scripted series
# of bodies so a document can be driven through several genuine versions.
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, content: str) -> None:
        self.content = content
        self.content_type = "text/html"
        self.raw_content = content.encode("utf-8")


class _ScriptedFetcher:
    """Answers each ``fetch`` with the next body in a list. Never touches the network."""

    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)
        self.calls = 0

    def fetch(self, _url, **_kw):
        body = self._bodies[min(self.calls, len(self._bodies) - 1)]
        self.calls += 1
        return _Result(body)


def _page(*paragraphs: str) -> str:
    """An HTML body the tracker's own extractor will read. Long enough to clear
    ``_MIN_TEXT`` (200 chars), because a short body is recorded as ``empty`` and the
    fixture would then test the refusal instead of the anchoring."""
    filler = "This section restates an existing obligation in unchanged words. " * 6
    inner = "".join(f"<p>{p}</p>" for p in (*paragraphs, filler))
    return f"<html><body><main>{inner}</main></body></html>"


@pytest.fixture
def store(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True)
    yield maker
    engine.dispose()


def _doc(session, **kw) -> LawDocument:
    doc = LawDocument(
        jurisdiction="uk",
        title="Measurement Act",
        url="https://example.test/act",
        official_url="https://example.test/act",
        category="legislation",
        **kw,
    )
    session.add(doc)
    session.commit()
    return doc


# ---------------------------------------------------------------------------
# Defect 2 — the diff's anchor
# ---------------------------------------------------------------------------


def test_a_change_is_measured_against_the_previous_version_not_the_baseline(store):
    """THE REPRODUCTION. Three versions, each adding one sentence of a known size.

    Against the baseline the third revision's delta is the sum of both additions; against
    the previous version it is the second addition alone. The two differ by construction,
    so this assertion cannot pass under the old code.
    """
    with store() as s:
        doc = _doc(s)
        v1 = _page("Alpha.")
        v2 = _page("Alpha.", "Beta beta beta beta beta.")
        v3 = _page("Alpha.", "Beta beta beta beta beta.", "Gamma gamma gamma.")
        fetcher = _ScriptedFetcher([v1, v2, v3])

        assert track_document(s, fetcher, doc)["status"] == "baseline"
        assert track_document(s, fetcher, doc)["status"] == "changed"
        assert track_document(s, fetcher, doc)["status"] == "changed"

        revs = s.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id).all()
        assert len(revs) == 3, "three captures must produce three revisions"
        baseline, second, third = revs

        # "first", not "baseline": on a later row "baseline" means "measured against the
        # first capture", and this row IS that capture. One value, one meaning.
        assert baseline.diff_basis == "first"
        assert baseline.diff_base_revision_id is None
        assert second.diff_basis == "previous"
        assert second.diff_base_revision_id == baseline.id
        assert third.diff_basis == "previous"
        assert third.diff_base_revision_id == second.id

        # The discriminating arithmetic: the third change's delta is the third version's
        # growth over the SECOND, and it is strictly smaller than its growth over the
        # baseline. A guard asserting only "delta > 0" would pass under either anchor.
        growth_over_previous = len(third.full_text) - len(second.full_text)
        growth_over_baseline = len(third.full_text) - len(baseline.full_text)
        assert growth_over_previous < growth_over_baseline, (
            "the fixture does not discriminate: make the second version's addition larger"
        )
        assert third.delta_bytes == growth_over_previous
        assert third.delta_bytes != growth_over_baseline

        # And the stored diff shows only THIS amendment: the second version's addition is
        # already in both texts, so it must not appear as an added line.
        assert "Gamma gamma gamma." in third.diff
        assert "Beta beta beta beta beta." not in third.diff, (
            "an unchanged sentence from an earlier amendment is in the diff, so the diff "
            "is still anchored on the baseline"
        )


def test_the_status_sentence_names_the_anchor_it_used(store):
    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher([_page("Alpha."), _page("Alpha.", "Beta.")])
        track_document(s, fetcher, doc)
        track_document(s, fetcher, doc)
        assert "vs the previous version" in (doc.last_status or ""), doc.last_status
        assert "vs baseline" not in (doc.last_status or "")


def test_a_previous_revision_with_no_stored_text_falls_back_and_SAYS_SO(store):
    """A revision recorded before ``full_text`` shipped cannot be measured against.

    Falling back to the baseline is right; doing it silently is the one-key-two-meanings
    defect, so the row records ``diff_basis="baseline"`` and a reader can see that this
    one row measures a different quantity from its neighbours.
    """
    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher([_page("Alpha."), _page("Alpha.", "Beta.")])
        track_document(s, fetcher, doc)
        # Reproduce the legacy shape exactly: a revision whose full_text was never stored,
        # and a document with no materialised latest text either.
        s.query(LawRevision).filter_by(document_id=doc.id).update({"full_text": None})
        doc.latest_text = None
        s.commit()

        track_document(s, fetcher, doc)
        newest = (
            s.query(LawRevision)
            .filter_by(document_id=doc.id)
            .order_by(LawRevision.id.desc())
            .first()
        )
        assert newest.diff_basis == "baseline"
        assert newest.diff_base_revision_id is None
        assert "vs baseline" in (doc.last_status or "")


def test_a_re_extraction_anchors_on_the_text_the_document_held_not_a_stale_revision(store):
    """The re-extraction path records NO revision and re-baselines, so the previous
    revision's stored text is deliberately stale. Anchoring on it would charge the next
    genuine amendment with the page chrome the strip removed.
    """
    from src.law.track import _diff_anchor

    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher([_page("Alpha.")])
        track_document(s, fetcher, doc)
        rev = s.query(LawRevision).filter_by(document_id=doc.id).one()
        # Exactly what the re-extraction branch leaves behind: a better reading on the
        # document, an untouched revision.
        doc.latest_text = (rev.full_text or "") + "\nA sentence the old strip kept."
        s.commit()

        prev, base_text, basis = _diff_anchor(s, doc)
        assert basis == "previous-text"
        assert base_text == doc.latest_text
        assert prev is rev, "the revision is still identified, it is just not the anchor"


def test_the_baseline_comparison_survives_as_a_derived_view(store):
    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher(
            [_page("Alpha."), _page("Alpha.", "Beta beta."), _page("Alpha.", "Beta beta.", "Gamma.")]
        )
        for _ in range(3):
            track_document(s, fetcher, doc)
        third = (
            s.query(LawRevision)
            .filter_by(document_id=doc.id)
            .order_by(LawRevision.id.desc())
            .first()
        )
        view = baseline_diff(doc, third)
        assert view["available"] is True
        assert view["delta_bytes"] == len(third.full_text) - len(doc.baseline_text)
        # Both amendments are visible against the baseline, which is what makes this a
        # DIFFERENT view rather than a second copy of the stored diff.
        assert "Beta beta." in view["diff"]
        assert "Gamma." in view["diff"]
        assert view["delta_bytes"] != third.delta_bytes
        assert "different quantity" in view["method"]


def test_the_derived_view_refuses_rather_than_diffing_against_nothing(store):
    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher([_page("Alpha.")])
        track_document(s, fetcher, doc)
        rev = s.query(LawRevision).filter_by(document_id=doc.id).one()

        stored = rev.full_text
        rev.full_text = None
        s.commit()
        refused = baseline_diff(doc, rev)
        assert refused["available"] is False
        assert "before the full text" in refused["reason"]
        assert "diff" not in refused, "a refusal must not carry a diff of one side against ''"

        rev.full_text = stored
        doc.baseline_text = None
        s.commit()
        refused2 = baseline_diff(doc, rev)
        assert refused2["available"] is False
        assert "no baseline text" in refused2["reason"]


# ---------------------------------------------------------------------------
# Defect 3 — the adapter's dates
# ---------------------------------------------------------------------------

_CLML = """<?xml version="1.0" encoding="UTF-8"?>
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <ukm:Metadata xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
    <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Measurement Act 2018</dc:title>
    <ukm:EnactmentDate Date="2018-05-23"/>
    <dct:valid xmlns:dct="http://purl.org/dc/terms/">2024-01-01</dct:valid>
  </ukm:Metadata>
  <Body>
    <P1 id="section-1">
      <Pnumber>1</Pnumber>
      <P1para><Text>{text}</Text></P1para>
    </P1>
  </Body>
</Legislation>
"""


class _XmlResult:
    def __init__(self, content: str) -> None:
        self.content = content
        self.content_type = "application/xml"
        self.raw_content = content.encode("utf-8")


class _XmlFetcher:
    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)
        self.calls = 0

    def fetch(self, _url, **_kw):
        body = self._bodies[min(self.calls, len(self._bodies) - 1)]
        self.calls += 1
        return _XmlResult(body)


def _clml_body(text: str) -> str:
    return _CLML.format(text=text)


def test_the_adapter_reaches_a_ParsedLaw_the_tracker_can_read():
    """The seam itself: ``_document_text`` returns the parse, not only its text.

    Asserted separately from the storage test below because the two can fail
    independently — a parse that never reaches the caller and a caller that drops it look
    identical from the database.
    """
    from src.law.track import _document_text

    text, reason, parsed = _document_text(
        _XmlResult(_clml_body("A" * 400)), retrieved_on="2026-09-18"
    )
    assert reason == "clml"
    assert text
    assert parsed is not None, "the parse must reach the caller, not just its text"
    assert parsed.enacted_on == "2018-05-23"
    assert parsed.valid_on == "2024-01-01"
    assert parsed.retrieved_on == "2026-09-18", "the caller's capture date must be threaded"


def test_the_three_dates_are_persisted_and_never_stand_in_for_each_other(store):
    with store() as s:
        doc = _doc(s)
        fetcher = _XmlFetcher([_clml_body("The first reading of section 1. " * 12)])
        track_document(s, fetcher, doc)

        assert doc.enacted_on == "2018-05-23", "the document-level enactment date"
        rev = s.query(LawRevision).filter_by(document_id=doc.id).one()
        assert rev.valid_on == "2024-01-01", "the version-level consolidation date"
        # The third date is `observed_at`, deliberately not a second column.
        assert rev.observed_at is not None
        # And none of them is the capture date wearing another label — the whole defect.
        assert doc.enacted_on != rev.observed_at.date().isoformat()
        assert rev.valid_on != rev.observed_at.date().isoformat()


def test_an_html_document_states_no_dates_and_gets_none(store):
    """A web page states nothing this adapter can read, so all three stay absent.

    The negative twin: without it, a fix that filled the dates from the fetch would pass
    every positive assertion above while committing the exact defect being fixed.
    """
    with store() as s:
        doc = _doc(s)
        track_document(s, _ScriptedFetcher([_page("Alpha.")]), doc)
        assert doc.enacted_on is None
        assert s.query(LawRevision).filter_by(document_id=doc.id).one().valid_on is None


def test_the_enactment_date_is_filled_once_and_never_overwritten(store):
    """Two readings that disagree about when a statute was made is a disagreement, and
    silently adopting the newer one would re-date the statute."""
    with store() as s:
        doc = _doc(s)
        first = _clml_body("The first reading of section 1. " * 12)
        second = first.replace('Date="2018-05-23"', 'Date="1999-01-01"').replace(
            "The first reading", "The second reading"
        )
        fetcher = _XmlFetcher([first, second])
        track_document(s, fetcher, doc)
        track_document(s, fetcher, doc)
        assert doc.enacted_on == "2018-05-23", "a later disagreeing reading must not win"


# ---------------------------------------------------------------------------
# Defect 1 — the reader
# ---------------------------------------------------------------------------


def _client(maker):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = maker()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app


@pytest.fixture
def served(store):
    """A document driven through three genuine versions, plus a TestClient over it."""
    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher(
            [
                _page("The original clause."),
                _page("The original clause.", "An inserted clause."),
                _page("The original clause.", "An inserted clause.", "A third clause."),
            ]
        )
        for _ in range(3):
            track_document(s, fetcher, doc)
        doc_id = doc.id
        rev_ids = [
            r.id
            for r in s.query(LawRevision).filter_by(document_id=doc_id).order_by(LawRevision.id)
        ]
    app = _client(store)
    try:
        with TestClient(app) as c:
            yield c, doc_id, rev_ids
    finally:
        app.dependency_overrides.clear()


def test_the_reader_shows_the_current_text_not_the_first_snapshot(served):
    c, doc_id, _rev_ids = served
    body = c.get(f"/api/law/documents/{doc_id}/view").text
    article = body.split("<article", 1)[1].split("</article>", 1)[0]
    # SCOPED TO THE ARTICLE, and the reason is a mutation survivor: every added clause
    # also appears BELOW as a "+" diff line in the amendment history, so a whole-page
    # needle is satisfied by the evidence and cannot tell the current text from the
    # baseline. The first draft of this assertion survived the mutation that puts
    # `doc.baseline_text` back.
    assert "A third clause." in article, "the reader must show the CURRENT text"
    assert "An inserted clause." in article
    # The baseline is still reachable through the selector; what must not happen is the
    # baseline being served AS the document.
    assert "Versions" in body
    assert "Current text (as last captured)" in body


def test_a_stored_past_version_can_be_selected(served):
    c, doc_id, rev_ids = served
    baseline_id = rev_ids[0]
    body = c.get(f"/api/law/documents/{doc_id}/view?version={baseline_id}").text
    article = body.split("<article", 1)[1].split("</article>", 1)[0]
    assert "The original clause." in article
    assert "A third clause." not in article, (
        "selecting the baseline must show the baseline, not fall through to the current text"
    )
    # Scoped to the article on purpose: the amendment history below it legitimately quotes
    # every added clause as diff lines, so a whole-page needle would be satisfied by the
    # evidence rather than by the text — the non-unique-needle trap, met while writing the
    # guard for it.
    assert "A third clause." in body, "the history must still show what changed"
    assert "stored past version" in body, "the footer must say what is on screen"


def test_an_unknown_version_is_a_404_not_a_silent_fallback(served):
    c, doc_id, rev_ids = served
    assert c.get(f"/api/law/documents/{doc_id}/view?version={max(rev_ids) + 999}").status_code == 404


def test_a_version_with_no_stored_text_refuses_by_name(store):
    """The wrong-version-under-the-right-date defect, one level down.

    A revision recorded before ``full_text`` shipped has no text to show. Showing another
    version's words under this version's date would be a fabricated reading; the page says
    what is missing and why, and keeps the diff, which IS held.
    """
    with store() as s:
        doc = _doc(s)
        fetcher = _ScriptedFetcher([_page("Alpha."), _page("Alpha.", "Beta.")])
        track_document(s, fetcher, doc)
        track_document(s, fetcher, doc)
        older = (
            s.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id).first()
        )
        older.full_text = None
        s.commit()
        doc_id, older_id = doc.id, older.id

    app = _client(store)
    try:
        with TestClient(app) as c:
            body = c.get(f"/api/law/documents/{doc_id}/view?version={older_id}").text
            assert "not held locally" in body
            assert "Alpha." not in body.split("<nav", 1)[0].split("<article", 1)[-1], (
                "no other version's words may appear as this version's text"
            )
            assert "text not stored" in body, "the selector must mark it too"
    finally:
        app.dependency_overrides.clear()


def test_every_amendment_row_states_the_anchor_it_was_measured_against(served):
    c, doc_id, _rev_ids = served
    body = c.get(f"/api/law/documents/{doc_id}/view").text
    assert "measured against the previous version" in body
    assert "nothing earlier to measure it against" in body, (
        "the first-capture row must say what it is, on the same line as its siblings"
    )


def test_a_row_recorded_before_the_basis_existed_is_not_relabelled_as_baseline(store):
    """NULL is "nobody wrote it down", which is a different fact from "baseline".

    Rendering the NULL case as the baseline wording would turn an absence into a claim
    somebody made — the one-key-two-meanings defect these columns exist to prevent.
    """
    from src.api.law import _BASIS_UNRECORDED, _BASIS_WORDS

    assert _BASIS_WORDS["baseline"] != _BASIS_UNRECORDED
    assert _BASIS_WORDS.get(None) is None
    # Four values, four distinct sentences: a vocabulary that collapses any two of them
    # is the defect these columns were added to prevent.
    assert len(set(_BASIS_WORDS.values()) | {_BASIS_UNRECORDED}) == len(_BASIS_WORDS) + 1

    with store() as s:
        doc = _doc(s, baseline_text="x" * 300, latest_text="x" * 300)
        s.add(
            LawRevision(
                document_id=doc.id,
                content_hash="legacy",
                observed_at=datetime(2026, 1, 2, tzinfo=UTC),
                delta_bytes=11,
                diff="+a legacy change",
                diff_basis=None,
            )
        )
        s.commit()
        doc_id = doc.id

    app = _client(store)
    try:
        with TestClient(app) as c:
            body = c.get(f"/api/law/documents/{doc_id}/view").text
            assert "recorded before the comparison" in body
            assert "measured against the first captured snapshot" not in body
    finally:
        app.dependency_overrides.clear()


def test_an_unreadable_capture_date_is_ABSENT_never_today(store):
    """The negative twin of the date rows, and it is where the fabrication would live.

    `_retrieved_on` composes the third date from the revision's own `observed_at`. A
    revision that carries none must produce NO row — a date we cannot read is absent,
    never today's, which would read as "captured today" for a document nobody has
    polled in a year. The positive fixture cannot see this: every revision it creates
    has an `observed_at`, so the mutation that falls back to `datetime.now()` survived it.
    """
    with store() as s:
        doc = _doc(s, baseline_text="x" * 300, latest_text="x" * 300)
        s.add(
            LawRevision(
                document_id=doc.id,
                content_hash="no-clock",
                observed_at=None,
                delta_bytes=0,
                diff_basis="first",
            )
        )
        s.commit()
        doc_id = doc.id

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    app = _client(store)
    try:
        with TestClient(app) as c:
            body = c.get(f"/api/law/documents/{doc_id}/view").text
            meta = body.split('class="meta"', 1)[1].split("</div>", 1)[0]
            assert "Captured by this instance" not in body, (
                "a date that cannot be read must be an absent row, never a fabricated one"
            )
            # SCOPED TO THE META BLOCK, which is where a capture date would render. The
            # first draft asserted over the whole page and duly matched a DATE IN A
            # SOURCE COMMENT on the page itself — the non-unique-needle trap meeting the
            # recorded "a date literal in source is a needle that matches prose" one.
            assert today not in meta, "today's date must not appear as a capture date"
    finally:
        app.dependency_overrides.clear()


def test_the_tracker_threads_its_own_capture_date_into_the_parser(store, monkeypatch):
    """A WIRING assertion, not a parameter assertion.

    `test_the_adapter_reaches_a_ParsedLaw_the_tracker_can_read` calls `_document_text`
    with `retrieved_on=` itself, so it proves the parameter works and says nothing about
    whether `track_document` supplies it — the recorded helper-versus-wiring gap, and the
    mutation that drops the argument duly survived that test. This drives the real
    tracker and records what the adapter was actually handed.
    """
    import src.law.adapters.clml as clml_mod

    seen: list[str | None] = []
    real = clml_mod.parse_clml

    def _spy(data, *, retrieved_on=None):
        seen.append(retrieved_on)
        return real(data, retrieved_on=retrieved_on)

    monkeypatch.setattr(clml_mod, "parse_clml", _spy)
    with store() as s:
        doc = _doc(s)
        track_document(s, _XmlFetcher([_clml_body("The first reading of section 1. " * 12)]), doc)
    assert seen, "the adapter was never reached — the fixture, not the wiring, is wrong"
    assert seen[0] == datetime.now(UTC).date().isoformat(), (
        "the tracker must hand the adapter its own capture date; the document cannot know it"
    )


def test_the_reader_shows_the_three_dates_with_their_own_labels(store):
    with store() as s:
        doc = _doc(s)
        track_document(s, _XmlFetcher([_clml_body("The first reading of section 1. " * 12)]), doc)
        doc_id = doc.id

    app = _client(store)
    try:
        with TestClient(app) as c:
            body = c.get(f"/api/law/documents/{doc_id}/view").text
            assert "Enacted" in body and "2018-05-23" in body
            assert "in force from" in body and "2024-01-01" in body
            assert "Captured by this instance" in body
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# The reader's own chrome, ×12.
#
# WHY THIS EXISTS. Before this slice the law reader loaded no i18n at all, so every
# word on it was English by construction and nothing could tell you so. Adding
# ``i18n.js`` makes the page translatable — and makes an UNKEYED string a visible
# defect rather than the status quo. The 2026-09-18 Chromium click-through (en/fr/de/ar)
# found seven of them still English on a page whose neighbours had just been translated,
# which is the same finding shape as the article reader's 2026-07-28 audit item I-2 and
# is guarded the same way here.
#
# The subtler half is WHY a phrase can be unkeyable rather than merely unkeyed: the i18n
# walker matches a text node EXACTLY, so a phrase welded to a timestamp
# ("2026-09-18 04:37 · baseline captured (…)") can never match a static key however many
# locales carry it. Such a phrase has to be its own element with the data BESIDE it —
# so this guard checks the phrase is emitted inside its own tag, not merely emitted.
_READER_CHROME = (
    "Open Omniscience · World law · offline stored copy — a research mirror, not legal advice",
    "Amendment history",
    "baseline captured (the reference text — amendments are measured against it)",
    "No change: this is the first snapshot.",
    "Open the official gazette ↗",
    "Opening the gazette makes a live request from your machine; you'll be asked to confirm.",
    "No official (http/https) URL recorded.",
    # The page's OWN external-link confirm (invariant #7 names OOI18N.t for this).
    "Open the official source on the public web?",
    "This leaves your local copy and makes a live request from your machine — the site "
    "may see your visit. Continue?",
    # The meta block's labels and the two values the page itself composes.
    "Text kind",
    "point-in-time consolidation",
    "raw captured fetch",
    "Last checked",
    "Changes recorded",
)


def _law_source_joined() -> str:
    """``src/api/law.py`` with adjacent string literals collapsed.

    Several of these phrases are emitted across wrapped f-string literals, so a naive
    read of the source does not contain the text the page actually renders.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src" / "api" / "law.py"
    return re.sub(r'"\s*\n\s*f?"', "", src.read_text(encoding="utf-8"))


@pytest.mark.parametrize("phrase", _READER_CHROME)
def test_every_reader_chrome_phrase_is_a_key_in_every_locale(phrase):
    import json
    from pathlib import Path

    locales = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    assert phrase in _law_source_joined(), (
        f"{phrase!r} is keyed but the reader no longer emits it — the key and the page "
        "have drifted, and a drifted key translates nothing"
    )
    for path in sorted(locales.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        assert phrase in table, f"{path.stem}.json is missing {phrase!r}"
        assert table[phrase].strip(), f"{path.stem}.json has an empty value for {phrase!r}"


def test_the_baseline_summary_phrase_is_its_own_element(store):
    """The timestamp travels BESIDE the phrase, never inside it.

    Mutating the reader back to ``<summary>{when} · baseline captured (…)</summary>``
    leaves all twelve locale entries in place and every other test green, while the
    phrase silently stops translating — so this is checked at the level where the
    walker actually works: the rendered tag.
    """
    with store() as s:
        doc = _doc(s)
        track_document(s, _XmlFetcher([_clml_body("The first reading of section 1. " * 12)]), doc)
        doc_id = doc.id

    app = _client(store)
    try:
        with TestClient(app) as c:
            body = c.get(f"/api/law/documents/{doc_id}/view").text
    finally:
        app.dependency_overrides.clear()

    phrase = "baseline captured (the reference text — amendments are measured against it)"
    assert f"<span>{phrase}</span>" in body, (
        "the baseline phrase must sit in its own element: the i18n walker matches a text "
        "node exactly, so a phrase sharing its node with a timestamp is untranslatable"
    )


def test_the_reader_confirm_goes_through_the_i18n_engine():
    """Invariant #7: the external-link confirm's message goes via ``OOI18N.t``.

    This page has its own inline guard rather than the shared ``_externalLinkGuard``,
    and its message was a bare JS string literal — unreachable by the DOM walker, which
    never sees a ``confirm()`` argument. A consent string is exactly the kind the
    informed-consent non-negotiable requires in all twelve locales.
    """
    src = _law_source_joined()
    assert 'OOI18N.t' in src, "the reader's confirm must reach the i18n engine"
    assert 't("Open the official source on the public web?")' in src
