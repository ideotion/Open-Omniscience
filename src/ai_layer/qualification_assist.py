"""
LLM QUALIFICATION ASSIST -- propose-only nav-soup/extraction-junk flagging (B7.2,
2026-07-24 field-feedback Session B, ruled "propose-only").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Scope (ruled): an LLM pass over a source's TRIAL-FETCH articles (its already-
stored ``Article`` rows -- the qualification lifecycle's
``src.catalog.qualification.trial_fetch`` stores whatever it collects as
normal articles, "no wasted fetch") flagging nav-soup/extraction-junk
signatures, as a PROPOSALS LOG beside the auditor's own evidence
(``src.analytics.source_audit``, ``src.services.prose_gate``) -- NEVER
auto-decides, NEVER touches ``Source.status``/``Source.tags``. Composes with
the qualification lifecycle as an ADDITIONAL, human-reviewed signal (the same
ai-proposed -> claude-verified -> maintainer-merged provenance chain the §8
triage/source-tag runs use), never a replacement for the deterministic
rule-based auditor that actually gates admission.

HONESTY BY CONSTRUCTION (mirrors ``src/ai_layer/triage.py``'s doctrine):
  * CONSTRAINED, PARSEABLE output: the model must reply with EXACTLY one word
    -- ``article`` or ``junk``. Anything else (a refusal, commentary, a third
    word) is unparseable and stores NOTHING for that article (miss over
    invent -- the B15/echo-back precedent).
  * CANARIES: a fixed, hand-known genuine-article snippet and a fixed,
    hand-known nav-soup snippet ride EVERY run (never corpus-derived), a
    tripwire against model drift.
  * NEVER writes ``Source.status``/``Source.tags``/anything else on the
    ``Source`` row -- this module's only output is a dict + (via
    ``run_and_persist_qualification_assist``) one dated JSONL proposals log.
"""

from __future__ import annotations

QUALIFICATION_ASSIST_PROMPT_VERSION = "qualification-assist-v1"

_SYSTEM_PROMPT = (
    "You are checking whether a stored web page is a genuine news/investigative "
    "ARTICLE or NAV-SOUP (a navigation menu, a bare list of links, a category/tag "
    "index page, a paywall/subscription/error page, or other non-article "
    "boilerplate with no real narrative content). Reply with EXACTLY one word: "
    "article or junk. Nothing else -- no punctuation, no explanation."
)

# Keep the prompt small -- a genre judgement needs far less text than a full
# who/where/when extraction (mirrors the project's per-feature _MAX_CHARS convention).
_MAX_CHARS = 4000

# Fixed, hand-known CANARY pair -- never corpus-derived, so the model cannot learn
# to special-case them from the batch itself (the triage-run canary convention).
CANARY_ARTICLE_TEXT = (
    "Reporters interviewed dozens of residents after the storm swept through the "
    "coastal town on Tuesday, leaving widespread damage to homes and roads. Local "
    "officials said recovery efforts were expected to take several weeks, and "
    "emergency shelters remained open for displaced families."
)
CANARY_JUNK_TEXT = (
    "Home | News | Sports | Entertainment | Business | Subscribe | Contact Us | "
    "Privacy Policy | Terms of Service | Advertise With Us | (c) 2024 All rights "
    "reserved."
)


def build_system() -> str:
    """The qualification-assist system prompt (constrained, one-word reply)."""
    return _SYSTEM_PROMPT


def parse_verdict(raw: str | None) -> str | None:
    """``"article"``/``"junk"`` on an exact (case/punctuation-insensitive) match --
    a refusal, extra commentary, or a third word is unparseable and yields
    ``None`` (never guessed, never coerced to a 'close' value)."""
    s = (raw or "").strip().strip("\"'.,;:!?").strip().lower()
    return s if s in ("article", "junk") else None


def classify_article_for_qualification(
    client, title: str | None, content: str | None, *, model: str, keep_alive: str | None = None
) -> str | None:
    """Ask the active backend whether ONE article's text reads as a genuine
    article or nav-soup. Returns ``"article"``/``"junk"``/``None`` (empty text
    or an unparseable reply). Raises the client's LLMUnavailable/LLMError up
    (the caller decides how to handle an outage)."""
    title = (title or "").strip()
    content = (content or "").strip()
    text = f"{title}\n\n{content}".strip() if title else content
    if not text:
        return None
    result = client.generate(
        text[:_MAX_CHARS], model=model, system=_SYSTEM_PROMPT, keep_alive=keep_alive
    )
    return parse_verdict(getattr(result, "text", None))


def check_canaries(client, *, model: str, keep_alive: str | None = None) -> dict:
    """Run the fixed canary pair through the SAME classifier used for real
    articles. Returns ``{"ok": bool, "article_verdict", "junk_verdict"}`` -- a
    tripwire the caller can surface alongside the real proposals, never a
    hard gate (a canary miss is a signal to distrust this run, not a crash)."""
    article_v = classify_article_for_qualification(
        client, "Storm recovery underway", CANARY_ARTICLE_TEXT, model=model, keep_alive=keep_alive
    )
    junk_v = classify_article_for_qualification(
        client, "", CANARY_JUNK_TEXT, model=model, keep_alive=keep_alive
    )
    return {
        "ok": article_v == "article" and junk_v == "junk",
        "article_verdict": article_v,
        "junk_verdict": junk_v,
    }


def propose_qualification_flags(
    session,
    source_id: int,
    client,
    *,
    model: str,
    max_articles: int = 20,
    keep_alive: str | None = None,
) -> dict:
    """Classify up to ``max_articles`` of ``source_id``'s STORED articles
    (newest first) as article/junk via the active model -- a PROPOSAL, never a
    decision: ``Source.status``/``Source.tags`` are NEVER touched here (the
    caller may log this dict; nothing about the source row changes).

    Returns ``{"source_id", "model", "prompt_version", "canary", "checked",
    "article_count", "junk_count", "unparseable_count", "flagged": [...]}``
    where ``flagged`` lists every article the model called ``junk``
    (id/title/verdict -- a proposal for the maintainer/Claude-verification
    loop to review, never applied automatically). An empty article set (a
    source with nothing stored yet) yields an honest zero-checked result,
    never a fabricated verdict."""
    from src.database.models import Article

    canary = check_canaries(client, model=model, keep_alive=keep_alive)

    rows = (
        session.query(Article.id, Article.title, Article.content)
        .filter(Article.source_id == source_id)
        .order_by(Article.id.desc())
        .limit(max_articles)
        .all()
    )

    flagged: list[dict] = []
    article_count = junk_count = unparseable_count = 0
    for article_id, title, content in rows:
        verdict = classify_article_for_qualification(
            client, title, content, model=model, keep_alive=keep_alive
        )
        if verdict is None:
            unparseable_count += 1
        elif verdict == "junk":
            junk_count += 1
            flagged.append({
                "article_id": int(article_id),
                "title": (title or "")[:120],
                "verdict": "junk",
            })
        else:
            article_count += 1

    return {
        "source_id": source_id,
        "model": model,
        "prompt_version": QUALIFICATION_ASSIST_PROMPT_VERSION,
        "canary": canary,
        "checked": len(rows),
        "article_count": article_count,
        "junk_count": junk_count,
        "unparseable_count": unparseable_count,
        "flagged": flagged,
    }


def run_qualification_assist_selftest() -> dict:
    """Prove the parser + the classify-and-tally mechanism on a deterministic
    STUB (no model, no network) -- mirrors ``run_triage_selftest``/
    ``run_perception_eval_selftest``: a regression here reddens both the
    in-app self-test and CI."""

    class _StubClient:
        def generate(self, prompt, *, model, system=None, keep_alive=None):
            low = prompt.lower()
            if "storm" in low or "residents" in low:
                text = "article"
            elif "subscribe" in low or "privacy policy" in low:
                text = "junk"
            else:
                text = "I cannot determine that."  # unparseable on purpose
            return type("R", (), {"text": text})()

    class _FakeSession:
        def __init__(self, rows):
            self._rows = rows

        def query(self, *a, **kw):
            return self

        def filter(self, *a, **kw):
            return self

        def order_by(self, *a, **kw):
            return self

        def limit(self, *a, **kw):
            return self

        def all(self):
            return self._rows

    rows = [
        (1, "Storm coverage", CANARY_ARTICLE_TEXT),
        (2, "", CANARY_JUNK_TEXT),
        (3, "Odd page", "asdkjasldkjaslkdj this is nonsense text with no real signal"),
    ]
    out = propose_qualification_flags(
        _FakeSession(rows), source_id=1, client=_StubClient(), model="stub:test"
    )
    checks = {
        "canary_ok": out["canary"]["ok"] is True,
        "checked_all_three": out["checked"] == 3,
        "article_counted": out["article_count"] == 1,
        "junk_counted": out["junk_count"] == 1,
        "unparseable_counted": out["unparseable_count"] == 1,
        "junk_article_flagged": out["flagged"] == [{"article_id": 2, "title": "", "verdict": "junk"}],
    }
    return {
        "schema": "oo-qualification-assist-selftest-1",
        "passed": all(checks.values()),
        "checks": checks,
        "result": out,
    }


QUALIFICATION_ASSIST_SCHEMA = "oo-qualification-assist-1"


def _dir():
    from src.paths import data_dir

    d = data_dir() / "triage"  # the one AI-run archive, shared with triage/source-tags/perception logs
    d.mkdir(parents=True, exist_ok=True)
    return d


def _export_path(source_id: int):
    from datetime import datetime

    return _dir() / f"oo-qualification-assist-{source_id}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"


def run_and_persist_qualification_assist(
    session,
    source_id: int,
    client=None,
    *,
    model: str | None = None,
    max_articles: int = 20,
    keep_alive: str | None = None,
) -> dict:
    """Run :func:`propose_qualification_flags` for ``source_id`` and persist the
    dated JSON artifact (mirrors ``perception_job.run_and_persist_perception_
    eval``'s pattern -- a bounded, one-shot diagnostic run, NOT a background
    job, since it is scoped to one source's small trial-fetch article set).
    Resolves the active backend/model when not injected. NEVER writes the
    ``Source`` row -- the ONLY write is this one proposals log file."""
    import json
    from datetime import datetime

    if client is None or model is None:
        from src.api.llm import active_model
        from src.llm.backend import get_client_with_name

        backend_name, resolved_client = get_client_with_name()
        client = client or resolved_client
        model = model or active_model()

    out = propose_qualification_flags(
        session, source_id, client, model=model, max_articles=max_articles, keep_alive=keep_alive
    )
    out["schema"] = QUALIFICATION_ASSIST_SCHEMA
    out["run_at"] = datetime.now().isoformat(timespec="seconds")
    path = _export_path(source_id)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    out["path"] = str(path)
    out["filename"] = path.name
    return out


def last_qualification_assist_report(source_id: int | None = None) -> dict:
    """The newest saved proposals artifact -- optionally filtered to ONE
    ``source_id`` (else the newest across every source ever checked). Read-
    only; never runs anything. Honest ``{available: False}`` stub when none
    exists (for that source, or at all)."""
    import json

    try:
        pattern = (
            f"oo-qualification-assist-{source_id}-*.json"
            if source_id is not None
            else "oo-qualification-assist-*.json"
        )
        files = sorted(_dir().glob(pattern))
        if not files:
            return {
                "schema": QUALIFICATION_ASSIST_SCHEMA,
                "available": False,
                "note": (
                    "no qualification-assist run has been made yet -- run it from "
                    "Settings -> AI, or POST /api/diagnostics/qualification-assist/run."
                ),
            }
        path = files[-1]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["available"] = True
        data["filename"] = path.name
        return data
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {"schema": QUALIFICATION_ASSIST_SCHEMA, "available": False, "error": str(exc)[:300]}


__all__ = [
    "CANARY_ARTICLE_TEXT",
    "CANARY_JUNK_TEXT",
    "QUALIFICATION_ASSIST_PROMPT_VERSION",
    "QUALIFICATION_ASSIST_SCHEMA",
    "build_system",
    "check_canaries",
    "classify_article_for_qualification",
    "last_qualification_assist_report",
    "parse_verdict",
    "propose_qualification_flags",
    "run_and_persist_qualification_assist",
    "run_qualification_assist_selftest",
]
