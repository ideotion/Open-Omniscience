"""The bulletin's facts and sections and the card audit write a caught failure through the scrub, and their records keep its class.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Twelve log calls in ``src/bulletin/facts.py``, ``src/bulletin/sections.py`` and ``src/briefing/card_audit.py`` asked for the
traceback of the failure they caught (``exc_info=True``), which a handler formats with the exception's message and its
``__cause__``/``__context__`` chain: a keyed open's driver error carries the passphrase, and ``data/app_errors.jsonl`` rides the
diagnostics bundle. Beside them, fourteen records wrote the exception's own words (``str(exc)``, ``f"{type(exc).__name__}: {exc}"``);
the card audit and the bulletin facts ride that bundle as well.

A log line now goes through ``secret_scrub.log_failure`` and a record keeps the exception's CLASS and none of its words (the words are
in the scrubbed log line, which is where a reader looks for them). Each site is driven here with a held passphrase, a key statement and a
sentence of the engine's own words inside the failure, and the record and every record a handler would format are searched. A source
guard (``test_runs_log_sinks.py``, ``_SWEEP_MODULES``) holds the three modules to the same rule.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import date

import pytest

from src.briefing import card_audit
from src.bulletin import facts, sections
from src.bulletin.period import resolve_period
from src.monitoring.secret_scrub import TRACEBACK_ATTRIBUTE

SECRET = "correct horse's battery"
STATEMENT = "PRAGMA key = 'k3y-zzzz-abcd'"
WORDS = "the driver said"
CLASS = "RuntimeError"


def _failure() -> RuntimeError:
    return RuntimeError(f"{WORDS}: {STATEMENT}, passphrase {SECRET}")


def _raise(*_a, **_k):
    raise _failure()


class _Poisoned:
    """A session whose every use fails the way a keyed engine's does."""

    def __getattr__(self, name):
        return _raise


@pytest.fixture(autouse=True)
def _held(monkeypatch, caplog):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    caplog.set_level(logging.WARNING)


def _period():
    return resolve_period("weekly", end=date(2026, 8, 1))


def _class_only(record) -> None:
    """The record names the failure's class and carries none of its words, the key statement or the passphrase."""
    text = json.dumps(record, default=str)
    assert CLASS in text, text
    for needle in (WORDS, STATEMENT, SECRET):
        assert needle not in text, (needle, text)


def _logged(caplog, logger: str, fragment: str) -> logging.LogRecord:
    got = [r for r in caplog.records if r.name == logger and fragment in r.getMessage()]
    assert len(got) == 1, (fragment, [r.getMessage() for r in caplog.records])
    return got[0]


def _scrubbed(rec: logging.LogRecord) -> None:
    """What a handler writes for the record: the failure is named, there is no live traceback for a handler to format, and the held
    passphrase is out of the message and of the scrubbed traceback the error log takes its tail from."""
    text = logging.Formatter("%(message)s").format(rec) + str(getattr(rec, TRACEBACK_ATTRIBUTE, ""))
    assert rec.exc_info is None, "a record that carries exc_info is formatted raw by every handler"
    assert CLASS in text and SECRET not in text, text


# --------------------------------------------------------------------------- #
#  bulletin facts: four probes
# --------------------------------------------------------------------------- #
def test_each_disclosure_probe_keeps_the_class_of_its_failure_and_logs_it_scrubbed(monkeypatch, caplog):
    monkeypatch.setattr("src.backup.merge.reindex_backlog", _raise)
    out = facts.disclosures(_Poisoned(), _period())
    _class_only(out["quarantined_error"])
    _class_only(out["mentions_without_a_date_error"])
    _class_only(out["reindex_backlog"])
    _class_only(out["baseline_coverage"]["error"])
    assert out["quarantined_in_period"] is None and out["mentions_without_a_date"] is None, "None is 'could not read', never zero"
    assert out["reindex_backlog"]["available"] is False
    for fragment in (
        "quarantine count failed",
        "undated-mention count failed",
        "re-index backlog unreadable",
        "baseline coverage failed",
    ):
        _scrubbed(_logged(caplog, "src.bulletin.facts", fragment))


# --------------------------------------------------------------------------- #
#  bulletin sections: six handlers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("build", "fragments"),
    [
        (sections.by_topic_tag, ("by_topic_tag failed",)),
        (sections.alerts, ("alerts unreadable",)),
        (sections.through_time, ("through_time unreadable",)),
        (sections.changes_of_record, ("law changes unreadable", "wiki changes unreadable")),
    ],
    ids=["by_topic_tag", "alerts", "through_time", "changes_of_record"],
)
def test_a_failing_section_keeps_the_class_of_its_failure_and_logs_it_scrubbed(build, fragments, caplog):
    out = build(_Poisoned(), _period())
    _class_only({k: v for k, v in out.items() if k.endswith("error")})
    for fragment in fragments:
        _scrubbed(_logged(caplog, "src.bulletin.sections", fragment))


def test_the_section_runner_keeps_the_class_of_a_section_that_raises_and_logs_it_scrubbed(monkeypatch, caplog):
    monkeypatch.setattr(sections, "SECTIONS", (("exploding", _raise),))
    monkeypatch.setattr(sections, "_deadline_expired", lambda _session: False)
    (bundle,) = sections.build_sections(object(), _period())
    assert bundle["section"] == "exploding"
    _class_only(bundle["error"])
    _scrubbed(_logged(caplog, "src.bulletin.sections", "section exploding failed"))


# --------------------------------------------------------------------------- #
#  the card audit: five sites
# --------------------------------------------------------------------------- #
def test_a_failing_audit_section_keeps_the_class_of_its_failure_and_logs_it_scrubbed(caplog):
    out = card_audit._safe_section("window", _raise)
    assert out["section_ok"] is False
    _class_only(out["error"])
    _scrubbed(_logged(caplog, "src.briefing.card_audit", "section 'window' failed"))


def test_a_failing_producer_keeps_its_class_and_the_report_says_the_words_are_not_kept():
    from src.briefing import registry

    saved = list(registry._REGISTRY)
    registry._REGISTRY = []
    try:
        registry.register("boom", _raise)
        (outcome,) = card_audit.observe_producers(object())
    finally:
        registry._REGISTRY = saved
    assert outcome.outcome == "error" and outcome.error_type == CLASS
    row = outcome.to_dict()
    _class_only({"error_type": row["error_type"]})
    assert row["error_message"] == card_audit._WORDS_NOT_KEPT
    for needle in (WORDS, STATEMENT, SECRET):
        assert needle not in json.dumps(row), needle


def test_an_unreadable_dismissals_file_is_logged_scrubbed_and_the_audit_goes_on(monkeypatch, caplog):
    monkeypatch.setattr("src.briefing.service.dismissed_ids", _raise)
    with contextlib.suppress(Exception):  # the rest of the report needs a corpus; this test reads the dismissals line only
        card_audit.card_audit_report(object(), depth="summary")
    _scrubbed(_logged(caplog, "src.briefing.card_audit", "dismissed ids unreadable"))


def test_a_report_folder_that_cannot_be_read_gives_a_reason_with_the_class_and_none_of_the_words(monkeypatch):
    monkeypatch.setattr(card_audit, "_report_dir", _raise)
    out = card_audit.last_card_audit_report()
    assert out["available"] is False
    _class_only(out["reason"])


def test_a_saved_report_that_cannot_be_read_gives_a_reason_with_the_class_and_none_of_the_words(tmp_path, monkeypatch):
    (tmp_path / "oo-card-audit-2026.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(card_audit, "_report_dir", lambda: tmp_path)
    monkeypatch.setattr(json, "loads", _raise)
    out = card_audit.last_card_audit_report()
    assert out["available"] is False and "oo-card-audit-2026.json" in out["reason"]
    _class_only(out["reason"])
