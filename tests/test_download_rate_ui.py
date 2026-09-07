"""PERF-09: the task manager actually DRAWS the rate the owners now measure.

A measurement no surface reads is the recorded dead-end shape ("a machine-readable
answer whose flag no caller ever sends"), and this repo has hit it at least five
times. So the render is part of the slice, and its behaviour is driven in node
(``download_rate_note_node_test.js``) against the function EXTRACTED from the
shipped module -- a re-typed copy would pass while the real renderer was broken.

The pytest half is the driver the node-suite ratchet requires, plus the two
claims that belong on this side: the endpoint really carries the block, and the
strings the renderer introduces are keyed in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

#: Every string the rate line can put on screen. Keyed here rather than trusted to
#: the i18n ratchets, because those are MAXIMA: a shrinking measured population and
#: an improving codebase move a max-gate the same way, so "the gate is green" is not
#: evidence that THESE strings are covered.
_RATE_STRINGS = [
    "{rate}/s",
    "{time} left",
    "no data for {time}",
    "Measured by the download itself: bytes it received, over the wall clock since "
    "the measurement window opened. Not an estimate made in the browser.",
    "No bytes have arrived for a while. The download is still open — it may be a "
    "slow or stalled server — and it resumes from where it stopped.",
]


def test_rate_note_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "download_rate_note_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_rate_string_is_keyed_in_all_twelve_locales() -> None:
    missing: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        # encoding= is not optional: this tree's utf8 guard scans for it, and on a
        # cp1252 default these files (curly quotes, em dashes) would CRASH the read
        # rather than fail an assertion.
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _RATE_STRINGS:
            if s not in data:
                missing.append(f"{path.name}: {s[:48]!r}")
            elif not str(data[s]).strip():
                missing.append(f"{path.name}: {s[:48]!r} is EMPTY")
    assert not missing, "unkeyed rate strings:\n  " + "\n  ".join(missing)
    assert len(list(_LOCALES.glob("*.json"))) == 12


def test_a_translated_template_keeps_its_placeholders_verbatim() -> None:
    """A ``{placeholder}`` with no matching var renders a LITERAL ``{x}`` to the
    reader -- a broken frame, which the composite-string rule forbids. A locale
    that translates the placeholder name is exactly how that ships."""
    import re

    bad: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _RATE_STRINGS:
            want = set(re.findall(r"\{(\w+)\}", s))
            got = set(re.findall(r"\{(\w+)\}", str(data.get(s, ""))))
            if want != got:
                bad.append(f"{path.name}: {s[:32]!r} wants {sorted(want)}, has {sorted(got)}")
    assert not bad, "placeholder drift:\n  " + "\n  ".join(bad)


def test_the_jobs_endpoint_carries_the_measurement_for_a_download_row() -> None:
    """The wiring claim. A test of the sampler is not a test of the payload, and
    the payload is what the renderer reads."""
    from src.api import jobs as jobs_mod

    seen: list[dict] = []

    class _Mgr:
        def queue_order(self):
            return []

        def list(self):
            return [{
                "key": "en:pages-articles",
                "wiki": "en",
                "kind": "pages-articles",
                "status": "downloading",
                "downloaded_bytes": 2048,
                "total_bytes": 8192,
                "percent": 25.0,
                "error": None,
                "rate": {"measured": True, "bytes_per_s": 1024.0, "window_s": 4.0,
                         "samples": 5, "method": "m", "eta_seconds": 6.0},
            }]

    import src.wiki.dumps as dumps_mod

    real = dumps_mod.get_manager
    dumps_mod.get_manager = lambda: _Mgr()  # type: ignore[assignment]
    try:
        rows = jobs_mod._dump_jobs()
    finally:
        dumps_mod.get_manager = real  # type: ignore[assignment]
    seen.extend(rows)

    assert len(seen) == 1, seen
    row = seen[0]
    assert row["rate"]["measured"] is True
    assert row["rate"]["bytes_per_s"] == 1024.0
    assert row["eta_seconds"] == 6.0


def test_an_unmeasured_download_row_carries_no_eta_rather_than_zero() -> None:
    """NEGATIVE TWIN. The endpoint lifts ``eta_seconds`` out of the rate block, so
    the natural implementation (``.get("eta_seconds", 0)``) would fabricate the
    very countdown invariant #20 refuses -- and a 0 next to a running download
    reads as "about to finish", the opposite of the truth."""
    from src.api import jobs as jobs_mod
    import src.geo.osm_downloads as osm_mod

    class _Mgr:
        def queue_order(self):
            return []

        def list(self):
            return [{
                "key": "monaco", "code": "monaco", "name": "Monaco",
                "status": "downloading", "downloaded_bytes": 10, "total_bytes": 0,
                "percent": 0.0, "error": None, "queue_position": None,
                "rate": {"measured": False, "reason": "no bytes observed yet"},
            }]

    real = osm_mod.get_manager
    osm_mod.get_manager = lambda: _Mgr()  # type: ignore[assignment]
    try:
        rows = jobs_mod._osm_jobs()
    finally:
        osm_mod.get_manager = real  # type: ignore[assignment]

    assert len(rows) == 1
    assert rows[0]["rate"]["measured"] is False
    assert rows[0]["eta_seconds"] is None, rows[0]
