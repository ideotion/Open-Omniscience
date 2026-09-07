"""
The ONE consented "refresh exact sizes" read (no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The surface these guards protect replaced a per-edition "Estimate size" button
that had three separate defects: it egressed with NO network-consent popup
(invariant #14), it read only the FIRST of a multi-select picker's editions, and
every failure -- airplane mode included -- printed one message, so a refusal by
THIS machine read as a dump host that would not answer.

Each guard therefore pins a property, not a shape: the batch really covers the
selection, a refusal is named as the refusal it is, and an unread size is never
a zero.
"""

from __future__ import annotations

import pytest

from src.safety.fetcher import NetworkBlocked
from src.wiki.dumps import MAX_SIZE_PROBE_EDITIONS, DumpDownloadManager


class _Resp:
    def __init__(self, headers=None):
        self.headers = headers if headers is not None else {}


def _manager(tmp_path, head):
    m = DumpDownloadManager(base_dir=tmp_path, http_head=head)
    # Compress the throttle to match the compressed batch: a test that scales one
    # dimension down for runtime must scale every constant that dimension is
    # compared against, or it silently models a case that cannot occur.
    m._probe_interval_s = 0.0
    return m


# --------------------------------------------------------------------------- #
# the multi-select defect: one action, every selected edition
# --------------------------------------------------------------------------- #


def test_a_batch_reads_every_selected_edition_not_only_the_first(tmp_path):
    seen: list[str] = []

    def head(url):
        seen.append(url)
        return _Resp({"Content-Length": str(1000 + len(seen))})

    m = _manager(tmp_path, head)
    out = list(m.probe_sizes(["en", "fr", "de"]))

    assert [r.wiki for r in out] == ["en", "fr", "de"]
    assert [r.size_bytes for r in out] == [1001, 1002, 1003]
    # Three editions selected, three requests made -- the defect this replaces
    # made exactly one and reported it as though it described the selection.
    assert len(seen) == 3
    assert all(r.reason is None for r in out)


def test_a_repeated_edition_is_read_once(tmp_path):
    calls: list[str] = []

    def head(url):
        calls.append(url)
        return _Resp({"Content-Length": "7"})

    m = _manager(tmp_path, head)
    out = list(m.probe_sizes(["en", "EN", " en ", "fr"]))
    assert [r.wiki for r in out] == ["en", "fr"]
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# negative space: an absent size is NAMED, and is never a zero
# --------------------------------------------------------------------------- #


def test_airplane_mode_is_named_as_airplane_and_never_becomes_a_size(tmp_path):
    """The kill switch refusing a request is a fact about THIS machine.

    Reporting it as ``unreachable`` would send an operator hunting a dump host
    that is perfectly fine; reporting it as ``0`` would publish a measurement
    nobody took. Both directions are asserted here because the shipped code has
    one branch for each.
    """

    def head(url):
        raise NetworkBlocked("network kill switch is active")

    m = _manager(tmp_path, head)
    (r,) = list(m.probe_sizes(["en"]))
    assert r.reason == "airplane"
    assert r.size_bytes is None
    assert r.size_bytes != 0


def test_a_transport_failure_is_unreachable_and_not_airplane(tmp_path):
    """The twin of the guard above: the two absences must not collapse together.

    Without this, "name the airplane case" is satisfiable by naming EVERY
    failure ``airplane``, which is the same conflation pointing the other way.
    """

    def head(url):
        raise OSError("connection reset")

    m = _manager(tmp_path, head)
    (r,) = list(m.probe_sizes(["en"]))
    assert r.reason == "unreachable"
    assert r.size_bytes is None


def test_a_host_that_publishes_no_size_is_named_as_such(tmp_path):
    m = _manager(tmp_path, lambda url: _Resp({}))
    (r,) = list(m.probe_sizes(["en"]))
    assert r.reason == "no-content-length"
    assert r.size_bytes is None


def test_an_unparseable_content_length_is_a_gap_not_a_zero(tmp_path):
    m = _manager(tmp_path, lambda url: _Resp({"Content-Length": "not-a-number"}))
    (r,) = list(m.probe_sizes(["en"]))
    assert r.size_bytes is None
    assert r.reason == "no-content-length"


def test_an_unusable_edition_code_never_becomes_a_request(tmp_path):
    """It is reported, not dropped -- and no HEAD is attempted for it.

    Asserting only the reason would pass for an implementation that built a
    traversal-shaped URL, fetched it, and then labelled the failure; the call
    counter is what makes the claim about egress rather than about wording.
    """
    calls: list[str] = []

    def head(url):
        calls.append(url)
        return _Resp({"Content-Length": "5"})

    m = _manager(tmp_path, head)
    out = list(m.probe_sizes(["../../etc/passwd", "fr"]))
    assert [r.wiki for r in out] == ["../../etc/passwd", "fr"]
    assert out[0].reason == "invalid-edition"
    assert out[0].size_bytes is None
    assert out[0].url == ""
    assert len(calls) == 1 and "frwiki" in calls[0]


# --------------------------------------------------------------------------- #
# politeness and bounds
# --------------------------------------------------------------------------- #


def test_the_batch_spaces_its_requests_across_the_one_host(tmp_path):
    """N-1 gaps for N requests: spacing BETWEEN calls, never a leading wait."""
    slept: list[float] = []
    m = DumpDownloadManager(base_dir=tmp_path, http_head=lambda url: _Resp({"Content-Length": "1"}))
    m._probe_interval_s = 0.25
    m._sleep = slept.append

    list(m.probe_sizes(["en", "fr", "de"]))
    assert slept == [0.25, 0.25]

    slept.clear()
    list(m.probe_sizes(["en"]))
    assert slept == []


def test_the_batch_is_bounded(tmp_path):
    calls: list[str] = []

    def head(url):
        calls.append(url)
        return _Resp({"Content-Length": "1"})

    m = _manager(tmp_path, head)
    codes = [f"x{i}" for i in range(MAX_SIZE_PROBE_EDITIONS + 5)]
    out = list(m.probe_sizes(codes))
    assert len(out) == MAX_SIZE_PROBE_EDITIONS
    assert len(calls) == MAX_SIZE_PROBE_EDITIONS


def test_probe_size_and_probe_sizes_share_one_implementation(tmp_path):
    """Two functions answering one question from different sources drift.

    ``probe_size`` keeps its two-state ``int | None`` contract for its existing
    callers, and the guard is that it reports the SAME reading the batch does.
    """
    m = _manager(tmp_path, lambda url: _Resp({"Content-Length": "4242"}))
    (r,) = list(m.probe_sizes(["en"]))
    assert m.probe_size("en", "pages-articles-multistream") == r.size_bytes == 4242

    blocked = _manager(tmp_path, lambda url: (_ for _ in ()).throw(NetworkBlocked("off")))
    assert blocked.probe_size("en") is None


# --------------------------------------------------------------------------- #
# the endpoint: anti-capping, and the same refusal /dumps/probe already makes
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_the_endpoint_names_the_editions_it_did_not_probe(client, monkeypatch):
    """A cap may bound which editions were READ; it may never bound what is
    reported. A short answer that reads as a complete one is the anti-capping
    defect this project names elsewhere."""
    import src.wiki.dumps as dumps

    class _Fake:
        def probe_sizes(self, wikis, kind, **kw):
            return [
                dumps.DumpSizeReading(wiki=w, kind=kind, url="", size_bytes=1)
                for w in list(wikis)[:MAX_SIZE_PROBE_EDITIONS]
            ]

    monkeypatch.setattr(dumps, "get_manager", lambda: _Fake())
    codes = [f"a{i}" for i in range(MAX_SIZE_PROBE_EDITIONS + 3)]
    r = client.get("/api/wiki/dumps/sizes", params={"wikis": ",".join(codes)})
    assert r.status_code == 200
    d = r.json()
    assert d["requested"] == len(codes)
    assert d["probed"] == MAX_SIZE_PROBE_EDITIONS
    assert d["not_probed"] == codes[MAX_SIZE_PROBE_EDITIONS:]
    assert d["not_probed"], "the surplus must be named, not silently dropped"


def test_the_endpoint_refuses_a_traversal_shaped_edition_code(client):
    r = client.get("/api/wiki/dumps/sizes", params={"wikis": "en,../../etc"})
    assert r.status_code == 400


def test_the_endpoint_refuses_an_empty_selection(client):
    # Never silently substitute a default edition the operator did not choose.
    assert client.get("/api/wiki/dumps/sizes", params={"wikis": " , "}).status_code == 400


def test_the_endpoint_is_a_sync_def_so_its_network_batch_leaves_the_event_loop_free():
    """A blocking body inside an ``async def`` freezes the single worker for the
    whole batch. Starlette runs a plain ``def`` route in the threadpool."""
    import inspect

    from src.api.wiki import dumps_sizes

    assert not inspect.iscoroutinefunction(dumps_sizes)


# --------------------------------------------------------------------------- #
# the consent gate (invariant #14) and the retired button
# --------------------------------------------------------------------------- #


def test_the_size_refresh_passes_the_one_network_consent_popup():
    """Reading live sizes from dumps.wikimedia.org is an offline->online
    transition, so it goes through ``ensureOnline`` like every other action on
    this surface. The old probe did not, which is what this replaces.

    Comment-stripped, because the comment above the call necessarily quotes the
    very identifier the assertion looks for.
    """
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "refreshDumpSizes"))
    assert "ensureOnline(" in body, "the size refresh must pass the ONE consent popup"
    assert "/api/wiki/dumps/sizes" in body
    # The gate must come BEFORE the request, or consent is asked for an egress
    # that already happened.
    assert body.index("ensureOnline(") < body.index("/api/wiki/dumps/sizes")


def test_the_per_edition_estimate_button_is_gone_from_the_picker():
    """The ruled retirement: the unconsented per-edition probe button is
    replaced, not merely joined, by the consented refresh."""
    from tests.js_source_helper import read_static

    html = read_static("index.html")
    assert "refreshDumpSizes()" in html
    assert "probeDump()" not in html


def test_the_refresh_refuses_an_empty_selection_instead_of_defaulting_to_english():
    """The old probe read ``dumpSelected()[0] || "en"``, so pressing it with
    nothing selected reported a figure for an edition the operator had not
    chosen. The replacement says so instead."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "refreshDumpSizes"))
    assert '|| "en"' not in body
    assert "Select one or more editions first." in body


def test_an_exact_reading_is_marked_differently_from_the_bundled_estimate():
    """One is what the host publishes now, the other is a table reviewed on a
    date. Rendering them identically would let a reader take a dated estimate
    for a measurement."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "renderWikiLanguages"))
    assert "_dumpExactSizes" in body
    assert "=${_fmtBytes(exact)}" in body
    assert "~${_fmtBytes(l.size_estimate_bytes)}" in body


def test_every_refusal_reason_the_backend_can_publish_has_its_own_sentence():
    """A reason the frontend cannot name would fall through to a generic line,
    which is the conflation the named reasons exist to prevent."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "_dumpSizeReason"))
    for reason in ("airplane", "unreachable", "no-content-length", "invalid-edition"):
        assert f'"{reason}"' in body, f"{reason} has no sentence in the UI"
