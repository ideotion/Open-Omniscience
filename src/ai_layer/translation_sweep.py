"""The AI-coordinator TRANSLATION SWEEPS (brief S05-08, gate row H of 0.5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two coordinator members, both ``≈`` by construction and neither ever the article nor
the trusted keyword index:

* **The keyword sweep** (Q405, S1). Walks the head of the keyword vocabulary -- the
  ``HEAD`` most-spread keywords, in the triage sweep's own keyset order -- and asks the
  local model for a TENTATIVE translation of every term no verified Wikidata ring
  covers and no earlier run already answered. Answers go to ``keyword_translations``
  (Q404's table) through :func:`src.analytics.translation_store.record_tentative`, so
  every keyword surface that walks the three-tier ladder shows them, ``≈``-marked,
  without being touched. At the end of every pass -- and every few batches during one --
  it writes its COVERAGE down (:func:`src.monitoring.kpi.record_sweep_coverage`), which
  is what KPI K6 reads. The recorded K6 lesson is the reason: a figure computed only on
  demand is a figure the board can never show.

* **The title sweep** (Q513 = b, S2). OPT-IN. Walks the newest articles whose language
  differs from the target and writes a ``≈`` title and a one-sentence gist of the
  article's OPENING into ``article_title_translations`` -- never into ``articles``.

WHICH LANGUAGE. Both translate into the INTERFACE language, which only the browser
knows; the SPA reports it on boot and on every switch (``POST
/api/ai/interface-language``), and it is kept in ``app_state``. When several browsers
use different languages, the last one to report wins, and the sweep says which
language it is filling. With none reported yet the sweep does nothing and says so --
it never guesses English.

WHAT IS PROPOSED, NOT RULED. The head size (``OO_TRANSLATION_SWEEP_HEAD``, 2,000
keywords; ``OO_TITLE_SWEEP_HEAD``, 500 articles) and the re-pass interval are the
brief's "the coordinator's budget, measured on the reference VM, then stated" (§6): the
numbers here are starting points stated as such, and each is an environment knob.

Local loopback only: the clients refuse a non-loopback backend under airplane mode,
and nothing here opens a socket of its own.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.jobs.progress_state import load_progress_state, save_progress_state

_LOG = logging.getLogger("ai_layer.translation_sweep")

#: The interface language the SPA last reported (``app_state`` key).
INTERFACE_LANG_KEY = "ui.interface_lang"

KEYWORD_BATCH = 25
TITLE_BATCH = 5
#: A proposed default (brief §6), never a ruling: the keyword head the sweep keeps
#: translated, in the triage sweep's order (article spread, then mentions).
DEFAULT_KEYWORD_HEAD = 2000
DEFAULT_TITLE_HEAD = 500
#: How long a finished pass rests before the next one looks for new keywords/articles.
REPASS_AFTER = timedelta(hours=6)
#: Coverage is re-measured every this many batches inside a pass, and always at its end.
COVERAGE_EVERY_BATCHES = 10
#: What the title sweep shows the model: the title and this much of the opening.
OPENING_CHARS = 1500

TITLE_PROMPT_VERSION = "title-gist-v1"

_KEYWORD_STATE = "translation_sweep_progress_state.json"
_TITLE_STATE = "title_sweep_progress_state.json"


def _head(env: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(env, str(default))))
    except ValueError:
        return default


def _state_dir() -> Path:
    from src.paths import data_dir

    d = Path(data_dir()) / "triage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
#  The target language
# --------------------------------------------------------------------------- #
def record_interface_lang(code: str | None) -> str | None:
    """Store the interface language the SPA reports. Returns the stored code, or None
    when the code is not a plain ISO-639 code (nothing is stored then)."""
    from src.analytics.managed import normalize_lang

    c = normalize_lang(code)
    if not c or not c.isalpha() or len(c) > 3:
        return None
    from src.config.kv_store import kv_set_json

    kv_set_json(INTERFACE_LANG_KEY, {"lang": c, "reported_at": _iso(_now())})
    return c


def interface_lang() -> str | None:
    """The last interface language a browser reported, or None when none ever did."""
    try:
        from src.config.kv_store import kv_get_json

        rec = kv_get_json(INTERFACE_LANG_KEY) or {}
    except Exception:  # noqa: BLE001 - an unreadable store is "not reported yet"
        return None
    lang = rec.get("lang")
    return lang if isinstance(lang, str) and lang else None


# --------------------------------------------------------------------------- #
#  The pass bookkeeping both sweeps share
# --------------------------------------------------------------------------- #
def _fresh_pass(state: dict, *, target: str, model: str, prompt_version: str, now: datetime) -> dict:
    """The state to run from: the saved one when it is the same pass, a new one when the
    target, the model or the prompt changed, or a finished pass has rested long enough."""
    same = (
        state.get("target_lang") == target
        and state.get("model") == model
        and state.get("prompt_version") == prompt_version
    )
    if same and state.get("pass_completed_at"):
        try:
            done = datetime.fromisoformat(state["pass_completed_at"])
        except ValueError:
            done = None
        if done is not None and now - done < REPASS_AFTER:
            return state  # rested pass: the caller reports complete
        same = False  # a rested-long-enough pass restarts to pick up new items
    if same:
        return state
    return {
        "target_lang": target,
        "model": model,
        "prompt_version": prompt_version,
        "pass_started_at": _iso(now),
        "cursor": None,
        "position": 0,
        "batches": 0,
        "totals": {},
    }


def _bump(totals: dict, key: str, n: int = 1) -> None:
    totals[key] = int(totals.get(key, 0)) + n


# --------------------------------------------------------------------------- #
#  S1 -- the keyword sweep
# --------------------------------------------------------------------------- #
def measure_keyword_coverage(session, target_lang: str, *, head: int) -> dict:
    """Where the keyword head stands for ``target_lang``, one count per ladder rung.

    Counts, never a share of anything: ``verified`` (a ring translates it),
    ``tentative`` (a model answered it, ``≈``), ``untranslated`` (neither yet),
    ``same_language`` (already in the target language) and ``no_language`` (the corpus
    holds no language for it, so there is nothing honest to translate FROM). The five
    add up to ``head_n``, the number of keywords actually looked at."""
    from src.ai_layer import triage as T
    from src.analytics.equivalence import _norm, translate_term
    from src.analytics.managed import normalize_lang
    from src.analytics.translation_store import tentative_translations

    items = T.select_triage_head(session, head, min_articles=1)
    tent = tentative_translations(session, [it.term for it in items], target_lang)
    counts = {"verified": 0, "tentative": 0, "untranslated": 0, "same_language": 0,
              "no_language": 0}
    for it in items:
        lang = normalize_lang(it.language)
        key = _norm(it.term)
        if not lang:
            counts["no_language"] += 1
        elif lang == target_lang:
            counts["same_language"] += 1
        elif translate_term(lang, key, target_lang):
            counts["verified"] += 1
        elif key in tent:
            counts["tentative"] += 1
        else:
            counts["untranslated"] += 1
    return {"target_lang": target_lang, "head_n": len(items), "head_cap": head, **counts}


def _hidden():
    try:
        from src.analytics.filters import hidden_set

        return hidden_set()
    except Exception:  # noqa: BLE001 - no filter settings: hide nothing extra
        return set()


def run_keyword_translation_sweep(
    ctx,
    *,
    model: str,
    max_batches: int | None = None,
    batch_size: int = KEYWORD_BATCH,
    head: int | None = None,
    target_lang: str | None = None,
    session_factory=None,
    client=None,
    state_path: Path | None = None,
    now=_now,
) -> dict:
    """Coordinator member: translate the keyword head into the interface language.

    Resumes from a persisted keyset cursor, skips a term a verified ring covers or an
    earlier answer already holds (from any model), and records every usable answer as
    a TENTATIVE row. A term with no corpus language is skipped and counted: "translated
    from" would otherwise have to be invented. A model that answers with the term
    itself, a refusal or a sentence stores nothing (``translate_keyword`` returns None).

    An unavailable model ends the turn with ``paused_reason`` and the cursor where it
    was -- the coordinator gives the next turn a fresh try; it is never a completion.
    """
    from src.ai_layer import triage as T
    from src.ai_layer.translate import TRANSLATE_PROMPT_VERSION, translate_keyword
    from src.analytics.equivalence import _norm, translate_term
    from src.analytics.managed import normalize_lang
    from src.analytics.translation_store import record_tentative, tentative_translations

    head = head or _head("OO_TRANSLATION_SWEEP_HEAD", DEFAULT_KEYWORD_HEAD)
    tgt = normalize_lang(target_lang) if target_lang else interface_lang()
    if not tgt:
        return {
            "complete": True,
            "note": "No interface language has been reported yet, so there is no language "
                    "to translate into. Open the app once and the sweep picks it up.",
        }
    if session_factory is None:
        from src.database.session import session_scope as session_factory
    path = state_path or (_state_dir() / _KEYWORD_STATE)
    t_now = now()
    state = _fresh_pass(load_progress_state(path), target=tgt, model=model,
                        prompt_version=TRANSLATE_PROMPT_VERSION, now=t_now)
    if state.get("pass_completed_at"):
        return {**state, "complete": True}
    if client is None:
        from src.llm.backend import get_client_with_name

        _, client = get_client_with_name()
    from src.llm.ollama import LLMError, LLMUnavailable

    hidden = _hidden()
    totals = dict(state.get("totals") or {})
    cursor = tuple(state["cursor"]) if state.get("cursor") else None
    batches_this_call = 0
    paused_reason: str | None = None
    complete = False
    while True:
        if getattr(ctx, "stopping", False):
            paused_reason = "cancelled — progress is saved"
            break
        if max_batches is not None and batches_this_call >= max_batches:
            break
        remaining = head - int(state.get("position", 0))
        if remaining <= 0:
            complete = True
            break
        with session_factory() as session:
            chunk = T.select_triage_batch_after(
                session, min(batch_size, remaining), min_articles=1, after=cursor  # type: ignore[arg-type]
            )
            if not chunk:
                complete = True
                break
            have = tentative_translations(session, [it.term for it in chunk], tgt)
            started = now()
            unavailable = False
            for it in chunk:
                key = _norm(it.term)
                lang = normalize_lang(it.language)
                if not key or key in hidden:
                    _bump(totals, "hidden")
                    continue
                if not lang:
                    _bump(totals, "no_language")
                    continue
                if lang == tgt:
                    _bump(totals, "same_language")
                    continue
                if translate_term(lang, key, tgt):
                    _bump(totals, "verified")
                    continue
                if key in have:
                    _bump(totals, "already_tentative")
                    continue
                try:
                    text = translate_keyword(client, it.term, lang, tgt, model=model)
                except LLMUnavailable as exc:
                    paused_reason = f"the local model is unavailable: {exc}"[:200]
                    unavailable = True
                    break
                except LLMError:
                    _bump(totals, "model_error")
                    continue
                if text and record_tentative(
                    session, term=it.term, source_lang=lang, target_lang=tgt, text=text,
                    model=model, prompt_version=TRANSLATE_PROMPT_VERSION, commit=True,
                ):
                    _bump(totals, "added")
                else:
                    _bump(totals, "no_usable_answer")
            if unavailable:
                break  # the cursor stays: the same chunk is retried next turn
            last = chunk[-1]
            cursor = (last.article_count or 0, last.mention_count or 0, last.keyword_id)  # type: ignore[assignment]
            state["cursor"] = list(cursor)  # type: ignore[arg-type]
            state["position"] = int(state.get("position", 0)) + len(chunk)
            state["batches"] = int(state.get("batches", 0)) + 1
            state["last_batch"] = {"started_at": _iso(started), "finished_at": _iso(now()),
                                   "terms_in": len(chunk)}
            batches_this_call += 1
            if state["batches"] % COVERAGE_EVERY_BATCHES == 0:
                _record_coverage(session, tgt, head, state)
        state["totals"] = totals
        save_progress_state(state, path)
        if hasattr(ctx, "set_progress"):
            ctx.set_progress(done=int(state.get("position", 0)), total=head)
    if complete:
        state["pass_completed_at"] = _iso(now())
        with session_factory() as session:
            _record_coverage(session, tgt, head, state)
    state["totals"] = totals
    save_progress_state(state, path)
    out: dict[str, Any] = {**state, "complete": complete}
    if paused_reason:
        out["paused_reason"] = paused_reason
    return out


def _record_coverage(session, tgt: str, head: int, state: dict) -> None:
    """Measure the head and persist it for KPI K6. Best-effort: a failed measurement
    records nothing, and K6 keeps showing the last one it has with its date."""
    try:
        from src.monitoring.kpi import record_sweep_coverage

        cov = measure_keyword_coverage(session, tgt, head=head)
        cov["model"] = state.get("model")
        cov["prompt_version"] = state.get("prompt_version")
        cov["pass_complete"] = bool(state.get("pass_completed_at"))
        record_sweep_coverage(cov)
    except Exception:  # noqa: BLE001 - a coverage side-record never ends a sweep
        _LOG.warning("translation sweep could not record its coverage", exc_info=True)


# --------------------------------------------------------------------------- #
#  S2 -- the title sweep (opt-in)
# --------------------------------------------------------------------------- #
_REFUSAL = re.compile(
    r"\b(as an ai|i (?:cannot|can't|am unable)|i'm sorry|sorry,|cannot translate)\b",
    re.IGNORECASE,
)
_LABEL = re.compile(r"^\s*(?:title|headline|summary|translation|traduction)\s*[:=]\s*", re.IGNORECASE)


def _one_line(raw: str | None, *, cap: int) -> str | None:
    """The first meaningful line of a model answer, cleaned; None when unusable."""
    for line in (raw or "").splitlines():
        s = _LABEL.sub("", line).strip().strip("\"'“”«»*").strip()
        if not s:
            continue
        if len(s) > cap or _REFUSAL.search(s):
            return None
        return s
    return None


def title_prompts(source_lang: str | None, target_lang: str) -> tuple[str, str]:
    """The two system prompts, pure so a test can read them."""
    from src.ai_layer.translate import lang_name

    src, tgt = lang_name(source_lang), lang_name(target_lang)
    title = (f"You translate one news HEADLINE from {src} into {tgt}. Output ONLY the "
             f"{tgt} headline, on one line, with no quotes and no explanation.")
    gist = (f"You are shown a headline and the OPENING of a news article in {src}. Write "
            f"ONE short sentence in {tgt} saying what the opening reports. Output only "
            "that sentence. Do not add anything the text does not say.")
    return title, gist


def translate_title(client, *, title: str, opening: str, source_lang: str | None,
                    target_lang: str, model: str) -> tuple[str | None, str | None]:
    """``(≈ title, ≈ one-sentence gist of the opening)``; either may be None."""
    from src.ai_layer.sampling import sweep_options

    sys_title, sys_gist = title_prompts(source_lang, target_lang)
    r = client.generate(title, model=model, system=sys_title, options=sweep_options())
    t_out = _one_line(getattr(r, "text", None), cap=300)
    if t_out and t_out.casefold() == title.strip().casefold():
        t_out = None  # an echo says nothing
    g_out = None
    if opening.strip():
        r2 = client.generate(f"Headline: {title}\n\n{opening}", model=model, system=sys_gist,
                             options=sweep_options())
        g_out = _one_line(getattr(r2, "text", None), cap=400)
    return t_out, g_out


def run_title_translation_sweep(
    ctx,
    *,
    model: str,
    max_batches: int | None = None,
    batch_size: int = TITLE_BATCH,
    head: int | None = None,
    target_lang: str | None = None,
    session_factory=None,
    client=None,
    state_path: Path | None = None,
    now=_now,
) -> dict:
    """Coordinator member (opt-in): ``≈`` titles for the newest foreign-language articles.

    Newest first by id, down to ``head`` articles. An article with no language (neither
    asserted nor detected) is skipped and counted rather than guessed at. The article
    row is READ ONLY -- the only write is ``article_title_translations``."""
    from sqlalchemy import func, select

    from src.analytics.managed import normalize_lang
    from src.database.models import Article, ArticleTitleTranslation

    head = head or _head("OO_TITLE_SWEEP_HEAD", DEFAULT_TITLE_HEAD)
    tgt = normalize_lang(target_lang) if target_lang else interface_lang()
    if not tgt:
        return {"complete": True,
                "note": "No interface language has been reported yet."}
    if session_factory is None:
        from src.database.session import session_scope as session_factory
    path = state_path or (_state_dir() / _TITLE_STATE)
    state = _fresh_pass(load_progress_state(path), target=tgt, model=model,
                        prompt_version=TITLE_PROMPT_VERSION, now=now())
    if state.get("pass_completed_at"):
        return {**state, "complete": True}
    if client is None:
        from src.llm.backend import get_client_with_name

        _, client = get_client_with_name()
    from src.llm.ollama import LLMError, LLMUnavailable

    totals = dict(state.get("totals") or {})
    batches_this_call = 0
    complete = False
    paused_reason: str | None = None
    while True:
        if getattr(ctx, "stopping", False):
            paused_reason = "cancelled — progress is saved"
            break
        if max_batches is not None and batches_this_call >= max_batches:
            break
        remaining = head - int(state.get("position", 0))
        if remaining <= 0:
            complete = True
            break
        after = state.get("cursor")
        with session_factory() as session:
            q = select(Article.id, Article.title, Article.language, Article.detected_language)
            if after:
                q = q.where(Article.id < int(after))
            rows = session.execute(q.order_by(Article.id.desc()).limit(min(batch_size, remaining))).all()
            if not rows:
                complete = True
                break
            ids = [r[0] for r in rows]
            done_ids = set(session.scalars(
                select(ArticleTitleTranslation.article_id).where(
                    ArticleTitleTranslation.article_id.in_(ids),
                    ArticleTitleTranslation.target_lang == tgt,
                    ArticleTitleTranslation.model == model,
                    ArticleTitleTranslation.prompt_version == TITLE_PROMPT_VERSION,
                )
            ))
            started = now()
            unavailable = False
            for aid, title, lang, det in rows:
                src = normalize_lang(lang or det)
                if not src:
                    _bump(totals, "no_language")
                    continue
                if src == tgt:
                    _bump(totals, "same_language")
                    continue
                if not (title or "").strip():
                    _bump(totals, "untitled")
                    continue
                if aid in done_ids:
                    _bump(totals, "already_done")
                    continue
                content = session.scalar(select(Article.content).where(Article.id == aid)) or ""
                try:
                    t_out, g_out = translate_title(
                        client, title=title, opening=content[:OPENING_CHARS],
                        source_lang=src, target_lang=tgt, model=model,
                    )
                except LLMUnavailable as exc:
                    paused_reason = f"the local model is unavailable: {exc}"[:200]
                    unavailable = True
                    break
                except LLMError:
                    _bump(totals, "model_error")
                    continue
                if not t_out:
                    _bump(totals, "no_usable_answer")
                    continue
                session.add(ArticleTitleTranslation(
                    article_id=aid, source_lang=src, target_lang=tgt, title=t_out,
                    summary=g_out, model=model, prompt_version=TITLE_PROMPT_VERSION,
                ))
                session.commit()
                _bump(totals, "added")
            if unavailable:
                break
            state["cursor"] = int(rows[-1][0])
            state["position"] = int(state.get("position", 0)) + len(rows)
            state["batches"] = int(state.get("batches", 0)) + 1
            state["last_batch"] = {"started_at": _iso(started), "finished_at": _iso(now()),
                                   "articles_in": len(rows)}
            batches_this_call += 1
            state["stored_total"] = int(session.scalar(
                select(func.count()).select_from(ArticleTitleTranslation).where(
                    ArticleTitleTranslation.target_lang == tgt)
            ) or 0)
        state["totals"] = totals
        save_progress_state(state, path)
    if complete:
        state["pass_completed_at"] = _iso(now())
    state["totals"] = totals
    save_progress_state(state, path)
    out: dict[str, Any] = {**state, "complete": complete}
    if paused_reason:
        out["paused_reason"] = paused_reason
    return out


def title_translations_for(session, article_ids, target_lang: str | None) -> dict[int, dict]:
    """``{article_id: {title, summary, model, prompt_version, source_lang, created_at}}``,
    the NEWEST row per article, for a page of list rows. Empty when the opt-in is off or
    the coordinator is off (Q513 = b: "shown ... when the AI coordinator is on")."""
    from sqlalchemy import select

    from src.analytics.managed import normalize_lang
    from src.database.models import ArticleTitleTranslation

    tgt = normalize_lang(target_lang)
    ids = [int(i) for i in (article_ids or [])][:1000]
    if not tgt or not ids or not titles_shown():
        return {}
    rows = session.execute(
        select(ArticleTitleTranslation)
        .where(ArticleTitleTranslation.article_id.in_(ids),
               ArticleTitleTranslation.target_lang == tgt)
        .order_by(ArticleTitleTranslation.created_at.desc(), ArticleTitleTranslation.id.desc())
    ).scalars().all()
    out: dict[int, dict] = {}
    for r in rows:
        if r.article_id in out:
            continue
        out[r.article_id] = {
            "title": r.title,
            "summary": r.summary,
            "source_lang": r.source_lang,
            "model": r.model,
            "prompt_version": r.prompt_version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "tier": "tentative",
        }
    return out


def titles_shown(settings=None) -> bool:
    """Both switches: the coordinator's master AND the title sweep's own opt-in."""
    if settings is None:
        try:
            from src.config.app_settings import load_settings

            settings = load_settings()
        except Exception:  # noqa: BLE001
            return False
    return bool(getattr(settings, "ai_background_enabled", False)) and bool(
        getattr(settings, "ai_sweep_article_titles", False)
    )


def sweep_state(name: str) -> dict:
    """A sweep's persisted state, for the activity feed (``keyword`` or ``title``)."""
    path = _state_dir() / (_KEYWORD_STATE if name == "keyword" else _TITLE_STATE)
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


__all__ = [
    "INTERFACE_LANG_KEY",
    "interface_lang",
    "measure_keyword_coverage",
    "record_interface_lang",
    "run_keyword_translation_sweep",
    "run_title_translation_sweep",
    "title_translations_for",
    "titles_shown",
]
