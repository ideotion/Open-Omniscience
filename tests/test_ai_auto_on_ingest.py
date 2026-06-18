"""Auto-on-ingest: ENABLED + run_on_ingest custom extractors run over recent articles,
OFF the scrape hot path (the scheduler's post-pass housekeeping).

These pin the gating + wiring — the bits that make it opt-in by construction and
best-effort — without the global engine: extract_for_articles itself is covered by
tests/test_ai_keyword_extract.py, so here it is stubbed to assert the call shape.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import auto as ai_auto
from src.database.models import AiCustomPrompt, Article, Base, Source


def _sess(tmp_path, name="auto.db"):
    eng = create_engine(
        f"sqlite:///{tmp_path / name}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)


class _StubClient:
    def __init__(self, up=True):
        self._up = up

    def is_available(self):
        return self._up


def _prompt(label="P", kind="figure", enabled=True, on_ingest=True):
    return AiCustomPrompt(
        label=label, output_kind=kind, prompt_text="extract X",
        run_on_ingest=on_ingest, enabled=enabled,
    )


def _article(sess):
    sess.add(Source(name="N", domain="n.test"))
    sess.commit()
    sess.add(Article(
        url="u", canonical_url="u", source_id=1, title="T",
        content="body", hash="h", language="en", created_at=datetime.now(UTC),
    ))
    sess.commit()


def test_due_auto_prompts_filters_enabled_and_on_ingest(tmp_path):
    S = _sess(tmp_path)
    with S() as s:
        s.add_all([
            _prompt("auto", enabled=True, on_ingest=True),
            _prompt("manual", enabled=True, on_ingest=False),
            _prompt("disabled", enabled=False, on_ingest=True),
        ])
        s.commit()
        assert [p.label for p in ai_auto.due_auto_prompts(s)] == ["auto"]


def test_no_auto_prompts_is_a_noop(tmp_path):
    """The default state: a non-auto prompt exists but nothing runs (zero cost)."""
    S = _sess(tmp_path)
    with S() as s:
        s.add(_prompt(enabled=True, on_ingest=False))
        s.commit()
        out = ai_auto.run_auto_on_ingest(s, _StubClient(up=True))
        assert out["ran"] is False and out["prompts"] == 0


def test_client_unavailable_does_not_run(tmp_path):
    """Local model down -> no-op (never a wall of failed events)."""
    S = _sess(tmp_path)
    with S() as s:
        s.add(_prompt())
        s.commit()
        out = ai_auto.run_auto_on_ingest(s, _StubClient(up=False))
        assert out["ran"] is False and out["prompts"] == 1


def test_runs_due_prompt_with_correct_args(tmp_path, monkeypatch):
    S = _sess(tmp_path)
    with S() as s:
        _article(s)
        s.add(_prompt(label="Figures", kind="figure"))
        s.commit()

        calls: dict = {}

        def fake_extract(work, client, *, model, kind, system, prompt_version,
                         skip_existing, **kw):
            calls.update(kind=kind, system=system, prompt_version=prompt_version,
                         skip_existing=skip_existing, n=len(work))
            yield {"event": "start", "total": len(work)}
            yield {"event": "item", "status": "stored"}
            yield {"event": "done"}

        monkeypatch.setattr(ai_auto, "extract_for_articles", fake_extract)
        out = ai_auto.run_auto_on_ingest(s, _StubClient(up=True))

        assert out["ran"] is True and out["stored"] == 1
        assert calls["kind"] == "figure" and calls["system"] == "extract X"
        assert calls["prompt_version"].startswith("custom:") and calls["skip_existing"] is True
        assert calls["n"] == 1  # the one recent article, as a snapshot
