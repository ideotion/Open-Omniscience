"""Auto-on-ingest: run the user's ENABLED, ``run_on_ingest`` custom extractors over recent
articles, OFF the scrape hot path.

Wired into the scheduler's post-pass housekeeping — NEVER inline at ingest, because a local
model in the scrape loop would stall collection (seconds per article). Opt-in by
construction: with no auto prompts (the default) this is a single empty query, so the cost
is zero until the user flips a prompt's "run automatically on new articles" toggle.
``skip_existing`` means only NEW articles cost a model call; already-processed ones are a
cheap DB skip, so the backlog drains over passes without re-paying. Results are
``ai_keyword`` rows of each prompt's ``output_kind`` (the unified, labelled-unreliable AI
lens) — NEVER the trusted keyword index.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ai_layer.jobs import ArticleWork, extract_for_articles
from src.database.models import AiCustomPrompt, Article
from src.llm.ollama import DEFAULT_MODEL, OllamaClient

logger = logging.getLogger(__name__)

#: Recent articles scanned per pass. ``skip_existing`` drains any backlog over passes, so a
#: bound here just caps per-pass LLM work — new articles beyond it are picked up next pass.
AUTO_LIMIT = 50


def _active_model() -> str:
    """The operator's chosen model (stored UI setting) else the built-in default — resolved
    here so the scheduler never has to import the API layer. Never fatal."""
    try:
        from src.config.app_settings import load_settings

        return load_settings().llm_model or DEFAULT_MODEL
    except Exception:  # noqa: BLE001 - a settings hiccup must not break a scrape
        return DEFAULT_MODEL


def due_auto_prompts(session: Session) -> list[AiCustomPrompt]:
    """The custom extractors that are BOTH enabled and flagged to run on new articles."""
    return list(
        session.execute(
            select(AiCustomPrompt).where(
                AiCustomPrompt.enabled.is_(True),
                AiCustomPrompt.run_on_ingest.is_(True),
            )
        ).scalars()
    )


def _recent_work(session: Session, limit: int) -> list[ArticleWork]:
    """The most recent articles as plain snapshots (the job never holds the ORM session)."""
    rows = session.execute(
        select(Article.id, Article.title, Article.content, Article.language)
        .order_by(Article.id.desc())
        .limit(limit)
    ).all()
    return [ArticleWork(r[0], r[1] or "", r[2] or "", r[3]) for r in rows]


def run_auto_on_ingest(
    session: Session,
    client: OllamaClient | None = None,
    *,
    model: str | None = None,
    limit: int = AUTO_LIMIT,
) -> dict:
    """Run every DUE (enabled + ``run_on_ingest``) custom extractor over the most recent
    ``limit`` articles. Best-effort + bounded; never raises.

    Returns a tally ``{prompts, ran, stored, skipped, failed}``. ``ran`` is ``False`` when
    there are no auto prompts (the default) or the local model is unavailable — in the
    latter case we do nothing rather than spam failed events. One prompt failing never
    stops the others."""
    out: dict = {"prompts": 0, "ran": False, "stored": 0, "skipped": 0, "failed": 0}
    try:
        prompts = due_auto_prompts(session)
    except Exception:  # noqa: BLE001
        logger.warning("auto-on-ingest: could not list prompts", exc_info=True)
        return out
    out["prompts"] = len(prompts)
    if not prompts:
        return out
    client = client or OllamaClient()
    try:
        if not client.is_available():
            return out  # local model down -> no-op (never a wall of failed events)
    except Exception:  # noqa: BLE001
        return out
    work = _recent_work(session, limit)
    if not work:
        return out
    mdl = model or _active_model()
    out["ran"] = True
    for p in prompts:
        try:
            for event in extract_for_articles(
                work,
                client,
                model=mdl,
                kind=p.output_kind,
                system=p.prompt_text,
                prompt_version=f"custom:{p.id}",
                skip_existing=True,
            ):
                if event.get("event") == "item":
                    st = event.get("status")
                    if st in ("stored", "skipped", "failed"):
                        out[st] += 1
        except Exception:  # noqa: BLE001 - one bad prompt never breaks the others
            logger.warning("auto-on-ingest: prompt %s failed", p.id, exc_info=True)
    return out
