"""Row 290: a redirect hop's robots refusal names the refusing HOST, and the "Track changes now" headline is keyed.

Row 283 named a robots refusal "blocked by the site's robots.txt". When a redirect carried the document to another site
and THAT site's robots.txt refused it, "the site" read as the document's own. The fetcher's stored sentence already names
the refused address and ends "(reached by a redirect)"; `/api/law/documents` now reads the host back out of it as
`robots_host` (host only, never the address: R734), and the Law badge and "Add & track" name it. Read side only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.law import _robots_hop_host
from src.ingest import _REDIRECT_HOP_NOTE
from tests.js_source_helper import function_source, read_static

_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
_HOP = f"({_REDIRECT_HOP_NOTE})"


@pytest.mark.parametrize(
    ("stored", "host"),
    [
        (f"fetch error: robots.txt disallows https://other.example/acts/1?q=***** {_HOP}", "other.example"),
        (f"fetch error: robots.txt disallows https://***:***@Other.Example:8443/x {_HOP}", "other.example"),
        (
            f"fetch error: robots.txt for https://other.example could not be determined (refused); refusing to fetch {_HOP}",
            "other.example",
        ),
    ],
)
def test_the_refusing_host_is_read_from_a_hop_refusal(stored, host):
    assert _robots_hop_host(stored) == host


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "fetch error: robots.txt disallows https://own.example/x",  # a direct refusal: the document's own site
        f"fetch error: request error for https://x.example/robots-act {_HOP}",  # not a robots refusal
        f"unchanged; stays on its HTML address: robots.txt disallows https://x.example/a.xml {_HOP}",  # R753: read, unchanged
        f"fetch error: robots.txt disallows {_HOP}",  # no address to read
    ],
)
def test_no_host_without_a_hop_robots_refusal(stored):
    assert _robots_hop_host(stored) is None


def test_never_the_full_address():
    got = _robots_hop_host(f"fetch error: robots.txt disallows https://other.example/secret/path?id=***** {_HOP}")
    assert got == "other.example" and "/" not in got and "?" not in got


def test_the_document_row_carries_it():
    from src.api.law import _doc_dict
    from src.database.models import LawDocument

    doc = LawDocument(jurisdiction="uk", title="A", url="https://own.example/a")
    doc.last_status = f"fetch error: robots.txt disallows https://other.example/a {_HOP}"
    row = _doc_dict(doc)
    assert row["verdict"] == "robots_blocked" and row["robots_host"] == "other.example"
    doc.last_status = "fetch error: robots.txt disallows https://own.example/a"
    assert _doc_dict(doc)["robots_host"] is None


def test_the_new_frames_are_keyed_in_all_twelve_languages():
    keys = (
        "blocked by the robots.txt of {host} (reached by a redirect)",
        "robots.txt of {host} not readable (reached by a redirect)",
        "Tracked {n} law(s): {baselines} baselines, {changed} changed, {flagged} flagged, {errors} errors.",
    )
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            value = data.get(key)
            assert value, (path.stem, key)
            for slot in ("{host}",) if "{host}" in key else ("{n}", "{baselines}", "{changed}", "{flagged}", "{errors}"):
                assert slot in value, (path.stem, key, slot)


def test_the_toast_headline_and_the_add_message_use_them():
    js = read_static("app-gov-law.js")
    track = function_source(js, "lawTrack")
    assert "Tracked {n} law(s): {baselines} baselines" in track and "`Tracked ${" not in track
    assert "lawVerdictLabel(\"robots_blocked\", r.robots_host)" in function_source(js, "lawAddDocument")
    assert "lawVerdictLabel(x.verdict, x.robots_host)" in function_source(js, "lawVerdictBadge")
