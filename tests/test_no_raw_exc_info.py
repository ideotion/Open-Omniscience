"""No log call writes an exception unscrubbed: ``exc_info=``, ``Logger.exception``, ``sys.exc_info()`` and the ``traceback``
text makers are sinks (``data/app_errors.jsonl`` rides the diagnostics bundle, and a traceback prints the ``__cause__`` and
``__context__`` chain, where a keyed open's driver error carries the passphrase). ``secret_scrub.log_failure`` is the way.

The files that still have sites are listed in ``tests/data/exc_info_allowlist.json`` (count + owner), a RATCHET with zero
slack: a new site fails, a converted site that leaves its entry too high fails, and the entry goes when its count is zero.

What the counts protect: that no new raw sink lands while the sweep converts the old ones. They are a measured ceiling that only
falls, never a budget; the sweep ends with an empty list and the list goes.
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
    assert not stale, (
        "the allowlist must equal what is found: lower or delete an entry whose sites were converted, and convert (never list) "
        f"a new site (listed, found): {stale}"
    )
    assert all(e["owner"] and e["count"] > 0 for e in ALLOWLIST.values())


def test_exempt_modules_exist_and_are_only_the_scrub_and_the_error_log():
    assert {"src/monitoring/secret_scrub.py", "src/monitoring/errorlog.py"} == scan.EXEMPT
    assert all((ROOT / p).is_file() for p in scan.EXEMPT)


_BAD = [
    ("try: pass\nexcept Exception:\n    log.warning('x', exc_info=True)", "exc_info"),
    ("try: pass\nexcept Exception as e:\n    _LOG.error('x', exc_info=e)", "exc_info"),
    ("import sys\nlogging.info('x', exc_info=sys.exc_info())", "exc_info"),
    ("log.warning('x', **{'exc_info': True})", "kwargs-unpack"),
    ("log.warning('x', **extra)", "kwargs-unpack"),
    ("kw = {'exc_info': True}", "exc_info-key"),
    ("kw['exc_info'] = True", "exc_info-key"),
    ("self.logger.exception('x')", "exception"),
    ("import logging\nlogging.getLogger('a').exception('x')", "exception"),
    ("lg = get(1)\nlg.exception('x')", "exception"),
    ("self.journal.exception('x')", "exception"),
    ("import logging\nlogging.exception('x')", "exception"),
    ("from logging import exception\nexception('x')", "exception"),
    ("import sys\nt = sys.exc_info()", "sys.exc_info"),
    ("import sys as s\nt = s.exc_info()", "sys.exc_info"),
    ("from sys import exc_info\nt = exc_info()", "sys.exc_info"),
    ("import sys\nt = sys.exception()", "sys.exception"),
    ("import sys\nt = sys.last_exc", "sys.last_exc"),
]
#: Every text maker the scanner names, in each of the ways a file can reach it.
_BAD += [
    (f"import traceback\nlog.error(traceback.{n}(e))", n) for n in sorted(scan.TRACEBACK_MAKERS)
]
_BAD += [
    (f"import traceback as tb\nlog.error(tb.{n}(e))", n) for n in sorted(scan.TRACEBACK_MAKERS)
]
_BAD += [(f"from traceback import {n} as fe\nfe()", n) for n in sorted(scan.TRACEBACK_MAKERS)]


@pytest.mark.parametrize(("snippet", "kind"), _BAD)
def test_scanner_flags_every_sink_shape(snippet, kind):
    """MUTATION TARGET: a shape dropped from ``exc_info_scan.scan_source`` stops this (and the tree scan) seeing it."""
    assert kind in {k for _, k in scan.scan_source(snippet)}


def test_the_named_text_makers_are_exactly_these():
    """MUTATION TARGET: a maker dropped from the scanner's set. The parametrised cases above are built from the set, so the set
    itself is pinned here by name; a new maker is added in both places."""
    assert {
        "format_exc",
        "print_exc",
        "format_exception",
        "format_exception_only",
        "print_exception",
        "format_tb",
        "print_tb",
        "TracebackException",
    } == scan.TRACEBACK_MAKERS
    assert {"exc_info", "exception"} == scan.SYS_MAKERS and {
        "last_exc",
        "last_value",
        "last_traceback",
    } == scan.SYS_ATTRIBUTES


def test_two_sinks_on_one_line_are_two():
    assert (
        len(scan.scan_source("log.warning('a', exc_info=True); log.error('b', exc_info=True)")) == 2
    )
    assert len(scan.scan_source("log.exception('a'); log.exception('b')")) == 2


def test_an_unparseable_file_is_named():
    with pytest.raises(SyntaxError, match=r"src/x\.py"):
        scan.scan_source("def (:", "src/x.py")


@pytest.mark.parametrize(
    "snippet",
    [
        "log.warning('x', exc_info=False)",
        "log.warning('x', exc_info=None)",
        "log.warning('x', exc_info=0)",
        "log.warning('x', exc_info='')",
        "log.warning('x', stack_info=True)",
        "fut.exception()",
        "task.exception(timeout=1)",
        "backlog.warning('x')",
        "secret_scrub.log_failure(log, 'x', exc)",
        "log.warning('x: %s', type(exc).__name__)",
        "import traceback\ntraceback.extract_stack()",
        "import sys\nsys.exit(1)",
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
