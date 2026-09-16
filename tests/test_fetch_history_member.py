"""The fetch/scrape-history member and its trust toggle (the Q701 note, gate row K).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ACCEPTANCE CLAUSE the brief names: "a fixture where a restored history, trusted,
prevents a re-fetch of a recorded page and, untrusted, does not". Both directions are
here, and the trusted one is driven through the REAL conditional-GET header builder --
because "the row arrived" and "the next fetch will be answered 304" are different
claims, and only the second is what the note asks for.

Every merge here is into a DIFFERENT (empty) corpus: a self-restore sees every row as a
duplicate, so it can never exercise a handler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup import fetch_history as fh  # noqa: E402
from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import Base, FeedFetchState, Source  # noqa: E402

_BATCH_META = {
    "artifact_kind": "oo-backup-3",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}
_CHECKED = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)
_SKIP = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _staged_with_history(path: Path) -> None:
    with _corpus(path)() as s:
        src = Source(name="N", domain="n.example", rss_url="https://n.example/feed.xml")
        s.add(src)
        s.flush()
        s.add(
            FeedFetchState(
                source_id=src.id,
                etag='"v1-etag"',
                last_modified="Mon, 01 Sep 2026 09:00:00 GMT",
                last_status=200,
                last_checked_at=_CHECKED,
                consecutive_unchanged=3,
                skip_until=_SKIP,
            )
        )
        s.commit()


# --------------------------------------------------------------------------- #
#  Trusted: the history really prevents a re-download
# --------------------------------------------------------------------------- #
def test_a_trusted_history_makes_the_next_fetch_CONDITIONAL(tmp_path):
    """THE ACCEPTANCE CLAUSE. Asserted through ``_feed_conditional_headers``, the real
    function the collector calls: a row that arrived but produced no If-None-Match
    would satisfy a row-count assertion and prevent nothing."""
    from src.ingest.pipeline import _feed_conditional_headers

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _staged_with_history(staged)
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META, trust_fetch_history=True)

    with _corpus(working)() as s:
        sid = s.query(Source).one().id
        headers = _feed_conditional_headers(s, sid)
    assert headers["If-None-Match"] == '"v1-etag"'
    assert headers["If-Modified-Since"] == "Mon, 01 Sep 2026 09:00:00 GMT"


def test_a_trusted_backoff_deadline_keeps_the_feed_out_of_the_next_pass(tmp_path):
    """The other half of "prioritises other downloads": a feed the source corpus found
    unchanged stays backed off until its capped deadline, so the pass spends its budget
    elsewhere. Driven through ``feed_is_due``, the real decision."""
    from src.ingest.pipeline import feed_is_due

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _staged_with_history(staged)
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META, trust_fetch_history=True)

    with _corpus(working)() as s:
        st = s.query(FeedFetchState).one()
    assert feed_is_due(st) is False


# --------------------------------------------------------------------------- #
#  Untrusted: nothing is adopted, and the report says so
# --------------------------------------------------------------------------- #
def test_an_untrusted_history_writes_NOTHING(tmp_path):
    from src.ingest.pipeline import _feed_conditional_headers

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _staged_with_history(staged)
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META, trust_fetch_history=False)

    with _corpus(working)() as s:
        assert s.query(FeedFetchState).count() == 0
        sid = s.query(Source).one().id
        assert _feed_conditional_headers(s, sid) == {}, (
            "an untrusted restore still made the next fetch conditional"
        )
    assert counts["_fetch_history"]["trusted"] is False
    assert counts["_fetch_history"]["adopted"] == 0


def test_an_untrusted_restore_still_reports_WHAT_WAS_DECLINED(tmp_path):
    """A bare zero cannot tell "you said no" from "there was nothing there". An
    operator who untrusted a history needs to see the size of what they declined."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _staged_with_history(staged)
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META, trust_fetch_history=False)

    assert counts["_fetch_history"]["available"] == 1


def test_the_step_runs_and_reports_even_with_nothing_to_adopt(tmp_path):
    """A step skipped when the answer is "no" would make "declined" and "empty" the
    same silence."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(Source(name="N", domain="n.example"))
        s.commit()
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META, trust_fetch_history=True)

    assert counts["_fetch_history"]["available"] == 0
    assert counts["_fetch_history"]["adopted"] == 0


# --------------------------------------------------------------------------- #
#  The adoption rule
# --------------------------------------------------------------------------- #
def test_a_local_row_always_wins(tmp_path):
    """Fill a gap, never overwrite. A local ``feed_fetch_state`` row is THIS machine's
    own observation of that feed; the other instance's is not a fact about this one."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _staged_with_history(staged)
    with _corpus(working)() as s:
        src = Source(name="N", domain="n.example", rss_url="https://n.example/feed.xml")
        s.add(src)
        s.flush()
        s.add(FeedFetchState(source_id=src.id, etag='"MINE"', last_status=304))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META, trust_fetch_history=True)

    with _corpus(working)() as s:
        assert s.query(FeedFetchState).one().etag == '"MINE"'
    assert counts["_fetch_history"]["adopted"] == 0
    assert counts["feed_fetch_state"]["duplicate"] == 1


def test_last_checked_at_is_NOT_adopted(tmp_path):
    """It answers "when did THIS instance last check", and the coverage report reads it
    as exactly that. Copying a foreign timestamp would claim a check this machine never
    made -- the ``articles.keyword_indexed_at`` inversion. Nothing is lost: no fetch
    decision reads it."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _staged_with_history(staged)
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META, trust_fetch_history=True)

    with _corpus(working)() as s:
        st = s.query(FeedFetchState).one()
    assert st.last_checked_at is None, (
        "a foreign last_checked_at was adopted; the coverage report would claim reach "
        "this instance never had"
    )
    # ... and the columns that DO decide a fetch really did arrive, so the omission is
    # an omission and not a broken handler.
    assert st.etag == '"v1-etag"'
    assert st.skip_until is not None


def test_the_carried_column_set_matches_the_model():
    """The explicit-allowlist trap, one table over: a column added to
    ``FeedFetchState`` after this handler was written would be silently dropped. Every
    column is either carried, the primary key, or named in the omitted registry WITH a
    reason."""
    cols = {c.name for c in FeedFetchState.__table__.columns}
    accounted = set(fh.FEED_FETCH_STATE_CARRIED) | set(fh.FEED_FETCH_STATE_OMITTED) | {"source_id"}
    assert cols == accounted, (
        f"unaccounted feed_fetch_state columns: {sorted(cols - accounted)}; "
        f"registry names columns that do not exist: {sorted(accounted - cols)}"
    )
    for name, reason in fh.FEED_FETCH_STATE_OMITTED.items():
        assert len(reason) > 40, f"{name} is omitted with no usable reason"


def test_the_table_left_the_not_carried_registry():
    """It was classified "per-machine, self-healing, re-learned on the next pass" --
    correct about the mechanism and overturned as a POLICY by the Q701 note. A table in
    both registries at once would be a merge nobody can reason about."""
    from src.backup.merge import _MERGE_HANDLED, _MERGE_NOT_CARRIED

    assert "feed_fetch_state" in _MERGE_HANDLED
    assert "feed_fetch_state" not in _MERGE_NOT_CARRIED


# --------------------------------------------------------------------------- #
#  The toggle's resolution order
# --------------------------------------------------------------------------- #
def test_an_explicit_choice_wins_over_the_stored_default(monkeypatch):
    monkeypatch.setattr(
        "src.config.app_settings.load_settings",
        lambda: type("S", (), {"trust_backup_fetch_history": True})(),
    )
    assert fh.resolve_trust_fetch_history(False) is False
    assert fh.resolve_trust_fetch_history(True) is True


def test_no_choice_falls_back_to_the_stored_answer(monkeypatch):
    """None is "this import did not choose", NOT "chose False". Coercing it would
    silently discard a history the operator had already said to trust."""
    for stored in (True, False):
        monkeypatch.setattr(
            "src.config.app_settings.load_settings",
            lambda stored=stored: type("S", (), {"trust_backup_fetch_history": stored})(),
        )
        assert fh.resolve_trust_fetch_history(None) is stored


def test_an_unreadable_settings_store_resolves_to_the_SHIPPED_DEFAULT(monkeypatch):
    """A read error must not quietly change what the app does with somebody's data, in
    either direction."""
    from src.config.app_settings import AppSettings

    def _boom():
        raise OSError("settings unreadable")

    monkeypatch.setattr("src.config.app_settings.load_settings", _boom)

    assert fh.resolve_trust_fetch_history(None) is AppSettings().trust_backup_fetch_history


def test_the_registry_says_what_adopting_each_table_changes():
    """The registry is the answer to "what does the toggle gate?", so an entry with no
    stated effect would make the toggle's own copy unverifiable."""
    assert "feed_fetch_state" in fh.FETCH_HISTORY_TABLES
    for table, (records, effect) in fh.FETCH_HISTORY_TABLES.items():
        assert len(records) > 20 and len(effect) > 20, f"{table} has no usable description"

# --------------------------------------------------------------------------- #
#  The toggle the operator actually sees
# --------------------------------------------------------------------------- #
#: Every string the two toggle surfaces put on screen. Keyed HERE rather than trusted
#: to the i18n ratchets, because those are MAXIMA: a shrinking untranslated population
#: moves the gate the same way a translated string does, so "the ratchet is green" is
#: not evidence that THESE six are covered.
_TOGGLE_STRINGS = (
    "Restoring a backup later",
    'A backup records what each source last served \u2014 the validators that let a server '
    'answer "nothing changed" instead of sending the whole feed again. Trusting that '
    "record is what stops a restored install re-downloading everything it already has.",
    "Trust a backup's scraping history by default",
    "Trusting it skips re-fetching what the history says was already fetched; not "
    "trusting it re-fetches everything from scratch. You can change this for any single "
    "import.",
    "Trust the backup's scraping history",
    "Trusting it skips re-fetching what the history says was already fetched; not "
    "trusting it re-fetches everything from scratch.",
)


def test_every_toggle_string_is_keyed_in_all_twelve_locales():
    import json
    import pathlib

    locales = pathlib.Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    files = sorted(locales.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {[f.name for f in files]}"

    missing: list[str] = []
    untranslated: list[str] = []
    for path in files:
        # encoding= is not optional: these files carry em dashes and curly quotes, and a
        # cp1252 default would CRASH the read rather than fail an assertion.
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _TOGGLE_STRINGS:
            if s not in data:
                missing.append(f"{path.name}: {s[:48]}...")
            elif path.name != "en.json" and data[s] == s:
                untranslated.append(f"{path.name}: {s[:48]}...")
    assert not missing, f"unkeyed toggle strings: {missing}"
    assert not untranslated, f"strings left in English: {untranslated}"


def test_the_caveat_is_VISIBLE_never_behind_the_hover():
    """The permanent informed-consent rule: the hover carries the LONG form (invariant
    #17), the visible surface keeps the caveat present. A caveat that lived only in a
    ``title`` would be a calm-UI toggle by another name."""
    import pathlib

    html = (
        pathlib.Path(__file__).resolve().parent.parent / "src" / "static" / "index.html"
    ).read_text(encoding="utf-8")

    for note_id in ("gw-trust-note", "ux-imp-trust-note"):
        at = html.index(f'id="{note_id}"')
        line_start = html.rindex("<", 0, at)
        block = html[line_start : html.index("</p>", at)]
        assert 'class="note"' in block, f"{note_id} is not rendered as a visible note"
        assert "hidden" not in block, f"{note_id} ships hidden"
        assert "not trusting it re-fetches everything from scratch" in block, (
            f"{note_id} no longer states what NOT trusting the history does -- half the "
            "choice is missing, which is the shape of a caveat that only reassures"
        )


def test_the_toggle_node_suite():
    """A source guard cannot see a live branch: ``_uxImTrust()`` answering ``false``
    rather than ``null`` for a hidden row asserts a refusal the operator never made, and
    the word ``null`` appears in the file either way. Driven as real code."""
    import pathlib
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("node not available")
    root = pathlib.Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        ["node", str(root / "tests" / "trust_history_toggle_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout

def test_the_checkboxes_escape_the_global_input_width():
    """A defect no source guard could have predicted, found in Chromium and pinned here.

    ``app.css`` styles ``input, select, textarea { width: 100% }``, and a bare
    ``<input type="checkbox">`` inherits it: both new boxes rendered ~340-360px wide,
    with the label stranded at the far end of the row. The repo already carries the
    escape (``#cust-ots``, ``#set-rerun-guide``), so this asserts BOTH halves -- that the
    stretching rule is really there (otherwise the escape is cargo cult that could be
    deleted as noise) and that each new checkbox carries it.

    Measured after the fix: 13px on all four walked surfaces
    (docs/audit/trust-history-clickthrough-2026-09-16/report.json).
    """
    import pathlib
    import re

    static = pathlib.Path(__file__).resolve().parent.parent / "src" / "static"
    css = (static / "app.css").read_text(encoding="utf-8")
    assert re.search(r"input,\s*select,\s*textarea\s*\{[^}]*width\s*:\s*100%", css), (
        "the global input width rule is gone -- re-check whether the width:auto escapes "
        "below are still needed before trusting this guard"
    )

    html = (static / "index.html").read_text(encoding="utf-8")
    for box_id in ("gw-trust-history", "ux-imp-trust"):
        at = html.index(f'id="{box_id}"')
        tag = html[html.rindex("<input", 0, at) : html.index(">", at) + 1]
        assert "width:auto" in tag, (
            f"#{box_id} has no width escape; the global `input {{width:100%}}` rule "
            f"stretches it across the row. Tag: {tag}"
        )
