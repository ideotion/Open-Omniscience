"""Fix-pass tests (audit 2026-09-08, api-backend agent): the bare ``/api/sources``
pagination trap, missing HTTP compression / cache headers, and the rate-limiter's
missing ``Retry-After``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each test is written to FAIL against the pre-fix ``src/api/main.py`` and PASS
against the fixed version — see the docstring on each test for the exact old
behaviour it would have caught.
"""

from __future__ import annotations

import asyncio
import gzip
import pathlib
import zlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.api.ratelimit import limiter
from src.database.models import Base, Source
from src.database.session import get_db


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    limiter.reset()  # isolate this file's hit-counts from whatever ran before it
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    limiter.reset()


def _seed(n: int, db_url: str) -> None:
    engine = create_engine(db_url, future=True, connect_args={"check_same_thread": False})
    Sess = sessionmaker(bind=engine, future=True)
    db = Sess()
    for i in range(n):
        db.add(
            Source(
                name=f"Source {i}",
                domain=f"s{i}.example",
                rss_url=f"https://s{i}.example/feed.xml",
                enabled=True,
                priority=0,
            )
        )
    db.commit()
    db.close()


# --------------------------------------------------------------------------- #
# (a) the bare /api/sources route ignoring its own limit/offset
# --------------------------------------------------------------------------- #


def test_bare_sources_route_honors_limit(client, tmp_path):
    """Audit finding (a): ``GET /api/sources?limit=5`` returned all 3,618 rows —
    the limit was silently ignored because the bare handler took no parameters at
    all. Against the OLD code this assertion fails (len == the full seeded count,
    not 5); against the fix it passes.
    """
    _seed(20, f"sqlite:///{tmp_path / 's.db'}")

    everything = client.get("/api/sources").json()
    assert len(everything) == 20, "default (no params) must still return every row"

    limited = client.get("/api/sources?limit=5").json()
    assert len(limited) == 5, "an explicit ?limit must actually be honoured, not ignored"

    # And offset moves the window rather than repeating the same 5 rows (id-ordered).
    page1 = client.get("/api/sources?limit=5&offset=0").json()
    page2 = client.get("/api/sources?limit=5&offset=5").json()
    assert [s["id"] for s in page1] != [s["id"] for s in page2]
    assert {s["id"] for s in page1}.isdisjoint({s["id"] for s in page2})


def test_bare_sources_route_default_unbounded_for_existing_callers(client, tmp_path):
    """The two real frontend callers (app-sources.js, app-markets.js) call this
    exact bare path with NO query params at all and expect the full array back
    to populate their dropdowns. The fix must not turn the default into a capped
    page (that would silently truncate their dropdowns — the same silent-wrong-
    answer failure mode this app refuses elsewhere).
    """
    _seed(150, f"sqlite:///{tmp_path / 's.db'}")
    r = client.get("/api/sources")
    assert r.status_code == 200
    assert len(r.json()) == 150


# --------------------------------------------------------------------------- #
# (b) no HTTP compression, no explicit static Cache-Control
# --------------------------------------------------------------------------- #


def test_static_assets_are_gzip_compressed_when_accepted(client):
    """Audit finding (b): ``curl -H 'Accept-Encoding: gzip'`` against a static
    JS bundle came back with no ``Content-Encoding`` header at all — nothing
    compressed anything. Against the OLD code (no GZipMiddleware) this fails
    (no Content-Encoding header, full uncompressed body); against the fix it
    passes and the wire bytes are actually smaller than the raw file.
    """
    r = client.get("/static/app-map.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert r.headers.get("vary", "").lower().find("accept-encoding") != -1

    # decoded content must still be byte-identical to the real file (compression
    # must be lossless, never a truncation)
    raw = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "static" / "app-map.js"
    ).read_bytes()
    assert r.content == raw

    # A client that does NOT ask for gzip must still get a plain, uncompressed
    # response (never force-compress on a client that can't decode it).
    plain = client.get("/static/app-map.js", headers={"Accept-Encoding": "identity"})
    assert plain.headers.get("content-encoding") is None
    assert plain.content == raw


async def _raw_asgi_get(path: str, accept_encoding: str) -> tuple[dict, bytes]:
    """Drive the ASGI app directly and return ``(headers, THE BYTES ON THE WIRE)``.

    Necessary because there is no other vantage point. httpx transparently
    inflates ``Response.content``, and ``Content-Length`` is absent on this
    response — StaticFiles answers with a streaming ``FileResponse``, so the gzip
    middleware takes its streaming branch and DELETES ``Content-Length`` (it
    cannot know the compressed total before the last chunk). Reading the ASGI
    messages is therefore the only place the transferred size actually exists.
    """
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"accept-encoding", accept_encoding.encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
        "app": app,
    }
    await app(scope, receive, send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return headers, body


def test_gzip_actually_shrinks_the_wire_bytes():
    """Not just a header: the bytes actually PUT ON THE WIRE for a large
    compressible asset must be smaller than the source file.

    The first version of this test gzipped the file by hand and asserted that
    ``gzip.compress(raw) < raw * 0.5`` — which is a fact about zlib, not about
    this app, and it passed identically against the pre-fix code with no
    middleware installed at all. Verified 2026-09-09 by running the file against
    a stashed ``main.py``: four of the seven tests went red and this one did not.
    """
    raw = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "static" / "app-map.js"
    ).read_bytes()
    assert len(raw) > 20_000, "pick an asset big enough for the ratio to mean something"

    headers, wire = asyncio.run(_raw_asgi_get("/static/app-map.js", "gzip"))
    assert headers.get("content-encoding") == "gzip"
    assert len(wire) < len(raw) * 0.5, (
        f"gzip put {len(wire)} bytes on the wire for a {len(raw)}-byte asset — "
        "the header says compressed but the transfer is not"
    )
    # It is a real gzip stream that inflates back to the file, byte for byte —
    # smaller AND lossless, never a truncation dressed up as compression.
    assert gzip.decompress(wire) == raw

    # The control: same asset, no gzip offered, full uncompressed size on the wire.
    plain_headers, plain_wire = asyncio.run(_raw_asgi_get("/static/app-map.js", "identity"))
    assert plain_headers.get("content-encoding") is None
    assert plain_wire == raw


def test_static_cache_control_forces_revalidation(client):
    """Audit finding (b): static assets carried ETag/Last-Modified but no
    Cache-Control, leaving freshness to browser heuristics that could skip
    revalidation entirely after an upgrade. `no-cache` (mandatory revalidation,
    not `no-store`) must be present. Non-static responses are untouched."""
    r = client.get("/static/app-map.js")
    assert r.headers.get("cache-control") == "no-cache"

    api_r = client.get("/api/health")
    assert api_r.headers.get("cache-control") != "no-cache"


# --------------------------------------------------------------------------- #
# (c) the rate-limiter's 429 carrying no Retry-After
# --------------------------------------------------------------------------- #


def test_rate_limit_429_carries_retry_after(client, tmp_path):
    """Audit finding (c): 105 rapid calls produced a genuine 429 with NO
    Retry-After header, while heavy.py's own busy-retry 429 does set one. A
    client cannot back off sensibly without it. Against the OLD handler this
    assertion fails (header is entirely absent); against the fix it is present,
    a positive integer, and no larger than the limit's own window (an hour).
    """
    _seed(5, f"sqlite:///{tmp_path / 's.db'}")
    limiter.reset()  # clean window: /api/sources is limited to 100/hour

    last = None
    for _ in range(105):
        last = client.get("/api/sources")
        if last.status_code == 429:
            break

    assert last is not None
    assert last.status_code == 429, "105 rapid calls against a 100/hour limit must trip it"
    retry_after = last.headers.get("retry-after")
    assert retry_after is not None, "a 429 must tell the client how long to back off"
    assert retry_after.isdigit(), f"Retry-After must be a plain integer, got {retry_after!r}"
    seconds = int(retry_after)
    assert 0 < seconds <= 3600, "must be a real, bounded wait for a 100/hour limit, not fabricated"


def test_rate_limit_value_itself_is_unchanged():
    """This fix must only ADD a header, never touch policy. The bare /api/sources
    route's rate limit stays exactly "100/hour" (a maintainer-reserved value per
    the fix brief — never edited here)."""
    import inspect

    import src.api.main as main_mod

    text = inspect.getsource(main_mod)
    route_at = text.index('@app.get("/api/sources", response_model=list)')
    following = text[route_at : route_at + 200]
    assert '@limiter.limit("100/hour")' in following


# --------------------------------------------------------------------------- #
# (b2) the risk the compression fix carries, pinned
# --------------------------------------------------------------------------- #


def test_gzip_is_the_outermost_middleware():
    """It must compress the FINAL response — after the security-header, CSRF,
    monitoring and rate-limit layers have added theirs — rather than something an
    inner layer might still re-serialize.

    Starlette's ``add_middleware`` inserts at position 0 of ``user_middleware`` and
    the stack is built by wrapping in reverse, so index 0 is the OUTERMOST layer
    and the LAST registration wins. That is an ordering fact about registration
    order in one source file, which is exactly the kind of thing a later edit
    moves without noticing.
    """
    from starlette.middleware.gzip import GZipMiddleware as _GZip

    assert app.user_middleware[0].cls is _GZip, (
        "GZipMiddleware is no longer outermost — it must stay the LAST "
        f"add_middleware call in src/api/main.py; found {app.user_middleware[0].cls}"
    )


def test_gzip_flushes_every_chunk_of_a_streaming_response():
    """THE RISK THIS FIX CARRIES, pinned as a test rather than as a comment.

    The app streams LLM tokens as ``application/x-ndjson``
    (``src/api/llm.py``, ``src/api/ai.py``) — and unlike ``text/event-stream``,
    that media type is NOT in Starlette's ``DEFAULT_EXCLUDED_CONTENT_TYPES``, so
    those live streams now go through gzip. A deflate stream that is not flushed
    per chunk accumulates in zlib's window and delivers nothing until several
    kilobytes have piled up, which for token-by-token output means a reply that
    appears to hang and then arrives all at once. The chat would look broken, and
    nothing in the app would report an error.

    Starlette 1.6.0's ``GZipResponder._compress_body`` calls
    ``flush(zlib.Z_SYNC_FLUSH)`` on every chunk with ``more_body=True``, so each
    chunk is independently inflatable the moment it is sent — measured here, five
    chunks in and five decodable chunks out, rather than trusted from the source.
    A future Starlette bump that drops that flush would silently reintroduce the
    stall; this is what would catch it.
    """
    from starlette.applications import Starlette
    from starlette.middleware.gzip import GZipMiddleware
    from starlette.responses import StreamingResponse
    from starlette.routing import Route

    chunks = [b'{"tok":"chunk-%d"}\n' % i for i in range(5)]

    async def _ndjson(_request):
        async def gen():
            for c in chunks:
                yield c
                await asyncio.sleep(0)

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    probe = Starlette(routes=[Route("/s", _ndjson)])
    probe.add_middleware(GZipMiddleware, minimum_size=500)

    async def _drive():
        sent: list[dict] = []
        first = {"pending": True}

        async def receive():
            # One request, then block. Returning http.request in a loop spins
            # StreamingResponse's disconnect listener; returning http.disconnect
            # would cancel the very stream being measured. The response's own
            # task group cancels this when the body ends.
            if first["pending"]:
                first["pending"] = False
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        await probe(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/s",
                "raw_path": b"/s",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"host", b"127.0.0.1"), (b"accept-encoding", b"gzip")],
                "client": ("127.0.0.1", 50000),
                "server": ("127.0.0.1", 8000),
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(_drive())
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert headers.get("content-encoding") == "gzip", "the premise: this stream IS gzipped"

    bodies = [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    delivered = [decomp.decompress(b) for b in bodies]

    # THE ASSERTION: each source chunk becomes readable at its OWN wire message,
    # not withheld until the stream ends. Position i must carry chunk i.
    for i, expected in enumerate(chunks):
        assert delivered[i] == expected, (
            f"chunk {i} was not flushed at its own message — gzip is buffering a "
            f"live token stream. Delivered so far: {delivered[: i + 1]!r}"
        )
