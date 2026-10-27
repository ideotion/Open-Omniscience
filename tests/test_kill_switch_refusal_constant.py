"""The kill switch's refusal sentence is defined ONCE and the reader is built from it (ruling R317).

The sentence was a string literal at five raise sites in ``src/ingest/__init__.py`` and one in ``src/safety/fetcher.py``, with the reader
(``fetch_verdict._OFFLINE_RE``) and the law tracker each holding their own copy of its opening words. A rewording at one writer would have
left the readers matching a sentence nobody raises any more, and the failure would have been silent: a refusal read as the HOST's failure
(R293, R297, R298 are all that one mistake). Now ``KILL_SWITCH_REFUSAL`` is the sentence, ``KILL_SWITCH_REFUSAL_HEAD`` its opening words, every
writer says the constant, and the reader's first alternative is built from the head.

A subclass of ``FetchFailed`` was considered and refused: most callers classify STORED strings (verdict JSON, queue state, diagnostics) and the
wrapped shapes carry the sentence inside another exception's text, so the text match has to stay; this only stops the copies from drifting.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    activate_kill_switch,
    clear_kill_switch,
    fetch_verdict,
    kill_switch_active,
)
from src.ingest.fetch_verdict import (
    KILL_SWITCH_REFUSAL,
    KILL_SWITCH_REFUSAL_HEAD,
    classify_fetch_failure,
    is_kill_switch_refusal,
)

_SRC = Path(__file__).resolve().parent.parent / "src"
_TAIL = "collection stopped by operator"
_HEAD_WORDS = "kill switch is active"
_DEFINITION = "src/ingest/fetch_verdict.py"
# The only other files under ``src/`` that spell the opening words, each with its OWN sentence (not the fetcher's refusal), and why. A file added
# here is a conscious decision that it is not a second copy of the reader's pattern (``src/law/track.py`` was one, and now says the constant).
_OWN_SENTENCES = {
    "src/wiki/ores.py": "the ORES scorer's note: 'the network kill switch is active (airplane mode)'",
    "src/wiki/stream.py": "the dump stream's stop: 'network kill switch is active (airplane mode) -- {doing} was refused'",
}
# A Stop through an HTTP proxy, as OSM measured it (R320): the request error is wrapped, not our sentence.
_PROXY_SHAPED_STOP = (
    "request error for https://h.test/a: ('Connection aborted.', AirplaneModeError(\"airplane mode is engaged: refusing a network "
    "connection to 'h.test'. No packet leaves the machine while offline\"))"
)

# What the pattern said BEFORE the head became a constant, copied here so the change is proved to be a pure refactor of the reader.
_OLD_OFFLINE_RE = re.compile(
    r"^\s*(?:[\w.]+:\s*)?(?:network kill switch is active|airplane mode is engaged: refusing a network connection)\b"
    r"|^\s*request error for \S+: .*Failed to establish a new connection: airplane mode is engaged: refusing a network connection"
    r"|^\s*cannot resolve host (?:'[^'\s\\]*'|\"[^\"\s\\]*\"): airplane mode is engaged: refusing a network connection",
    re.IGNORECASE | re.DOTALL,
)


@pytest.fixture(autouse=True)
def _switch_clear():
    was = kill_switch_active()
    clear_kill_switch()
    yield
    (activate_kill_switch if was else clear_kill_switch)()


def _string_constants(path: Path):
    """Every string (and bytes) constant in the code of ``path``, lower-cased, docstrings left out: a docstring quotes the sentence, it does not
    raise it, and a lesson or a comment that quotes it must not fail the scan. What it does NOT see: a sentence assembled from pieces (``+``, an
    f-string placeholder in the middle), which a reader of the diff has to catch."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in docstrings:
            if isinstance(node.value, bytes):
                yield node.value.decode("latin-1").lower()
            elif isinstance(node.value, str):
                yield node.value.lower()


def test_the_constants_say_what_the_sentence_always_said():
    assert KILL_SWITCH_REFUSAL == "network kill switch is active -- collection stopped by operator"
    assert KILL_SWITCH_REFUSAL.startswith(KILL_SWITCH_REFUSAL_HEAD) and KILL_SWITCH_REFUSAL_HEAD == "network kill switch is active"
    assert is_kill_switch_refusal(KILL_SWITCH_REFUSAL) and classify_fetch_failure(KILL_SWITCH_REFUSAL) == "offline"


def _holders(needle: str) -> list[str]:
    return sorted(
        str(path.relative_to(_SRC.parent)).replace("\\", "/")
        for path in _SRC.rglob("*.py")
        if any(needle in value for value in _string_constants(path))
    )


def test_no_other_file_under_src_spells_the_sentence_out():
    """A literal copy of the sentence is where the drift would start. The scan reads code, case-folded, bytes included, so a docstring or a
    comment that quotes the sentence does not fail it and a capitalised or bytes copy does not slip past it."""
    assert _holders(_TAIL) == [_DEFINITION], "the refusal sentence is spelled out outside its definition"
    elsewhere = [  # a JS, HTML, JSON or YAML file under src/ is not a Python module, but it could carry the sentence as well
        str(path.relative_to(_SRC.parent)).replace("\\", "/")
        for path in _SRC.rglob("*")
        if path.suffix in {".js", ".html", ".json", ".yml", ".yaml"} and _TAIL in path.read_text(encoding="utf-8", errors="replace").lower()
    ]
    assert elsewhere == [], f"the refusal sentence is spelled out in a non-Python file: {elsewhere}"


def test_no_other_file_under_src_holds_the_opening_words_as_a_pattern_of_its_own():
    """The shape ``src/law/track.py`` had: a second module keeps the HEAD of the sentence to recognise it, and a rewording at the definition
    leaves that copy matching a sentence nobody raises. EVERY file under ``src/`` is scanned, not a list of the ones known today; the files
    that hold the words for a sentence of their own are named above, each with its reason."""
    assert _holders(_HEAD_WORDS) == sorted([_DEFINITION, *_OWN_SENTENCES]), (
        "a file under src/ spells the refusal's opening words; say KILL_SWITCH_REFUSAL / KILL_SWITCH_REFUSAL_HEAD instead, or, if it is a "
        "sentence of its own, add it to _OWN_SENTENCES with the reason"
    )


def test_every_raise_site_raises_the_constant_and_the_reader_reads_it():
    """Each writer is DRIVEN with the switch engaged (the sites are not the same code path), not matched by name."""
    from src.safety.fetcher import GuardedSession, NetworkBlocked

    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0)
    activate_kill_switch()
    raised: dict[str, BaseException] = {}
    for label, call, kind in (
        ("fetch", lambda: f.fetch("https://h.test/a"), FetchFailed),
        ("declared_sitemaps", lambda: f.declared_sitemaps("https://h.test/a"), FetchFailed),
        ("_guard_target", lambda: f._guard_target("h.test"), FetchFailed),
        ("_guarded_redirect_get", lambda: f._guarded_redirect_get("https://h.test/robots.txt"), FetchFailed),
        ("GuardedSession.request", lambda: GuardedSession().get("https://h.test/a"), NetworkBlocked),
    ):
        with pytest.raises(kind) as caught:
            call()
        raised[label] = caught.value
    for label, exc in raised.items():
        assert str(exc) == KILL_SWITCH_REFUSAL, label
        assert is_kill_switch_refusal(str(exc)) and classify_fetch_failure(str(exc)) == "offline", label


def test_the_robots_read_site_raises_the_constant_when_the_switch_cuts_the_read(tmp_path):
    """The fifth FetchFailed site (R297), reached only when the switch is set after the earlier checks passed."""
    from urllib.parse import urlparse

    import requests

    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, robots_cache_path=tmp_path / "robots.json")
    f._guard_target = lambda host: None  # type: ignore[method-assign]

    def cut_off(url, **_kw):
        activate_kill_switch()
        raise requests.ConnectionError("cut")

    f._guarded_redirect_get = cut_off  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as caught:
        f._get_robots("https://h.test", urlparse("https://h.test/a"))
    assert str(caught.value) == KILL_SWITCH_REFUSAL


def test_the_reader_is_built_from_the_head_and_accepts_exactly_what_it_accepted():
    assert re.escape(KILL_SWITCH_REFUSAL_HEAD) in fetch_verdict._OFFLINE_RE.pattern
    corpus = [
        KILL_SWITCH_REFUSAL,
        "FetchFailed: " + KILL_SWITCH_REFUSAL,
        "  " + KILL_SWITCH_REFUSAL,
        "NETWORK KILL SWITCH IS ACTIVE -- collection stopped",
        "network kill switch is active",
        "network kill switch is active (airplane mode) -- a download was refused",
        "network kill switch is actively refusing",
        "the network kill switch is active",
        "xnetwork kill switch is active",
        "HTTP 503 for https://h.test/a (server said: " + KILL_SWITCH_REFUSAL + ")",
        "redirect to unsupported URL: 'ftp://h.test/" + KILL_SWITCH_REFUSAL + "'",
        "airplane mode is engaged: refusing a network connection to 'h.test'. No packet leaves the machine while offline",
        "request error for https://h.test/a: HTTPSConnectionPool(host='h.test'): Failed to establish a new connection: "
        "airplane mode is engaged: refusing a network connection to 'h.test'",
        "cannot resolve host 'h.test': airplane mode is engaged: refusing a network connection to 'h.test'",
        "cannot resolve host 'a b': airplane mode is engaged: refusing a network connection to 'a b'",
        "cannot resolve host 'h.test': [Errno -2] Name or service not known",
        "HTTPSConnectionPool(host='a.example', port=443): Max retries exceeded with url: /robots.txt (Caused by NewConnectionError(...))",
        _PROXY_SHAPED_STOP,
        "",
        "the kill switch of the CDN fired",
    ]
    assert len(corpus) == 20
    for text in corpus:
        assert bool(fetch_verdict._OFFLINE_RE.match(text)) == bool(_OLD_OFFLINE_RE.match(text)), text
    assert fetch_verdict._OFFLINE_RE.flags == _OLD_OFFLINE_RE.flags


def test_a_stop_through_an_http_proxy_is_not_widened_into_a_match():
    """R320: a Stop through an HTTP proxy reaches a caller as a requests error wrapping the guard's sentence in a ``ConnectionError`` tuple.
    That is the wrapped shape the start anchor (R298) exists to refuse, so the reader does NOT recognise it; the callers that can meet it
    read ``kill_switch_active()`` after each check instead. Building the first alternative from a constant must not change that."""
    assert not is_kill_switch_refusal(_PROXY_SHAPED_STOP)
    assert classify_fetch_failure(_PROXY_SHAPED_STOP) != "offline"
    assert not fetch_verdict._OFFLINE_RE.match(_PROXY_SHAPED_STOP)



def test_the_law_tracker_reads_the_head_and_not_the_wider_predicate():
    """``track_document`` tests ``startswith(KILL_SWITCH_REFUSAL_HEAD)``, which is NARROWER than ``is_kill_switch_refusal`` on purpose (R293, and
    the PR that made the constant says so). The socket guard's sentence as ``requests`` wraps it is a refusal for the predicate, and with the
    switch CLEAR again the tracker must still read it as an ordinary failed request that stamps its back-off: moving the tracker onto the
    predicate is a widening of R293 and a decision of its own, so this pins today's behaviour until someone makes it."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, LawDocument
    from src.law.track import track_document

    wrapped = (
        "request error for https://gazette.test/act1: HTTPSConnectionPool(host='gazette.test'): Failed to establish a new connection: "
        "airplane mode is engaged: refusing a network connection to 'gazette.test'"
    )
    assert is_kill_switch_refusal(wrapped), "premise: the predicate reads this shape as a refusal"

    class _Raises:
        def __init__(self, exc):
            self.exc = exc

        def fetch(self, url, **_kw):
            raise self.exc

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    doc = LawDocument(
        jurisdiction="uk", title="Act", url="https://gazette.test/act1", watched=True, last_status="unchanged",
        last_checked_at=datetime.now(UTC) - timedelta(days=3),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    before = doc.last_checked_at  # read back from the store, the way the tracker sees it

    out = track_document(db, _Raises(FetchFailed(wrapped)), doc)  # the switch is CLEAR here
    db.refresh(doc)
    assert out["status"] == "error" and "offline" not in out
    assert doc.last_checked_at > before, "a failed request made by the tracker keeps its stamp"

    # control: the fetcher's own sentence IS the refusal that made no request, and restores the stamp
    doc.last_checked_at = before
    db.commit()
    out = track_document(db, _Raises(FetchFailed(KILL_SWITCH_REFUSAL)), doc)
    db.refresh(doc)
    assert out["offline"] is True and doc.last_checked_at == before
