"""The Living sources view (Q1016; gate row O, S04-08's S6): its reads and its page.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What must hold, and why each is its own test:

* COUNTS AND DATES, NEVER A VERDICT. Freshness is the newest and oldest check, and
  coverage is "followed" beside "only counted" -- a lane under a budget stores the text
  of some changes and counts the rest, and a view that showed only the numerator would
  read as complete.
* EACH SOURCE DEGRADES ALONE. A lane that never ran, a lane file with no tables (the
  empty ``wiki.db`` the S5 walk found), a map manager that raises: each is a named
  absence in its own block, and the other two sources still answer.
* A READ NEVER CREATES THE LANE FILE. The drain makes it, with its schema and its
  refusals (Q1005); a GET that made an empty one would recreate the S5 bug by looking.
* THE MODAL IS GONE AND ITS VIEW LIVES IN THE TAB, with the same honest renderer, so
  the watched-pages table and the reader's ``?wikitc=`` link still land somewhere.

The renderers are driven in node (``tests/living_sources_node_test.js``).
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import living, wiki_lane
from src.versioned.models import (
    VersionedChange,
    VersionedCursor,
    VersionedGap,
    VersionedRevision,
)
from src.versioned.pipeline import ensure_entity
from src.versioned.store import create_lane, dispose_all, lane_path, lane_session

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


@pytest.fixture
def no_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    try:
        yield tmp_path
    finally:
        dispose_all()


@pytest.fixture
def lane(no_lane):
    create_lane("wiki")
    return no_lane


@pytest.fixture
def corpus():
    """A throwaway main database holding only the four tables the overview reads, so
    every count below is exact rather than a delta over the suite's shared database."""
    from src.database.models import Base, LawDocument, LawRevision, WikiPage, WikiRevision

    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[t.__table__ for t in (WikiPage, WikiRevision, LawDocument, LawRevision)],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


NOW = datetime.now(UTC)
SINCE = NOW - timedelta(days=living.WINDOW_DAYS)


# --------------------------------------------------------------------------- #
# the stream's block
# --------------------------------------------------------------------------- #
def test_a_lane_that_never_ran_is_NAMED_and_the_read_does_not_create_it(no_lane):
    out = living._wiki_stream(SINCE)
    assert out == {"measured": False, "reason": "lane-never-run"}
    assert not lane_path("wiki").exists(), "a GET made the lane file a drain should make"


def test_the_stream_counts_followed_counted_and_unfollowed_SEPARATELY(lane):
    old = NOW - timedelta(days=living.WINDOW_DAYS + 3)
    with lane_session("wiki") as db:
        rome = ensure_entity(db, "en:Rome", title="Rome", language="en")
        db.flush()
        rev = VersionedRevision(entity_id=rome.id, revision_ref="r2", content_hash="h", content="x")
        db.add(rev)
        db.flush()
        db.add_all([
            # followed, text stored
            VersionedChange(entity_id=rome.id, change_ref="a", feed="stream:en", change_kind="edit",
                            recorded_at=NOW - timedelta(hours=1), ingested_revision_id=rev.id),
            # followed, only counted
            VersionedChange(entity_id=rome.id, change_ref="b", feed="stream:en", change_kind="edit",
                            recorded_at=NOW - timedelta(hours=2)),
            # not followed
            VersionedChange(external_id="en:Elsewhere", change_ref="c", feed="stream:en",
                            change_kind="edit", recorded_at=NOW - timedelta(hours=3)),
            # outside the window: counted nowhere
            VersionedChange(entity_id=rome.id, change_ref="d", feed="stream:en", change_kind="edit",
                            recorded_at=old),
        ])
        db.commit()
    out = living._wiki_stream(SINCE)
    assert out["measured"] is True
    assert out["pages"] == 1
    assert out["changes"] == 2, "the window leaked a change older than it"
    assert out["changes_with_text"] == 1
    assert out["changes_not_followed"] == 1
    assert out["open_gaps"] == 0
    assert out["contiguous_through"] is None, "no feed declared one, so none is invented"


def test_complete_through_is_the_feed_that_is_BEHIND(lane):
    """With one feed current and one behind, only the one behind is true of both."""
    ahead, behind = NOW - timedelta(minutes=5), NOW - timedelta(days=2)
    with lane_session("wiki") as db:
        db.add_all([
            VersionedCursor(feed="stream:en", contiguous_through=ahead, updated_at=NOW),
            VersionedCursor(feed="stream:fr", contiguous_through=behind, updated_at=NOW - timedelta(hours=1)),
            VersionedGap(feed="stream:fr", reason="reconnect"),
            VersionedGap(feed="stream:en", reason="reconnect", closed_at=NOW),
        ])
        db.commit()
    out = living._wiki_stream(SINCE)
    assert out["contiguous_through"] == behind.isoformat()
    assert out["cursor_read_at"] == NOW.isoformat()
    assert out["open_gaps"] == 1, "a closed gap was counted as open"


def test_an_EMPTY_lane_file_is_named_and_does_not_blank_the_other_sources(no_lane, monkeypatch):
    """The S5 walk's bug, from the reader's side: a wiki.db with no tables."""
    path = lane_path("wiki")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    stream = living._wiki_stream(SINCE)
    assert stream["measured"] is False and stream["reason"] == "unreadable"
    changes = wiki_lane.lane_changes(limit=50, offset=0)
    assert changes["measured"] is False and changes["reason"] == "lane-unreadable"


# --------------------------------------------------------------------------- #
# the main database's blocks
# --------------------------------------------------------------------------- #
def test_tracked_pages_freshness_is_the_newest_and_OLDEST_check(corpus):
    from src.database.models import WikiPage, WikiRevision

    naive = NOW.replace(tzinfo=None)
    a = WikiPage(wiki="en", title="A", watched=True, last_checked_at=naive - timedelta(days=1))
    b = WikiPage(wiki="en", title="B", watched=True, last_checked_at=naive - timedelta(days=40))
    c = WikiPage(wiki="en", title="C", watched=True, last_checked_at=None)
    off = WikiPage(wiki="en", title="Unwatched", watched=False, last_checked_at=naive)
    corpus.add_all([a, b, c, off])
    corpus.flush()
    corpus.add_all([
        WikiRevision(page_id=a.id, revid=1, created_at=naive - timedelta(days=2), flagged=True),
        WikiRevision(page_id=a.id, revid=2, created_at=naive - timedelta(days=2)),
        # an old EDIT stored today counts; a revision stored long ago does not
        WikiRevision(page_id=b.id, revid=3, created_at=naive - timedelta(days=90)),
    ])
    corpus.commit()
    out = living._wiki_tracked(corpus, SINCE.replace(tzinfo=None))
    assert out["pages"] == 3, "an unwatched page was counted as tracked"
    assert out["never_checked"] == 1
    assert out["newest_check_at"].startswith((naive - timedelta(days=1)).isoformat()[:16])
    assert out["oldest_check_at"].startswith((naive - timedelta(days=40)).isoformat()[:16])
    assert out["newest_check_at"].endswith("+00:00"), "a naive UTC time went out without its zone"
    assert out["changes"] == 2 and out["flagged"] == 1


def test_law_counts_a_CHANGE_not_a_recheck(corpus):
    from src.database.models import LawDocument, LawRevision

    naive = NOW.replace(tzinfo=None)
    d1 = LawDocument(jurisdiction="fr", title="Code", url="https://x.invalid/1", last_checked_at=naive)
    d2 = LawDocument(jurisdiction="uk", title="Act", url="https://x.invalid/2")
    corpus.add_all([d1, d2])
    corpus.flush()
    corpus.add_all([
        LawRevision(document_id=d1.id, content_hash="a", delta_bytes=120, observed_at=naive, flagged=True),
        LawRevision(document_id=d1.id, content_hash="b", delta_bytes=0, observed_at=naive),
        LawRevision(document_id=d1.id, content_hash="c", delta_bytes=-4,
                    observed_at=naive - timedelta(days=60)),
    ])
    corpus.commit()
    out = living._law(corpus, SINCE.replace(tzinfo=None))
    assert out["documents"] == 2 and out["jurisdictions"] == 2
    assert out["never_checked"] == 1
    assert out["changes"] == 1, "a re-check with no byte change, or an old change, was counted"
    assert out["flagged"] == 1


def test_a_database_that_cannot_be_read_is_NAMED_per_block():
    engine = create_engine("sqlite://")  # no tables at all
    session = sessionmaker(bind=engine)()
    try:
        assert living._wiki_tracked(session, SINCE)["reason"] == "unreadable"
        assert living._law(session, SINCE)["reason"] == "unreadable"
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# maps
# --------------------------------------------------------------------------- #
class _Maps:
    def __init__(self, entries):
        self._entries = entries

    def list(self):
        return self._entries


def test_maps_count_states_and_bytes_and_say_the_DATE_is_not_recorded(monkeypatch):
    from src.geo import osm_downloads

    monkeypatch.setattr(osm_downloads, "get_manager", lambda: _Maps([
        {"status": "done", "downloaded_bytes": 1000},
        {"status": "paused", "downloaded_bytes": 250},
        {"status": "error", "downloaded_bytes": 0},
        {"status": "something-new", "downloaded_bytes": 5},
    ]))
    out = living._maps()
    assert out["regions"] == 4
    assert out["by_state"]["done"] == 1 and out["by_state"]["paused"] == 1
    assert out["by_state"]["error"] == 1, "a failed download was not counted as one"
    assert out["other_state"] == 1, "an unknown state was mapped onto a known one"
    assert out["bytes_on_disk"] == 1255
    assert out["freshness"] == {"measured": False, "reason": "not-recorded"}


def test_the_map_states_are_the_WORDS_THE_MANAGER_WRITES():
    """The manager says ``error`` where the task manager says "failed". Counting under a
    word it never writes reads every failed download as zero, and nothing else fails."""
    src = (_ROOT / "src/geo/osm_downloads.py").read_text(encoding="utf-8")
    written = set(re.findall(r'\.status = "(\w+)"', src))
    assert written, "no status assignments found -- the manager changed shape"
    assert written <= set(living._MAP_STATES), written - set(living._MAP_STATES)
    app = (_ROOT / "src/static/app-living.js").read_text(encoding="utf-8")
    table = re.search(r"const _LIVING_MAP_STATE = \{(.*?)\};", app, re.S).group(1)
    assert set(re.findall(r"(\w+):", table)) == set(living._MAP_STATES)


def test_a_map_manager_that_raises_does_not_blank_the_overview(no_lane, corpus, monkeypatch):
    from src.geo import osm_downloads

    def boom():
        raise RuntimeError("state file unreadable")

    monkeypatch.setattr(osm_downloads, "get_manager", boom)
    out = living.living_overview(db=corpus)
    kinds = [s["kind"] for s in out["sources"]]
    assert kinds == ["wiki", "law", "osm"]
    osm = out["sources"][2]
    assert osm["maps"]["measured"] is False and osm["maps"]["reason"] == "unreadable"
    law = out["sources"][1]
    assert law["tracker"]["measured"] is True, "one source's trouble blanked another"
    assert out["window_days"] == living.WINDOW_DAYS
    assert "never judged" in out["caveat"]


def test_the_overview_uses_the_SAME_storage_rows_as_settings(monkeypatch):
    """Two surfaces that computed a lane's size separately would come to disagree."""
    from src.database.session import SessionLocal
    from src.versioned import budget

    seen = []

    def fake(session):
        seen.append(session)
        return {"lanes": [{"kind": "wiki", "bytes": 7}, {"kind": "law", "bytes": None}]}

    monkeypatch.setattr(budget, "storage_report", fake)
    db = SessionLocal()
    try:
        out = living.living_overview(db=db)
    finally:
        db.close()
    assert seen, "the overview did not read Settings -> Storage's report"
    by_kind = {s["kind"]: s["storage"] for s in out["sources"]}
    assert by_kind["wiki"] == {"kind": "wiki", "bytes": 7}
    assert by_kind["osm"] is None


# --------------------------------------------------------------------------- #
# the stream's timeline and its stored diffs
# --------------------------------------------------------------------------- #
def test_the_timeline_is_newest_first_FOLLOWED_only_and_says_what_was_stored(lane):
    with lane_session("wiki") as db:
        rome = ensure_entity(db, "en:Rome", title="Rome", language="en")
        db.flush()
        rev = VersionedRevision(entity_id=rome.id, revision_ref="r9", content_hash="h", content="x",
                                diff_method="unified", diff_added=3, diff_removed=1,
                                diff_text="--- previous\n+++ current\n+new\n-old\n")
        db.add(rev)
        db.flush()
        db.add_all([
            VersionedChange(entity_id=rome.id, change_ref="new", feed="stream:en", change_kind="edit",
                            recorded_at=NOW, ingested_revision_id=rev.id, byte_delta=40),
            VersionedChange(entity_id=rome.id, change_ref="mid", feed="stream:en", change_kind="log-thing",
                            recorded_at=NOW - timedelta(minutes=5)),
            VersionedChange(external_id="en:Other", change_ref="x", feed="stream:en", change_kind="edit",
                            recorded_at=NOW - timedelta(minutes=1)),
        ])
        db.commit()
        rid = rev.id
    out = wiki_lane.lane_changes(limit=50, offset=0)
    assert out["measured"] is True
    assert out["total"] == 2, "a change on a page nobody follows entered the timeline"
    first, second = out["changes"]
    assert first["title"] == "Rome" and first["text_stored"] is True and first["revision_id"] == rid
    assert first["diff_added"] == 3 and first["diff_method"] == "unified"
    assert second["text_stored"] is False and second["revision_id"] is None
    assert second["change_kind"] == "log-thing", "an unknown kind was mapped instead of kept"
    page = wiki_lane.lane_changes(limit=1, offset=1)
    assert page["count"] == 1 and page["changes"][0]["change_kind"] == "log-thing"

    diff = wiki_lane.lane_revision_diff(rid)
    assert diff["diff_text"].startswith("--- previous") and diff["truncated"] is False
    assert diff["title"] == "Rome" and diff["revision_ref"] == "r9"


def test_a_long_diff_is_CUT_and_says_so(lane, monkeypatch):
    monkeypatch.setattr(wiki_lane, "_DIFF_TEXT_CAP", 10)
    with lane_session("wiki") as db:
        e = ensure_entity(db, "en:Long", title="Long")
        db.flush()
        rev = VersionedRevision(entity_id=e.id, revision_ref="r", content_hash="h",
                                diff_method="unified", diff_text="+" + "a" * 99)
        db.add(rev)
        db.commit()
        rid = rev.id
    out = wiki_lane.lane_revision_diff(rid)
    assert len(out["diff_text"]) == 10 and out["diff_chars"] == 100 and out["truncated"] is True


def test_an_unknown_revision_is_a_404_and_an_absent_lane_is_named(no_lane):
    assert wiki_lane.lane_changes(limit=5, offset=0)["reason"] == "lane-never-run"
    assert wiki_lane.lane_revision_diff(1)["reason"] == "lane-never-run"
    assert not lane_path("wiki").exists()
    create_lane("wiki")
    with pytest.raises(HTTPException) as exc:
        wiki_lane.lane_revision_diff(12345)
    assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------------- #
def _html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def _tab(html: str) -> str:
    start = html.index('<div class="tab-page" id="tab-living">')
    return html[start: html.index('<!-- ========================== WORLD MAP', start)]


def test_the_tab_exists_with_its_subtabs_and_a_VISIBLE_caveat():
    html = _html()
    assert '<button class="nav-item" data-tab="living">' in html
    tab = _tab(html)
    assert '<nav class="tabs" id="living-subtabs"' in tab
    for kind in ("wiki", "law", "osm"):
        assert f'data-tab="{kind}"' in tab and f'id="living-{kind}-facts"' in tab
    assert 'class="card-caveat" id="living-caveat"' in tab, "the caveat must be printed, never hovered"
    assert "never judged" in tab and "not a live re-diff" in tab


def test_the_tracked_changes_DIALOG_is_gone_and_its_view_lives_in_the_tab():
    html = _html()
    assert '<dialog id="wiki-tc"' not in html, "the tracked-changes modal must be gone (Q1016)"
    tab = _tab(html)
    for needle in ('<section id="wiki-tc"', 'id="wiki-tc-body"', 'id="wiki-tc-title"',
                   'id="wiki-tc-flagged"', 'id="wiki-tc-method" class="card-caveat"',
                   'onchange="loadWikiTC()"'):
        assert needle in tab, f"the tracked-changes view lost {needle} in its move"


def test_the_tab_is_registered_through_the_shell():
    shell = (_STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert "living: () => loadLiving()" in shell
    assert 'living: "living-subtabs"' in shell, "the subtab strip must be relocated like every other tab's"
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    assert '"/static/app-living.js"' in sw
    html = _html()
    assert html.index('src="/static/app-living.js"') < html.index('src="/static/app-boot.js"'), (
        "boot runs last; a module after it is not defined when boot wires the page"
    )


def test_opening_a_tracked_page_goes_to_the_tab_through_its_COMPONENT():
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "openWikiTC"))
    assert 'showTab("living")' in body
    assert '_livingSubtabs.select("wiki")' in body, "invariant #18: select through the component"
    assert "showModal" not in body, "the view is not a dialog any more"


def test_the_renderers_behave(tmp_path):
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "living_sources_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_diff_lines_take_their_direction_from_their_OWN_text():
    """In the Arabic UI the walk drew "+An added line" as "An added line+" and a size
    change of -3000 as "3000-": a diff is read line by line, and each line is in the
    source's language, not the interface's."""
    css = (_STATIC / "app.css").read_text(encoding="utf-8")
    rule = re.search(r"\.living-diff-l \{([^}]*)\}", css).group(1)
    assert "unicode-bidi: plaintext" in rule
    from tests.js_source_helper import app_js, function_body

    row = function_body(app_js(), "_wikiRevRow")
    assert "unicode-bidi:plaintext" in row, "the tracked view's diff lines follow the UI direction"
    assert "direction:ltr;unicode-bidi:isolate" in row, "the tracked view's size change is not isolated"
