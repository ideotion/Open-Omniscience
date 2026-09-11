"""The all-diagnostics archive writes a streamed member WITHOUT materialising it (B2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. `keyword-log-digest.json` reached 73.2 MB -- 84x the
next-largest member and ~96% of the archive -- and the member entry recorded
`rss_peak_rise_kb 3,402,592` (+3.4 GB) on a machine with `mem_total_mb 4093.8`, whose
PREVIOUS session had already ended `unclean-end` at peak RSS 4158.0 MB against 1024.0 MB
of swap. Capping the member is the real fix (see the families cap in
test_young_corpus_and_diagnostics.py); this is the net beneath it, so the NEXT large
member does not repeat the shape.

The old path was `zf.writestr(name, _member_bytes(value))`, which held three copies of
the member at once: the list of chunks the drain accumulates, the joined bytes it
returns, and whatever writestr buffers.
"""

from __future__ import annotations

import io
import json
import zipfile

from src.api.diagnostics import _write_member


class _FakeStreamed:
    """Stands in for a StreamingResponse: the archive writer recognises members by
    their `body_iterator`, exactly as `_member_bytes` always has."""

    def __init__(self, chunks, *, on_chunk=None):
        self._chunks = list(chunks)
        self._on_chunk = on_chunk

    @property
    def body_iterator(self):
        async def _gen():
            for c in self._chunks:
                if self._on_chunk is not None:
                    self._on_chunk(c)
                yield c

        return _gen()


def test_streamed_member_round_trips_and_reports_uncompressed_bytes():
    buf = io.BytesIO()
    chunks = ['{"a":', "1,", '"b":2}']
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _write_member(zf, "member.json", _FakeStreamed(chunks))

    expected = "".join(chunks).encode("utf-8")
    assert n == len(expected), "the manifest's `bytes` must be the UNCOMPRESSED length"
    with zipfile.ZipFile(buf) as zf:
        assert zf.read("member.json") == expected
        assert json.loads(zf.read("member.json")) == {"a": 1, "b": 2}


def test_streamed_member_is_written_chunk_by_chunk_never_accumulated():
    """The defect itself, asserted structurally rather than by measuring RSS (an RSS
    assertion on a shared CI box is the flaky shape this repo's ledger already records).

    If the writer were still accumulating, EVERY chunk would be pulled from the iterator
    before the first byte reached the archive. Interleaving proves it streams."""
    order: list[str] = []
    chunks = [f"chunk-{i:02d}-" for i in range(8)]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        real_open = zf.open

        def _tracking_open(name, mode="r", **kw):
            fh = real_open(name, mode, **kw)
            real_write = fh.write

            def _w(b):
                order.append("write")
                return real_write(b)

            fh.write = _w  # type: ignore[method-assign]
            return fh

        zf.open = _tracking_open  # type: ignore[method-assign]
        _write_member(
            zf, "streamed.txt", _FakeStreamed(chunks, on_chunk=lambda c: order.append("read"))
        )

    # Accumulate-then-write would read all 8 before writing any: "read"*8 then "write"*n.
    first_write = order.index("write")
    reads_before_first_write = order[:first_write].count("read")
    assert reads_before_first_write <= 1, (
        "the member was drained before anything was written -- that is the "
        f"materialising shape B2 removed (order={order[:12]})"
    )
    assert order.count("read") == len(chunks)


def test_non_streamed_members_are_unchanged():
    """A plain dict / JSONResponse member still goes through writestr -- the fix is
    scoped to the streamed path and must not alter the others."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _write_member(zf, "plain.json", {"hello": "world"})
    with zipfile.ZipFile(buf) as zf:
        payload = zf.read("plain.json")
    assert json.loads(payload) == {"hello": "world"}
    assert n == len(payload)
