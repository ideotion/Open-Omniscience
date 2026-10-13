"""The rest of the bulletin and its routes write a caught failure through the scrub, and their records keep its class.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_bulletin_sink_sites.py`` holds the bulletin's facts and sections and the card audit to this rule; this file holds every
other site of ``src/bulletin`` and of ``src/api/bulletin.py``. Each handler asked for the traceback of the failure it caught
(``exc_info=True``) or wrote the exception's own words into the record it returns (``f"{type(exc).__name__}: {exc}"``, ``str(exc)``):
the edition, the annexes, the evidence archive, the narration layers and the job all ride the diagnostics bundle or the backup, and a
keyed open's driver error carries the passphrase.

A log line now goes through ``secret_scrub.log_failure``; a record keeps the exception's CLASS and none of its words (the words are in
the scrubbed log line). Three places answer the OPERATOR who just asked and keep no record: a route's refusal, the route's "built but
not saved" answer (``persist_error``) and the evidence plan's "this folder cannot be written". They keep the failure's words, through
``exception_text``, so that the person who chose the folder is told why it fails; the held passphrase is out of those words and the chained
cause is not raised. A frame the translator cannot fill is NOT one of them: its reason rides ``bulletin-language.json`` in the diagnostics
bundle, so it is a record and keeps the class. Every site is driven here with a held passphrase, a key statement and a sentence of the
engine's own words inside the failure. ``test_runs_log_sinks.py`` reads the same modules
for the shape of the code (``_SWEEP_MODULES``).
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime

import pytest

from tests.test_bulletin_sink_sites import (  # noqa: F401  (``_held`` is an autouse fixture: importing it puts it in force here)
    CLASS,
    SECRET,
    STATEMENT,
    WORDS,
    _class_only,
    _class_only_absent,
    _failure,
    _held,
    _is_the_class,
    _logged,
    _period,
    _Poisoned,
    _raise,
    _scrubbed,
)


def _os_failure() -> OSError:
    return OSError(f"{WORDS}: {STATEMENT}, passphrase {SECRET}")


def _os_raise(*_a, **_k):
    raise _os_failure()


def _value_raise(*_a, **_k):
    raise ValueError(f"{WORDS}: {STATEMENT}, passphrase {SECRET}")


def _no_secret(text) -> None:
    """A record that keeps the class: neither the held passphrase nor the key statement nor the engine's words are in it."""
    blob = json.dumps(text, default=str)
    for needle in (WORDS, STATEMENT, SECRET):
        assert needle not in blob, (needle, blob)


def _no_passphrase(text) -> None:
    """Words that are kept for the person who asked: the engine's sentence stays and the held passphrase is out of it."""
    blob = json.dumps(text, default=str)
    assert SECRET not in blob and "***redacted***" in blob, blob


def _empty_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _corpus_with_one_article():
    from src.database.models import Article, Source

    s = _empty_session()
    src = Source(name="Le Monde", domain="lemonde.fr", country="fr", source_type="news")
    s.add(src)
    s.flush()
    s.add(
        Article(
            id=11,
            url="https://lemonde.fr/11",
            canonical_url="https://lemonde.fr/11",
            source_id=src.id,
            title="Article 11",
            content="Le corps de l'article onze.",
            hash=f"{11:064d}",
            language="fr",
            published_at=datetime(2026, 8, 5, 9, 30),
            quarantined=False,
        )
    )
    s.commit()
    return s


def _zip_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())


# --------------------------------------------------------------------------- #
#  the annexes: four handlers
# --------------------------------------------------------------------------- #
def test_the_annexes_keep_the_class_of_each_failure_in_the_bundle_and_log_it_scrubbed(monkeypatch, caplog):
    from src.bulletin import annexes
    from tests.test_bulletin_annexes import _edition

    monkeypatch.setattr("src.bulletin.articles.article_analyses", _raise)
    monkeypatch.setattr("src.bulletin.articles.article_bodies", _raise)
    monkeypatch.setattr(annexes, "concepts_markdown", _raise)
    out = annexes.build_annexes(_Poisoned(), _edition())
    text = _zip_text(out["data"])
    _class_only(text)
    assert "This list could not be computed (RuntimeError)" in text, "the privacy note names the class"
    assert "This table could not be computed (RuntimeError)" in text, "the concepts note names the class"
    for fragment in (
        "annex analyses unreadable",
        "annex bodies unreadable",
        "could not write the annex privacy note",
        "could not write the concepts annexe",
    ):
        _scrubbed(_logged(caplog, "src.bulletin.annexes", fragment))


# --------------------------------------------------------------------------- #
#  article rows and bodies, the story evidence: an unreadable body
# --------------------------------------------------------------------------- #
def test_an_unreadable_article_body_is_logged_scrubbed_at_debug_and_costs_one_row(monkeypatch, caplog):
    from src.bulletin import articles
    from src.database.models import Article

    monkeypatch.setattr(Article, "get_content", _raise)
    caplog.set_level(logging.DEBUG, logger="src.bulletin.articles")
    s = _corpus_with_one_article()
    (row,) = articles.article_rows(s, [11])
    assert row["id"] == 11 and not row.get("excerpt")
    assert articles.article_bodies(s, [11]) == {}, "an unreadable body is omitted, never an empty string"
    for rec in [r for r in caplog.records if r.name == "src.bulletin.articles"]:
        _scrubbed(rec)
    assert len([r for r in caplog.records if "article 11 body unreadable" in r.getMessage()]) == 2


def test_the_debug_sites_cost_nothing_when_debug_is_off(monkeypatch, caplog):
    """``log_failure`` makes the whole traceback text, so every DEBUG site (the per-body ones, the temp sweep, the story's article
    rows) builds it only when DEBUG is on: each is driven here with its module's ``log_failure`` replaced by a recorder."""
    from src.bulletin import articles, store
    from src.bulletin import edition as edition_mod
    from src.database.models import Article

    called = []
    for module in (articles, edition_mod, store):
        monkeypatch.setattr(module, "log_failure", lambda *a, **k: called.append(a))
    monkeypatch.setattr(Article, "get_content", _raise)
    session = _corpus_with_one_article()
    articles.article_rows(session, [11])
    assert called == [], "article_rows"
    articles.article_bodies(session, [11])
    assert called == [], "article_bodies"

    class _Folder:
        def glob(self, _pattern):
            raise _failure()

    store._sweep(_Folder())
    assert called == [], "the temp sweep"

    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {"masthead": {}})
    monkeypatch.setattr("src.bulletin.edition._attribution", lambda *_a, **_k: ([], None))
    monkeypatch.setattr("src.bulletin.introduction.opening_block", lambda _e: {})
    monkeypatch.setattr("src.bulletin.stories.build_stories", lambda *_a, **_k: {"stories": [{"article_ids": [1]}]})
    monkeypatch.setattr("src.bulletin.articles.article_rows", _raise)
    edition_mod.build_edition(object(), _period(), narrate=False)
    assert called == [], "the story's article rows"
    assert caplog.records == []


def test_an_article_that_cannot_be_read_for_narration_is_logged_scrubbed_and_skipped(monkeypatch, caplog):
    from src.bulletin import stories
    from src.database.models import Article

    monkeypatch.setattr(Article, "get_content", _raise)
    out = stories.story_evidence(_corpus_with_one_article(), [11], budget_chars=1000)
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.stories", "article 11 unreadable for narration"))


# --------------------------------------------------------------------------- #
#  the cards section
# --------------------------------------------------------------------------- #
def test_a_card_layer_failure_keeps_the_class_and_logs_it_scrubbed(monkeypatch, caplog):
    from src.bulletin.cards import cards_by_type

    monkeypatch.setattr("src.briefing.registry.run_all_bounded", _raise)
    out = cards_by_type(object(), _period())
    _is_the_class(out["error"])
    _scrubbed(_logged(caplog, "src.bulletin.cards", "the card layer failed"))


# --------------------------------------------------------------------------- #
#  the edition: four handlers
# --------------------------------------------------------------------------- #
def test_the_edition_keeps_the_class_of_a_failed_opening_and_a_failed_licence_query(monkeypatch, caplog):
    from src.bulletin import edition as edition_mod

    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {"masthead": {}})
    monkeypatch.setattr("src.bulletin.introduction.opening_block", _raise)
    monkeypatch.setattr("src.bulletin.stories.build_stories", lambda *_a, **_k: {"stories": []})
    out = edition_mod.build_edition(_Poisoned(), _period(), narrate=False)
    _is_the_class(out["attribution_error"])
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.edition", "could not compose the opening paragraph"))
    _scrubbed(_logged(caplog, "src.bulletin.edition", "could not compute the attribution lines"))


def test_the_edition_keeps_the_class_of_a_failed_clustering_and_logs_it_scrubbed(monkeypatch, caplog):
    from src.bulletin import edition as edition_mod

    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {"masthead": {}})
    monkeypatch.setattr("src.bulletin.edition._attribution", lambda *_a, **_k: ([], None))
    monkeypatch.setattr("src.bulletin.introduction.opening_block", lambda _e: {})
    monkeypatch.setattr("src.bulletin.stories.build_stories", _raise)
    out = edition_mod.build_edition(object(), _period(), narrate=True)
    _is_the_class(out["stories"]["error"])
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.edition", "story clustering failed"))


def test_a_story_whose_articles_cannot_be_described_is_logged_scrubbed_at_debug(monkeypatch, caplog):
    from src.bulletin import edition as edition_mod

    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {"masthead": {}})
    monkeypatch.setattr("src.bulletin.edition._attribution", lambda *_a, **_k: ([], None))
    monkeypatch.setattr("src.bulletin.introduction.opening_block", lambda _e: {})
    monkeypatch.setattr("src.bulletin.stories.build_stories", lambda *_a, **_k: {"stories": [{"article_ids": [1]}]})
    monkeypatch.setattr("src.bulletin.articles.article_rows", _raise)
    caplog.set_level(logging.DEBUG, logger="src.bulletin.edition")
    out = edition_mod.build_edition(object(), _period(), narrate=False)
    assert "article_rows" not in out["stories"]["stories"][0], "the clusters are the record; the descriptions are not"
    _scrubbed(_logged(caplog, "src.bulletin.edition", "could not describe a story's articles"))


# --------------------------------------------------------------------------- #
#  the evidence archive: three handlers, and the operator's folder check
# --------------------------------------------------------------------------- #
def test_the_evidence_plan_keeps_the_class_of_each_failure_and_logs_it_scrubbed(monkeypatch, caplog):
    from src.bulletin import evidence

    monkeypatch.setattr(evidence, "_period_article_ids", lambda *_a, **_k: [1, 2])
    monkeypatch.setattr("src.bulletin.privacy.export_privacy", _raise)
    out = evidence.evidence_plan(_Poisoned(), _period())
    _is_the_class(out["privacy"]["error"])
    _no_secret(out)
    assert out["estimated_bytes"] is None, "an estimate that cannot be made is unknown, never zero"
    _scrubbed(_logged(caplog, "src.bulletin.evidence", "evidence size estimate failed"))
    _scrubbed(_logged(caplog, "src.bulletin.evidence", "export privacy enumeration failed"))


def test_a_folder_that_cannot_be_checked_is_explained_to_the_operator_without_the_passphrase(monkeypatch, tmp_path):
    """The plan answers the person who chose the folder and no record keeps the text: the OS's words stay, the passphrase does not."""
    from src.bulletin import evidence

    monkeypatch.setattr(evidence, "_period_article_ids", lambda *_a, **_k: [])
    monkeypatch.setattr("src.bulletin.privacy.export_privacy", lambda *_a, **_k: {"kind": "evidence"})
    monkeypatch.setattr(evidence.shutil, "disk_usage", _os_raise)
    out = evidence.evidence_plan(_empty_session(), _period(), dest=tmp_path)
    assert out["destination_writable"] is False
    _no_passphrase(out["destination_error"])
    assert out["destination_error"].startswith("OSError: ") and WORDS in out["destination_error"]


def test_the_evidence_archive_keeps_the_class_of_a_failed_privacy_note_and_logs_it_scrubbed(monkeypatch, tmp_path, caplog):
    from src.bulletin import evidence

    monkeypatch.setattr(evidence, "_period_article_ids", lambda *_a, **_k: [])
    monkeypatch.setattr("src.bulletin.privacy.export_privacy", _raise)
    out = evidence.build_evidence_archive(
        _empty_session(), {"period": _period().to_dict(), "masthead": {}, "sections": []}, _period(), tmp_path
    )
    (archive,) = tmp_path.glob("*-evidence.zip")
    text = _zip_text(archive.read_bytes())
    _class_only(text)
    _no_secret(out)
    assert "This list could not be computed (RuntimeError)" in text
    _scrubbed(_logged(caplog, "src.bulletin.evidence", "could not write the privacy note"))


# --------------------------------------------------------------------------- #
#  the hardware gate
# --------------------------------------------------------------------------- #
def test_a_hardware_probe_that_raises_degrades_with_the_class_and_logs_the_words_scrubbed(monkeypatch, caplog):
    from src.bulletin.gate import bulletin_available

    monkeypatch.setattr("src.llm.backend.inference_capability", _raise)
    out = bulletin_available()
    assert out["available"] is False and out["narration_available"] is False
    assert out["reason"] == f"the hardware capability probe failed ({CLASS})"
    assert out["narration_reason"] == out["reason"]
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.gate", "hardware capability probe failed"))


def test_the_gate_record_keeps_no_word_of_a_probe_that_failed_inside_the_capability_check(monkeypatch, caplog):
    """The capability dict is stored in the edition (``edition["gate"]``), so it rides the backup, the evidence archive and the diagnostics
    bundle: the probes' own handlers run here (``inference_capability`` is not replaced), which is the shape a stand-in would skip."""
    from src.bulletin.gate import bulletin_available

    monkeypatch.setattr("src.llm.backend.detect_gpu", _raise)
    monkeypatch.setattr("src.llm.backend.platform.system", _raise)
    out = bulletin_available()
    # Where the probe text lands depends on the host: a machine under the CPU/RAM floor says it in ``reason``, one over it in ``warnings``.
    warned = json.dumps(out, default=str)
    assert f"GPU probe failed ({CLASS})" in warned and f"platform probe failed ({CLASS})" in warned, warned
    _class_only(out)
    for fragment in ("the GPU probe failed", "the platform probe failed"):
        _scrubbed(_logged(caplog, "src.llm.backend", fragment))


def test_an_apple_silicon_probe_that_raises_keeps_the_class_in_the_capability(monkeypatch, caplog):
    from src.llm import backend

    monkeypatch.setattr(backend, "detect_gpu", lambda: {"available": False, "reason": "no nvidia-smi on this machine"})
    monkeypatch.setattr(backend, "detect_apple_silicon", _raise)
    cap = backend.inference_capability()
    # ``reason`` on a machine under the CPU/RAM floor, ``warnings`` on one over it: the whole capability is searched, so the test reads the same on any host.
    assert f"Apple Silicon probe failed ({CLASS})" in json.dumps(cap, default=str), cap
    _class_only(cap)
    _scrubbed(_logged(caplog, "src.llm.backend", "the Apple Silicon probe failed"))


# --------------------------------------------------------------------------- #
#  the translator: a frame it cannot fill keeps the class in the language report, which rides the diagnostics bundle
# --------------------------------------------------------------------------- #
def test_a_format_error_in_a_frame_keeps_the_class_in_the_report_and_its_words_in_the_scrubbed_log(caplog):
    from src.bulletin.i18n import Translator

    class _Boom:
        def __format__(self, spec):
            raise ValueError(f"{WORDS}: {STATEMENT}, passphrase {SECRET}")

    tr = Translator("fr")  # English reports a bare count; a translated locale lists each refused frame with its reason
    assert tr.f("{x}", x=_Boom()) == "{x}", "a frame that cannot be filled comes back as it is"
    assert tr.f("{x}", x=_Boom()) == "{x}", "asked again, it answers the same and logs once"
    (row,) = tr.report()["rejected_strings"]
    assert row["text"] == "{x}"
    assert row["reason"] == "the frame could not be filled (ValueError)"
    _class_only_absent(row)
    from src.monitoring.secret_scrub import TRACEBACK_ATTRIBUTE

    rec = _logged(caplog, "src.bulletin.i18n", "a frame could not be filled")
    text = logging.Formatter("%(message)s").format(rec) + str(getattr(rec, TRACEBACK_ATTRIBUTE, ""))
    assert rec.exc_info is None and "ValueError" in text and WORDS in text and SECRET not in text, text


# --------------------------------------------------------------------------- #
#  the model layers: the introduction, a story, the whole run
# --------------------------------------------------------------------------- #
class _FailingModel:
    def generate(self, *_a, **_k):
        raise _failure()


def test_a_failing_model_gives_the_introduction_a_class_only_reason_and_a_scrubbed_log_line(caplog):
    from src.bulletin.introduction import narrate_introduction
    from tests.test_bulletin_introduction import _edition

    out = narrate_introduction(_edition(), client=_FailingModel(), model="m", backend="b")
    assert out["narrated"] is False and out["fallback_reason"] == "the model call failed (RuntimeError)"
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.introduction", "introduction narration failed"))


def test_a_failing_model_gives_a_story_a_class_only_reason_and_a_scrubbed_log_line(caplog):
    from src.bulletin.narration import narrate_story
    from tests.test_bulletin_narration import _EVIDENCE, _STORY

    out = narrate_story(_STORY, _EVIDENCE, client=_FailingModel(), model="m", backend="b")
    assert out["narrated"] is False and out["fallback_reason"] == "the model call failed (RuntimeError)"
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.narration", "narration call failed"))


def test_the_outage_marker_the_job_retries_on_still_reads_a_class_only_reason():
    from src.bulletin.narration_job import _is_outage

    assert _is_outage({"narrated": False, "fallback_reason": "the model call failed (RuntimeError)"})


def test_a_run_with_no_backend_and_a_story_with_no_evidence_keep_the_class_and_log_scrubbed(monkeypatch, caplog):
    from src.bulletin.narration import narrate
    from tests.test_bulletin_narration import _EVIDENCE, _STORY

    monkeypatch.setattr("src.llm.backend.get_client_with_name", _raise)
    out = narrate([_STORY], lambda _s: _EVIDENCE)
    assert out["available"] is False and out["reason"] == "no local model is available (RuntimeError)"
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.narration", "no LLM backend for narration"))

    caplog.clear()
    out = narrate([_STORY], _raise, client=_FailingModel())
    (para,) = out["paragraphs"]
    assert para["fallback_reason"] == "evidence unavailable (RuntimeError)"
    _no_secret(out)
    _scrubbed(_logged(caplog, "src.bulletin.narration", "evidence unavailable for a story"))


# --------------------------------------------------------------------------- #
#  the narration job: no model, a failing unit, a failing introduction unit
# --------------------------------------------------------------------------- #
@pytest.fixture
def _job(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    from tests import test_bulletin_narration_job as tj

    return tj


def test_a_job_with_no_backend_is_refused_with_the_class_and_logs_the_words_scrubbed(_job, monkeypatch, caplog):
    from src.bulletin import narration_job as NJ

    monkeypatch.setattr("src.llm.backend.get_client_with_name", _raise)
    ctx = _job._Ctx()
    out = NJ.run_bulletin_narration_job(
        ctx,
        filename=_job._edition(1),
        client=None,
        session_factory=_job._sf,
        gate=dict(_job._OPEN_GATE),
    )
    assert out["state"] == "refused" and "no local model is available (RuntimeError)" in json.dumps(out)
    _no_secret(out)
    _no_secret(ctx.progress)
    _scrubbed(_logged(caplog, "bulletin.narration_job", "no local model for the narration job"))


def test_a_unit_whose_evidence_cannot_be_read_is_written_with_the_class_and_logged_scrubbed(_job, monkeypatch, caplog):
    from src.bulletin.store import read_edition

    monkeypatch.setattr("src.bulletin.stories.story_evidence", _raise)
    fn = _job._edition(1)
    out = _job._run(fn)
    _no_secret(out)
    record = read_edition(fn)
    _no_secret(record)
    assert "evidence unavailable (RuntimeError)" in json.dumps(record)
    _scrubbed(_logged(caplog, "bulletin.narration_job", "narration unit 0 failed"))


def test_an_introduction_unit_that_raises_is_written_with_the_class_and_logged_scrubbed(_job, monkeypatch, caplog):
    from src.bulletin.store import read_edition

    _job._evidence(monkeypatch)
    monkeypatch.setattr("src.bulletin.introduction.narrate_introduction", _raise)
    fn = _job._edition(1)
    out = _job._run(fn, introduction=True)
    _no_secret(out)
    record = read_edition(fn)
    _no_secret(record)
    assert "evidence unavailable (RuntimeError)" in json.dumps(record)
    assert [r for r in caplog.records if r.name == "bulletin.narration_job" and "narration unit" in r.getMessage()]
    for rec in [r for r in caplog.records if r.name == "bulletin.narration_job" and "narration unit" in r.getMessage()]:
        _scrubbed(rec)


# --------------------------------------------------------------------------- #
#  the quarantine count, the temp sweep
# --------------------------------------------------------------------------- #
def test_an_unreadable_quarantine_count_is_unknown_and_logged_scrubbed(caplog):
    from src.bulletin.privacy import quarantined_in_period

    assert quarantined_in_period(_Poisoned(), _period()) is None
    _scrubbed(_logged(caplog, "src.bulletin.privacy", "could not count quarantined articles"))


def test_a_temp_sweep_that_fails_is_logged_scrubbed_at_debug_and_never_raises(caplog):
    from src.bulletin.store import _sweep

    class _Folder:
        def glob(self, _pattern):
            raise _failure()

    caplog.set_level(logging.DEBUG, logger="src.bulletin.store")
    _sweep(_Folder())
    _scrubbed(_logged(caplog, "src.bulletin.store", "edition temp sweep failed"))


# --------------------------------------------------------------------------- #
#  the routes: what the operator is told, and that no cause is chained on
# --------------------------------------------------------------------------- #
@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "src.bulletin.gate.bulletin_available",
        lambda **_k: {"available": True, "narration_available": True, "reason": "test", "narration_reason": "test"},
    )
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        yield _empty_session()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _told(response, status: int) -> str:
    assert response.status_code == status, response.text
    assert SECRET not in response.text, response.text
    return json.dumps(response.json())


def test_a_refused_period_tells_the_operator_the_words_without_the_passphrase(api, monkeypatch):
    monkeypatch.setattr("src.bulletin.period.resolve_period", _value_raise)
    for call in (
        lambda: api.post("/api/bulletin/generate?cadence=weekly"),
        lambda: api.post("/api/bulletin/evidence/plan?cadence=weekly"),
        lambda: api.post("/api/bulletin/evidence/build?cadence=weekly&dest=/tmp"),
    ):
        assert WORDS in _told(call(), 400)


def test_an_edition_that_cannot_be_written_is_returned_with_the_class_and_the_scrubbed_words(api, monkeypatch):
    monkeypatch.setattr("src.bulletin.edition.build_edition", lambda *_a, **_k: {"masthead": {}})
    monkeypatch.setattr("src.bulletin.store.persist_edition", _os_raise)
    body = api.post("/api/bulletin/generate?cadence=weekly")
    _told(body, 200)
    persist_error = body.json()["persist_error"]
    assert body.json()["persisted"] is False and persist_error.startswith("OSError: ") and WORDS in persist_error, persist_error


def test_an_edition_on_disk_that_cannot_be_read_says_so_and_chains_no_cause(api, monkeypatch):
    monkeypatch.setattr("src.bulletin.store.read_edition", _value_raise)
    assert "edition unreadable" in _told(api.get("/api/bulletin/editions/x.json"), 500)

    def _missing(*_a, **_k):
        raise FileNotFoundError(f"{WORDS}: {SECRET}")

    monkeypatch.setattr("src.bulletin.store.read_edition", _missing)
    assert "no such edition" in _told(api.get("/api/bulletin/editions/x.json"), 404)


@pytest.mark.parametrize("reading", ["unreadable", "missing"])
def test_the_edition_routes_raise_their_refusal_with_no_cause_chained_on(api, monkeypatch, reading):
    """``from None`` sets ``__suppress_context__``; ``from exc`` would set ``__cause__``, and a traceback prints the cause's message."""
    from fastapi import HTTPException

    from src.api import bulletin as route

    def _missing(*_a, **_k):
        raise FileNotFoundError(f"{WORDS}: {SECRET}")

    monkeypatch.setattr("src.bulletin.store.read_edition", _value_raise if reading == "unreadable" else _missing)
    with pytest.raises(HTTPException) as caught:
        route.edition("x.json")
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


def test_a_narration_refusal_tells_the_operator_the_words_without_the_passphrase(api, monkeypatch):
    from src.api import bulletin as route
    from src.bulletin.narration_job import NarrationScopeMismatch

    monkeypatch.setattr("src.bulletin.store.read_edition", lambda *_a, **_k: {})

    def _running(**_k):
        raise RuntimeError(f"{WORDS}: {STATEMENT}, passphrase {SECRET}")

    monkeypatch.setattr(route._NARRATION_JOB, "start", _running)
    monkeypatch.setattr(route._NARRATION_JOB, "status", lambda: {"state": "running"})
    told = _told(api.post("/api/bulletin/editions/x.json/narrate"), 409)
    assert WORDS in told and '"state": "running"' in told

    def _mismatch(**_k):
        raise NarrationScopeMismatch(f"{WORDS}: passphrase {SECRET}", state={"cursor": 3, "filename": "other.json"})

    monkeypatch.setattr(route._NARRATION_JOB, "start", _mismatch)
    told = _told(api.post("/api/bulletin/editions/x.json/narrate"), 409)
    assert WORDS in told and '"cursor": 3' in told and "other.json" in told, "the run's own state travels with the reason"


def test_a_publish_that_cannot_be_stamped_or_an_archive_that_cannot_be_written_tells_the_operator_without_the_passphrase(api, monkeypatch, tmp_path):
    monkeypatch.setattr("src.bulletin.store.read_edition", lambda *_a, **_k: {"period": {}, "sections": []})
    monkeypatch.setattr("src.bulletin.store.mark_published", _os_raise)
    assert "could not stamp the edition" in _told(api.post("/api/bulletin/editions/x.json/publish"), 500)

    monkeypatch.setattr("src.bulletin.evidence.build_evidence_archive", _os_raise)
    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {})
    told = _told(api.post(f"/api/bulletin/evidence/build?cadence=weekly&dest={tmp_path}"), 500)
    assert "could not write the archive" in told and WORDS in told


def test_the_exports_refuse_with_the_words_without_the_passphrase(api, monkeypatch):
    monkeypatch.setattr("src.bulletin.store.read_edition", lambda *_a, **_k: {"period": {"cadence": "weekly"}, "sections": []})
    monkeypatch.setattr("src.bulletin.privacy.export_privacy", _value_raise)
    assert WORDS in _told(api.get("/api/bulletin/editions/x.json/export-privacy?kind=annexes"), 400)
    monkeypatch.setattr("src.bulletin.render.render", _value_raise)
    assert WORDS in _told(api.get("/api/bulletin/editions/x.json/render?fmt=markdown"), 400)
