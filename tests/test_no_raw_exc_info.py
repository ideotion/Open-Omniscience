"""No log call writes an exception unscrubbed: ``exc_info=``, ``Logger.exception``, ``sys.exc_info()`` and the ``traceback``
text makers are sinks (``data/app_errors.jsonl`` rides the diagnostics bundle, and a traceback prints the ``__cause__`` and
``__context__`` chain, where a keyed open's driver error carries the passphrase). ``secret_scrub.log_failure`` is the way.

The files that still have sites are listed in ``tests/data/exc_info_allowlist.json`` (count + owner), a RATCHET with zero
slack: a new site fails, a converted site that leaves its entry too high fails, and the entry goes when its count is zero.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tests import exc_info_scan as scan

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = json.loads(
    (ROOT / "tests" / "data" / "exc_info_allowlist.json").read_text(encoding="utf-8")
)


def test_no_new_unscrubbed_exception_sink():
    found = scan.scan_tree(ROOT)
    new = {
        f: list(hits)
        for f, hits in found.items()
        if f not in ALLOWLIST or len(hits) > ALLOWLIST[f]["count"]
    }
    assert not new, (
        "log the failure with secret_scrub.log_failure (or the class name alone), never exc_info=/.exception(: "
        + "; ".join(f"{f}:{','.join(f'{n} {k}' for n, k in h)}" for f, h in sorted(new.items()))
    )


def test_allowlist_has_no_slack():
    found = scan.scan_tree(ROOT)
    stale = {
        f: (e["count"], len(found.get(f, [])))
        for f, e in ALLOWLIST.items()
        if len(found.get(f, [])) != e["count"]
    }
    assert not stale, f"lower or delete these allowlist entries (listed, found): {stale}"
    assert all(e["owner"] and e["count"] > 0 for e in ALLOWLIST.values())


def test_exempt_modules_exist_and_are_only_the_scrub_and_the_error_log():
    assert {"src/monitoring/secret_scrub.py", "src/monitoring/errorlog.py"} == scan.EXEMPT
    assert all((ROOT / p).is_file() for p in scan.EXEMPT)


@pytest.mark.parametrize(
    ("snippet", "kind"),
    [
        ("try: pass\nexcept Exception:\n    log.warning('x', exc_info=True)", "exc_info"),
        ("try: pass\nexcept Exception as e:\n    _LOG.error('x', exc_info=e)", "exc_info"),
        ("try: pass\nexcept Exception:\n    self.logger.exception('x')", "exception"),
        ("import sys\nlogging.info('x', exc_info=sys.exc_info())", "exc_info"),
        ("import sys\nt = sys.exc_info()", "sys.exc_info"),
        ("import traceback\nlog.error('x %s', traceback.format_exc())", "format_exc"),
        ("from traceback import print_exc\nprint_exc()", "print_exc"),
        ("import traceback\nlog.error(''.join(traceback.format_exception(e)))", "format_exception"),
    ],
)
def test_scanner_flags_every_sink_shape(snippet, kind):
    """MUTATION TARGET: a shape dropped from ``exc_info_scan.scan_source`` stops this (and the tree scan) seeing it."""
    assert kind in {k for _, k in scan.scan_source(snippet)}


@pytest.mark.parametrize(
    "snippet",
    [
        "log.warning('x', exc_info=False)",
        "log.warning('x', exc_info=None)",
        "fut.exception()",
        "secret_scrub.log_failure(log, 'x', exc)",
        "log.warning('x: %s', type(exc).__name__)",
    ],
)
def test_scanner_leaves_the_scrubbed_forms_alone(snippet):
    assert scan.scan_source(snippet) == []


def test_log_failure_still_scrubs_the_secret_and_attaches_no_exc_info(caplog):
    from src.monitoring import secret_scrub

    def boom():
        raise ValueError("driver says hunter2-pass")

    with caplog.at_level(logging.ERROR):
        try:
            boom()
        except ValueError as exc:
            secret_scrub.log_failure(logging.getLogger("t"), "failed", exc, "hunter2-pass")
    rec = caplog.records[-1]
    assert rec.exc_info is None
    assert "hunter2-pass" not in rec.getMessage() and "hunter2-pass" not in getattr(
        rec, secret_scrub.TRACEBACK_ATTRIBUTE
    )
