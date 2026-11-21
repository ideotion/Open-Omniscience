"""Row 283 (row 72's unowned part): a law source refused by its robots.txt is named as such, never as failed or empty.

On OOS-1, 7 or 8 of the 23 law sources are refused by their own robots.txt. Nothing was requested from them, so nothing
failed, yet three surfaces said otherwise: the Law table badged them "robots-blocked" shorthand, "Add & track" printed the
stored "fetch error: robots.txt disallows ..." text, and "Track changes now" counted them in its "N errors". All three are
read-side words now: the badge and the add message read "blocked by the site's robots.txt" (or "robots.txt not readable"
for the fail-closed refusal), and the toast takes the robots refusals out of its error count and names them. The fetch
path is unchanged: the tracker only labels the exception the fetcher already raised.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.law import track as law_track
from tests.js_source_helper import function_source, read_static

_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
_KEYS = (
    "blocked by the site's robots.txt",
    "{n} blocked by the site's robots.txt",
    "{n} not fetched: the site's robots.txt could not be read",
)
_FAILURE_WORDS = re.compile(r"fail|error|empty|no usable", re.IGNORECASE)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def fetch(self, url, *, require_html=True, **_kw):
        raise self.exc


def _robots(kind: str, url: str = "https://ex.test/a"):
    from src.ingest import FetchFailed, RobotsDisallowed, RobotsUnavailable

    if kind == "blocked":
        return RobotsDisallowed(f"robots.txt disallows {url}")
    if kind == "unread":
        return RobotsUnavailable(f"robots.txt for {url} could not be determined (unreachable); refusing to fetch")
    return FetchFailed("boom")


@pytest.mark.parametrize(("kind", "key"), [("blocked", "robots_blocked"), ("unread", "robots_unread")])
def test_track_watched_counts_a_robots_refusal_apart(db, kind, key):
    db.add(LawDocument(jurisdiction="uk", title="A", url="https://ex.test/a"))
    db.commit()
    tally = law_track.track_watched(db, _Raises(_robots(kind)))
    # The old field is unchanged (skipped_offline's convention); the new key lets a caller take it out and name it.
    assert tally["errors"] == 1 and tally[key] == 1
    other = {"robots_blocked", "robots_unread"} - {key}
    assert not other & tally.keys()


def test_a_real_failure_carries_no_robots_key(db):
    db.add(LawDocument(jurisdiction="uk", title="A", url="https://ex.test/a"))
    db.commit()
    tally = law_track.track_watched(db, _Raises(_robots("failed")))
    assert tally["errors"] == 1
    assert "robots_blocked" not in tally and "robots_unread" not in tally


def test_the_document_result_says_which_robots_refusal(db):
    doc = LawDocument(jurisdiction="uk", title="A", url="https://ex.test/a")
    db.add(doc)
    db.commit()
    assert law_track.track_document(db, _Raises(_robots("blocked")), doc)["robots"] == "blocked"
    assert law_track.track_document(db, _Raises(_robots("unread")), doc)["robots"] == "unread"
    assert "robots" not in law_track.track_document(db, _Raises(_robots("failed")), doc)


def test_both_batch_trackers_tally_it():
    # auto_track_due's pass needs the scheduler's due-ness and politeness; its tally branch is the same code.
    for fn in (law_track.track_watched, law_track.auto_track_due):
        assert '_ROBOTS_TALLY_KEY[res["robots"]]' in inspect.getsource(fn), fn.__name__


def test_the_words_are_keyed_in_all_twelve_languages():
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in _KEYS:
            assert data.get(key), (path.stem, key)
        assert "robots-blocked" not in data, path.stem  # the shorthand is gone, so nothing can draw it again


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_no_robots_verdict_is_labelled_a_failure():
    js = read_static("app-gov-law.js")
    script = (
        "const window = {};\n"
        + function_source(js, "lawVerdictLabel")
        + "\nconsole.log(JSON.stringify([lawVerdictLabel('robots_blocked'), lawVerdictLabel('robots_unread')]));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout  # noqa: S607
    blocked, unread = json.loads(out)
    assert blocked == "blocked by the site's robots.txt"
    assert unread == "robots.txt not readable"
    assert not _FAILURE_WORDS.search(blocked) and not _FAILURE_WORDS.search(unread)


def test_the_add_message_and_the_track_toast_name_it():
    js = read_static("app-gov-law.js")
    track = function_source(js, "lawTrack")
    assert "r.robots_blocked" in track and "r.robots_unread" in track
    assert "{n} blocked by the site's robots.txt" in track
    assert "{n} not fetched: the site's robots.txt could not be read" in track
    assert "(r.errors || 0) - rb - ru" in track, "the robots refusals leave the error count"
    assert 'r.verdict === "robots_blocked"' in js and "lawVerdictLabel(r.verdict)" in js
