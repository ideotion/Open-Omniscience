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
import tempfile
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


def test_a_streamed_member_never_sits_whole_in_ram(monkeypatch):
    """The defect itself, asserted structurally rather than by measuring RSS (an RSS
    assertion on a shared CI box is the flaky shape this repo's ledger already records).

    THE PROXY THIS TEST USES CHANGED WHEN D5 LANDED, and the reason is worth stating.
    B2's first version asserted that reads and writes INTERLEAVE -- chunk in, chunk
    straight out to the archive -- which was a fine proxy for "the member is never held
    whole" while the writer piped directly into the zip. D5's per-member cap cannot work
    that way: a member's final size is unknown until its last chunk, and the cap cannot
    be enforced by truncating mid-write, because half a JSON document is invalid and
    hides its own loss. So the writer now spools.

    The property that actually mattered was never the interleaving -- it was that RAM
    stays bounded by a CONSTANT rather than by the member's size. A SpooledTemporaryFile
    delivers exactly that, and this asserts it directly: past the spool limit the buffer
    ROLLS OVER to disk, so the 73.2 MB member that pushed RSS up by 3.4 GB could not sit
    in memory today no matter how large it grew. Asserting the real property beats
    asserting a proxy that has stopped tracking it."""
    from src.api import diagnostics as dg

    monkeypatch.setenv("OO_DIAG_MEMBER_MAX_MB", "0")        # no cap: exercise the big path
    monkeypatch.setattr(dg, "_MEMBER_SPOOL_MAX", 1024)      # spill past 1 KiB

    made: list = []
    real_spooled = tempfile.SpooledTemporaryFile

    def _watching(*a, **kw):
        f = real_spooled(*a, **kw)
        made.append(f)
        return f

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", _watching)

    chunks = ["q" * 4096 for _ in range(8)]                 # 32 KiB, 32x the spool limit
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _write_member(zf, "big.json", _FakeStreamed(chunks))

    assert made, "the writer did not spool at all"
    # `_rolled` stays True on the object after close: it records that the buffer
    # exceeded _MEMBER_SPOOL_MAX and moved to disk, i.e. RAM was bounded by the
    # CONSTANT and not by the member's size.
    assert getattr(made[0], "_rolled", False) is True, (
        "the streamed member stayed entirely in RAM -- that is the materialising shape "
        "B2 removed; the spool must roll over to disk past _MEMBER_SPOOL_MAX"
    )
    assert n == 32768
    with zipfile.ZipFile(buf) as zf:
        assert zf.read("big.json") == b"q" * 32768          # and round-trips intact


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


# --------------------------------------------------------------------------- #
#  D5 (maintainer request): a per-member byte cap, so no single member can make
#  the whole archive unsendable again
# --------------------------------------------------------------------------- #


def _read_names(buf):
    with zipfile.ZipFile(buf) as zf:
        return zf.namelist()


def test_an_over_cap_streamed_member_is_omitted_with_a_record_never_truncated(monkeypatch):
    """The maintainer could not upload the bundle because ONE member reached 73.2 MB.
    B2 fixed that member; this stops the NEXT one, whichever it turns out to be.

    The member must be OMITTED WITH A RECORD, never truncated: half a JSON document is
    invalid, so truncation would cost the operator the member AND the ability to tell
    anything was lost."""
    monkeypatch.setenv("OO_DIAG_MEMBER_MAX_MB", "0.001")      # 1,048 bytes
    chunks = ["x" * 500 for _ in range(10)]                     # 5,000 bytes

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _write_member(zf, "huge.json", _FakeStreamed(chunks))

    names = _read_names(buf)
    assert "huge.json" not in names, "the over-cap member must not be written at all"
    assert "huge.json.omitted.json" in names

    with zipfile.ZipFile(buf) as zf:
        rec = json.loads(zf.read("huge.json.omitted.json"))
    assert rec["omitted"] is True
    assert rec["member"] == "huge.json"
    assert rec["bytes_uncompressed"] == 5000          # its REAL size, stated
    assert rec["cap_bytes"] == 1048
    assert "OO_DIAG_MEMBER_MAX_MB" in rec["how_to_get_it"]
    # The manifest's `bytes` must describe what was ACTUALLY written, so the archive's
    # own accounting stays true rather than reporting a member it does not contain.
    assert n == len(zf.read("huge.json.omitted.json")) if False else n == len(
        json.dumps(rec, ensure_ascii=False, indent=2).encode("utf-8")
    )


def test_an_over_cap_plain_member_is_omitted_too(monkeypatch):
    """The cap is the BUILDER's, not the streaming path's -- a plain dict member that
    runs large is exactly as unsendable."""
    monkeypatch.setenv("OO_DIAG_MEMBER_MAX_MB", "0.001")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_member(zf, "big.json", {"payload": ["y" * 100 for _ in range(50)]})
    assert "big.json.omitted.json" in _read_names(buf)


def test_a_member_within_the_cap_is_untouched(monkeypatch):
    """The cap must not change the healthy path -- every member measured in the field
    after B2 is under 1 MB, so the common case must round-trip byte-for-byte."""
    monkeypatch.setenv("OO_DIAG_MEMBER_MAX_MB", "12")
    chunks = ['{"ok":', "true}"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _write_member(zf, "fine.json", _FakeStreamed(chunks))
    with zipfile.ZipFile(buf) as zf:
        assert json.loads(zf.read("fine.json")) == {"ok": True}
    assert n == len("".join(chunks))
    assert "fine.json.omitted.json" not in _read_names(buf)


def test_the_cap_can_be_disabled(monkeypatch):
    """0 disables it -- an operator who wants everything must be able to say so."""
    monkeypatch.setenv("OO_DIAG_MEMBER_MAX_MB", "0")
    chunks = ["z" * 2000]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_member(zf, "unbounded.json", _FakeStreamed(chunks))
    assert "unbounded.json" in _read_names(buf)
