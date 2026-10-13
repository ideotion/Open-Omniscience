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


def _class_only_absent(record) -> None:
    """None of the failure's words, the key statement or the passphrase is in the record (it need not name the class)."""
    text = json.dumps(record, default=str)
    for needle in (WORDS, STATEMENT, SECRET):
        assert needle not in text, (needle, text)


def _is_the_class(value) -> None:
    """A field that is the failure's class and nothing else: not the class beside a few characters of the words."""
    assert value == CLASS, value


def _logged(caplog, logger: str, fragment: str) -> logging.LogRecord:
    got = [r for r in caplog.records if r.name == logger and fragment in r.getMessage()]
    assert len(got) == 1, (fragment, [r.getMessage() for r in caplog.records])
    return got[0]


def _scrubbed(rec: logging.LogRecord) -> None:
    """What a handler writes for the record: the failure is named WITH its words, there is no live traceback for a handler to format,
    and the held passphrase is out of the message and of the scrubbed traceback the error log takes its tail from."""
    text = logging.Formatter("%(message)s").format(rec) + str(getattr(rec, TRACEBACK_ATTRIBUTE, ""))
    assert rec.exc_info is None, "a record that carries exc_info is formatted raw by every handler"
    assert CLASS in text and SECRET not in text, text
    assert WORDS in text, "the words are the one thing the log line is for: a record that keeps only the class sends a reader nowhere"


# --------------------------------------------------------------------------- #
#  bulletin facts: four probes
# --------------------------------------------------------------------------- #
def test_each_disclosure_probe_keeps_the_class_of_its_failure_and_logs_it_scrubbed(monkeypatch, caplog):
    monkeypatch.setattr("src.backup.merge.reindex_backlog", _raise)
    out = facts.disclosures(_Poisoned(), _period())
    _is_the_class(out["quarantined_error"])
    _is_the_class(out["mentions_without_a_date_error"])
    _is_the_class(out["baseline_coverage"]["error"])
    assert out["reindex_backlog"] == {"available": False, "reason": f"the backlog could not be read ({CLASS})"}
    _class_only(out)
    assert out["quarantined_in_period"] is None and out["mentions_without_a_date"] is None, "None is 'could not read', never zero"
    for fragment in (
        "quarantine count failed",
        "undated-mention count failed",
        "re-index backlog unreadable",
        "baseline coverage failed",
    ):
        _scrubbed(_logged(caplog, "src.bulletin.facts", fragment))


def test_a_re_index_backlog_the_merge_module_could_not_read_gives_the_record_fixed_words_not_the_engines(monkeypatch, caplog):
    """``reindex_backlog`` catches its own failure and puts the engine's (scrubbed) words in its ``reason``: the REAL handler runs here,
    so what the bulletin's record keeps of it is tested, not a stand-in that skips it."""
    monkeypatch.setattr("src.database.session.session_scope", _raise)
    out = facts.disclosures(_Poisoned(), _period())
    assert out["reindex_backlog"] == {"available": False, "reason": "the backlog could not be read"}
    _class_only_absent(out["reindex_backlog"])
    # the merge module wrote the scrubbed words to the log itself
    merge_lines = [r for r in caplog.records if r.name == "backup.merge" and "re-index backlog" in r.getMessage()]
    assert merge_lines and all(SECRET not in r.getMessage() for r in merge_lines)


# --------------------------------------------------------------------------- #
#  bulletin sections: six handlers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("build", "keys", "fragments"),
    [
        (sections.by_topic_tag, ("error",), ("by_topic_tag failed",)),
        (sections.alerts, ("error",), ("alerts unreadable",)),
        (sections.through_time, ("error",), ("through_time unreadable",)),
        (sections.changes_of_record, ("law_error", "wiki_error"), ("law changes unreadable", "wiki changes unreadable")),
    ],
    ids=["by_topic_tag", "alerts", "through_time", "changes_of_record"],
)
def test_a_failing_section_keeps_the_class_of_its_failure_and_logs_it_scrubbed(build, keys, fragments, caplog):
    out = build(_Poisoned(), _period())
    for key in keys:
        assert key in out, f"{key} is the only place the section says it failed"
        _is_the_class(out[key])
    _class_only_absent(out)
    for fragment in fragments:
        _scrubbed(_logged(caplog, "src.bulletin.sections", fragment))


def test_the_section_runner_keeps_the_class_of_a_section_that_raises_and_logs_it_scrubbed(monkeypatch, caplog):
    monkeypatch.setattr(sections, "SECTIONS", (("exploding", _raise),))
    monkeypatch.setattr(sections, "_deadline_expired", lambda _session: False)
    (bundle,) = sections.build_sections(object(), _period())
    assert bundle["section"] == "exploding"
    _is_the_class(bundle["error"])
    _scrubbed(_logged(caplog, "src.bulletin.sections", "section exploding failed"))


# --------------------------------------------------------------------------- #
#  the card audit: five sites
# --------------------------------------------------------------------------- #
def test_a_failing_audit_section_keeps_the_class_of_its_failure_and_logs_it_scrubbed(caplog):
    out = card_audit._safe_section("window", _raise)
    assert out["section_ok"] is False
    _is_the_class(out["error"])
    _class_only_absent(out)
    _scrubbed(_logged(caplog, "src.briefing.card_audit", "section 'window' failed"))


def test_a_statement_timeout_still_propagates_out_of_an_audit_section():
    """The outer statement deadline must still bite: ``_safe_section`` re-raises it and degrades everything else."""
    from src.database.maintenance import StatementTimeout

    def _times_out():
        raise StatementTimeout("the statement ran out of time")

    with pytest.raises(StatementTimeout):
        card_audit._safe_section("window", _times_out)


def test_a_failing_producer_keeps_its_class_logs_the_words_scrubbed_and_the_report_says_where_they_are(caplog):
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
    # the row says "the log has them": it does
    _scrubbed(_logged(caplog, "src.briefing.card_audit", "producer 'boom' failed"))


def test_an_unreadable_dismissals_file_is_logged_scrubbed_and_the_audit_goes_on(monkeypatch, caplog):
    monkeypatch.setattr("src.briefing.service.dismissed_ids", _raise)
    with contextlib.suppress(Exception):  # the rest of the report needs a corpus; this test reads the dismissals line only
        card_audit.card_audit_report(object(), depth="summary")
    _scrubbed(_logged(caplog, "src.briefing.card_audit", "dismissed ids unreadable"))


def test_a_report_folder_that_cannot_be_read_gives_a_reason_with_the_class_and_none_of_the_words(monkeypatch):
    monkeypatch.setattr(card_audit, "_report_dir", _raise)
    out = card_audit.last_card_audit_report()
    assert out["available"] is False
    assert out["reason"] == f"the report folder could not be read ({CLASS})"


def test_a_saved_report_that_cannot_be_read_gives_a_reason_with_the_class_and_none_of_the_words(tmp_path, monkeypatch):
    (tmp_path / "oo-card-audit-2026.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(card_audit, "_report_dir", lambda: tmp_path)
    monkeypatch.setattr(json, "loads", _raise)
    out = card_audit.last_card_audit_report()
    assert out["available"] is False
    assert out["reason"] == f"unreadable report oo-card-audit-2026.json ({CLASS})"


def test_a_report_saved_by_an_older_build_passes_on_no_failure_words(tmp_path, monkeypatch):
    """A deep report is read back whatever wrote it: an older build kept ``str(exc)`` in the producer row."""
    old_row = {
        "name": "boom",
        "outcome": "error",
        "error_type": CLASS,
        "error_message": f"{WORDS}: {STATEMENT}, passphrase {SECRET}",
    }
    report = {"schema": card_audit.SCHEMA, "producer_inventory": {"total": 1, "errored": [old_row, "not a row"], "note": "n"}}
    (tmp_path / "oo-card-audit-2026.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(card_audit, "_report_dir", lambda: tmp_path)
    out = card_audit.last_card_audit_report()
    assert out["available"] is True
    (row, other) = out["producer_inventory"]["errored"]
    assert row["error_type"] == CLASS and row["error_message"] == card_audit._WORDS_NOT_KEPT
    assert other == "not a row", "what is not a producer row is left as it was"
    _class_only(out["producer_inventory"])


def test_a_saved_report_the_diff_cannot_read_gives_a_reason_with_the_class_and_none_of_the_words(tmp_path, monkeypatch):
    from src.briefing import card_audit_diff

    for name in ("oo-card-audit-2026-1.json", "oo-card-audit-2026-2.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(card_audit, "_report_dir", lambda: tmp_path)
    monkeypatch.setattr(json, "loads", _raise)
    out = card_audit_diff.diff_latest_card_audits()
    assert out["available"] is False
    _class_only(out["reason"])


def test_the_modules_these_tests_drive_are_held_to_the_source_guard():
    """Taking a module out of the source guard must fail a test, not pass in silence."""
    from tests.test_runs_log_sinks import _SWEEP_MODULES

    for rel in (
        "src/briefing/card_audit.py",
        "src/briefing/card_audit_diff.py",
        "src/bulletin/facts.py",
        "src/bulletin/sections.py",
    ):
        assert rel in _SWEEP_MODULES, rel
