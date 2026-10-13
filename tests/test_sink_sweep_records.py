"""The records that ride a file, a served status or the diagnostics bundle carry the exception's text only through
``secret_scrub.exception_text`` (scrub, then cut), never ``str(exc)`` / ``f"{type(exc).__name__}: {exc}"`` directly.

The log guard (``test_no_raw_exc_info``) reads log calls; these are the stored half, in the scheduler, the wiki lane and the
unlock module. A raw spelling returning there fails this test, naming the line.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = re.compile(
    r"=\s*str\((?:exc|e|err)\)|str\((?:exc|e)\)\[|\{type\((?:exc|e)\)\.__name__\}: \{(?:exc|e)\}"
    r"|\"error\": str\(|error=str\("
)
# Held in memory as a dedupe key and never written, served or logged.
KEY_ONLY = {"src/scheduler/storage_guard.py"}
SCOPE = ["src/scheduler", "src/wiki", "src/api/unlock.py"]


def _files():
    for entry in SCOPE:
        p = ROOT / entry
        yield from ([p] if p.is_file() else sorted(p.rglob("*.py")))


def test_no_raw_exception_text_in_a_stored_or_served_record():
    hits = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW.search(line) and not (rel in KEY_ONLY and "first = " in line):
                hits.append(f"{rel}:{n}: {line.strip()}")
    assert not hits, "route the exception through secret_scrub.exception_text:\n" + "\n".join(hits)


def test_the_guard_sees_the_spellings_it_forbids():
    for bad in (
        "self._last_error = str(exc)",
        "report[\"error\"] = str(exc)",
        "x = str(exc)[:160]",
        "rec = f\"{type(exc).__name__}: {exc}\"",
        "set_startup('ready', '', error=str(exc))",
    ):
        assert RAW.search(bad), bad
    assert not RAW.search("self._last_error = exception_text(exc, typed=False)")
