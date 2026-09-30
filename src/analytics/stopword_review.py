"""The stopword review: accept or reject candidate stopwords, batch by batch (R98, D11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer ruled (2026-09-30, answer 2 = a) that the stoplist GROWS, in reviewed batches,
through a review screen in Settings. This module is that screen's logic and nothing else:

* candidate batches ship as ``configs/stopword_review/<lang>.yml`` (a worklist, not engine
  input, so the index engine identity does not hash them);
* a decision (accept / reject) per candidate is stored in the ``app_state`` store, so it is
  durable, inside the encrypted corpus and carried by backups;
* the export writes the accepted words as a reviewed-batch file for a release to merge.

WHAT IT DELIBERATELY DOES NOT DO, each on purpose:

* It never changes a stoplist. A local change would make this install's extraction differ from
  every other install's, which the engine identity exists to prevent; the stoplist changes in a
  release, from an exported batch, after the collision check.
* It never sets a keyword's kind (R107: kinds come from sources, and no control sets one).
* It never accepts a word that is a translated concept (a ring member, R102: a concept is
  signal) or a platform name (R104: platform names count as keywords); it says which.
* It never lets a caller invent a candidate: only a word a shipped batch proposes can be
  decided, so the screen reviews proposals and does not author them.
* It carries no score. Each candidate shows its own counts and where else the same spelling is
  a keyword on this install, which is the collision evidence a global union would destroy.
"""

from __future__ import annotations

import logging
import threading
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_LOG = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "stopword_review"
_KEEP_FILE = CONFIG_DIR / "_keep_platform_names.yml"
_DECISIONS_KEY = "keywords.stopword_review"

DECISIONS = ("accept", "reject")
CLASSES = ("function_word", "page_word", "boilerplate", "other")

# How many other languages' use of the same spelling is shown per candidate, and how many
# articles make a use worth showing. Both only bound what is DISPLAYED; the export carries
# every collision found.
_ELSEWHERE_SHOWN = 4
_ELSEWHERE_MIN_ARTICLES = 3

_write_lock = threading.Lock()


class ReviewError(ValueError):
    """A decision that cannot be recorded; the message is shown to the operator as is."""


def _norm(term: object) -> str:
    return unicodedata.normalize("NFC", str(term or "").strip()).casefold()


def _read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def platform_names() -> frozenset[str]:
    """The platform names that COUNT as keywords (R104). Empty when the file is missing."""
    try:
        data = _read_yaml(_KEEP_FILE) or {}
    except (OSError, yaml.YAMLError):
        _LOG.warning("stopword review: cannot read %s", _KEEP_FILE, exc_info=True)
        return frozenset()
    return frozenset(_norm(n) for n in (data.get("platform_names") or []) if _norm(n))


def load_batches() -> dict[str, Any]:
    """Every shipped candidate batch, by language, plus the files that could not be read.

    A malformed batch is reported in ``errors`` and skipped; it never takes the screen down
    and never raises into the boot path (this is only read when the operator opens it).
    """
    languages: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    if not CONFIG_DIR.is_dir():
        return {"languages": languages, "errors": errors}
    for path in sorted(CONFIG_DIR.glob("*.yml")):
        if path.name.startswith("_"):
            continue
        try:
            data = _read_yaml(path) or {}
            lang = str(data.get("language") or path.stem).strip().lower()
            if not lang:
                raise ValueError("no language")
            batches = []
            for b in data.get("batches") or []:
                cands = []
                for c in b.get("candidates") or []:
                    term = _norm(c.get("term"))
                    if not term:
                        continue
                    cls = str(c.get("class") or "other")
                    cands.append(
                        {
                            "term": term,
                            "articles": int(c.get("articles") or 0),
                            "mentions": int(c.get("mentions") or 0),
                            "class": cls if cls in CLASSES else "other",
                            "note": str(c.get("note") or ""),
                        }
                    )
                batches.append(
                    {
                        "id": str(b.get("id") or ""),
                        "generated": str(b.get("generated") or ""),
                        "source": str(b.get("source") or ""),
                        "method": str(b.get("method") or ""),
                        "candidates": cands,
                    }
                )
            languages.setdefault(lang, {"batches": []})["batches"].extend(batches)
        except Exception as exc:  # noqa: BLE001 - reported to the operator, never swallowed
            errors.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
    return {"languages": languages, "errors": errors}


def _stored() -> dict[str, dict[str, dict[str, str]]]:
    from src.config.kv_store import kv_get_json

    raw = kv_get_json(_DECISIONS_KEY)
    decisions = raw.get("decisions") if isinstance(raw, dict) else None
    out: dict[str, dict[str, dict[str, str]]] = {}
    if isinstance(decisions, dict):
        for lang, per in decisions.items():
            if isinstance(per, dict):
                out[str(lang)] = {
                    str(t): dict(v) for t, v in per.items() if isinstance(v, dict) and v.get("d") in DECISIONS
                }
    return out


def _save(decisions: dict[str, dict[str, dict[str, str]]]) -> None:
    from src.config.kv_store import kv_set_json

    kv_set_json(_DECISIONS_KEY, {"v": 1, "decisions": decisions})


def _already_listed(lang: str, term: str) -> bool:
    """True when the language's own extraction already drops this word."""
    from src.analytics.extract import _stopset

    return term in _stopset(lang)


def _elsewhere(db: Any, lang: str, terms: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Where else each spelling is a keyword on this install: the collision evidence.

    One bounded query over the ``keywords`` table by ``normalized_term`` (indexed, so the column
    is compared as stored, never wrapped in ``lower()``, which would force a scan per chunk);
    a non-entity keyword is stored lowercase already, as the candidates are. A word that is
    content in another language is exactly what a global list would hide there.
    """
    if db is None or not terms:
        return {}
    from sqlalchemy import func, select

    from src.database.models import Keyword

    out: dict[str, list[dict[str, Any]]] = {}
    lowered = {t: t for t in terms}
    for i in range(0, len(terms), 400):
        chunk = terms[i : i + 400]
        rows = db.execute(
            select(
                Keyword.normalized_term,
                Keyword.language,
                func.sum(Keyword.article_count),
            )
            .where(Keyword.normalized_term.in_(chunk))
            .where(Keyword.is_entity.is_not(True))
            .where(Keyword.language.is_not(None))
            .where(Keyword.language != lang)
            .group_by(Keyword.normalized_term, Keyword.language)
        ).all()
        for term, other, articles in rows:
            n = int(articles or 0)
            if n >= _ELSEWHERE_MIN_ARTICLES and term in lowered:
                out.setdefault(term, []).append({"language": other, "articles": n})
    for uses in out.values():
        uses.sort(key=lambda u: (-u["articles"], u["language"]))
    return out


def _blocked(lang: str, term: str, keep: frozenset[str]) -> str | None:
    """Why this word may not be accepted, or None. The reason is a stable key."""
    if term in keep:
        return "platform_name"
    try:
        from src.analytics import equivalence

        if equivalence.ring_of(lang, term) is not None:
            return "ring_member"
    except Exception:  # noqa: BLE001 - a ring file problem must not block the screen
        _LOG.warning("stopword review: ring lookup failed", exc_info=True)
    return None


def languages() -> list[dict[str, Any]]:
    """The languages with a shipped batch, with how many candidates each proposes."""
    data = load_batches()
    decided = _stored()
    out = []
    for lang, v in sorted(data["languages"].items()):
        terms = {c["term"] for b in v["batches"] for c in b["candidates"]}
        out.append(
            {
                "language": lang,
                "candidates": len(terms),
                "decided": len(terms & set(decided.get(lang, {}))),
            }
        )
    return out


def review_state(db: Any, language: str) -> dict[str, Any]:
    """Everything the screen shows for one language. Read-only; no network."""
    lang = (language or "").strip().lower()
    data = load_batches()
    batches = (data["languages"].get(lang) or {}).get("batches") or []
    decided = _stored().get(lang, {})
    keep = platform_names()

    merged: dict[str, dict[str, Any]] = {}
    for b in batches:
        for c in b["candidates"]:
            cur = merged.get(c["term"])
            if cur is None or c["articles"] > cur["articles"]:
                merged[c["term"]] = {**c, "batch": b["id"]}
    terms = sorted(merged)
    listed = {t for t in terms if _already_listed(lang, t)}
    reviewable = [t for t in terms if t not in listed]
    elsewhere = _elsewhere(db, lang, reviewable)

    rows = []
    for t in sorted(reviewable, key=lambda x: (-merged[x]["articles"], x)):
        c = merged[t]
        rows.append(
            {
                **c,
                "decision": (decided.get(t) or {}).get("d"),
                "blocked": _blocked(lang, t, keep),
                "elsewhere": elsewhere.get(t, [])[:_ELSEWHERE_SHOWN],
                "elsewhere_total": len(elsewhere.get(t, [])),
            }
        )
    counts = {
        "candidates": len(terms),
        "already_listed": len(listed),
        "reviewable": len(rows),
        "accepted": sum(1 for r in rows if r["decision"] == "accept"),
        "rejected": sum(1 for r in rows if r["decision"] == "reject"),
        "undecided": sum(1 for r in rows if r["decision"] is None),
        "blocked": sum(1 for r in rows if r["blocked"]),
    }
    return {
        "language": lang,
        "batches": [
            {k: b[k] for k in ("id", "generated", "source", "method")} | {"candidates": len(b["candidates"])}
            for b in batches
        ],
        "counts": counts,
        "candidates": rows,
        "errors": data["errors"],
        "method": (
            "Words a shipped batch proposes for this language, minus those its extraction "
            "already drops. Each row shows its own counts from the batch and where else the "
            "same spelling is a keyword on this install. Nothing here changes a stoplist: "
            "accepted words leave as an exported batch that a release merges."
        ),
        "caveat": (
            "A word that looks like furniture in one language can be content in another; the "
            "'also a keyword in' column is that evidence from your own corpus, and an empty one "
            "means none was found here, not that none exists."
        ),
    }


def record_decision(language: str, term: str, decision: str | None, db: Any = None) -> dict[str, Any]:
    """Record accept / reject for one proposed word, or clear it (``decision`` None or 'clear').

    Raises :class:`ReviewError` for a word no shipped batch proposes, an unknown decision, or an
    accept of a word the screen refuses (a ring member or a platform name).
    """
    lang = (language or "").strip().lower()
    word = _norm(term)
    if decision == "clear":
        decision = None
    if decision is not None and decision not in DECISIONS:
        raise ReviewError(f"unknown decision {decision!r}; use accept, reject or clear")
    proposed = {
        c["term"] for b in (load_batches()["languages"].get(lang) or {}).get("batches", []) for c in b["candidates"]
    }
    if word not in proposed:
        raise ReviewError("no shipped batch proposes this word for this language")
    if decision == "accept":
        why = _blocked(lang, word, platform_names())
        if why == "platform_name":
            raise ReviewError("a platform name counts as a keyword (R104), so it cannot be accepted as a stopword")
        if why == "ring_member":
            raise ReviewError("a translated concept is signal (R102), so it cannot be accepted as a stopword")
    with _write_lock:
        stored = _stored()
        per = stored.setdefault(lang, {})
        if decision is None:
            per.pop(word, None)
        else:
            per[word] = {"d": decision, "at": datetime.now(UTC).isoformat(timespec="seconds")}
        if not per:
            stored.pop(lang, None)
        _save(stored)
    return {"language": lang, "term": word, "decision": decision}


def export_batch(db: Any, language: str) -> str:
    """The accepted (and rejected) words of one language as a reviewed-batch YAML document.

    Returned as text for the operator to save; it is NOT applied anywhere. Rejected words are
    carried too so a later batch does not propose them again.
    """
    state = review_state(db, language)
    lang = state["language"]
    if not state["batches"]:
        raise ReviewError(f"no shipped batch for language {language!r}")
    # A word accepted earlier that has since become a ring member or a platform name is left
    # out: R102 and R104 outrank an old decision, and the screen shows it as blocked.
    acc = [r for r in state["candidates"] if r["decision"] == "accept" and not r["blocked"]]
    rej = [r for r in state["candidates"] if r["decision"] == "reject"]
    lines = [
        f"# Reviewed stopword batch, exported from this install for language {_yaml_scalar(lang)}.",
        f"# Exported {datetime.now(UTC).isoformat(timespec='seconds')}. Not applied anywhere:",
        "# a stoplist changes only in a release, merged from this file after the collision",
        "# check (a word hidden in one language may be content in another).",
        f"language: {_yaml_scalar(lang)}",
        "reviewed_batches:",
    ]
    lines += [f"  - {_yaml_scalar(str(b['id']))}" for b in state["batches"]] or ["  []"]
    lines.append("accepted:")
    for r in acc:
        note = f"articles {r['articles']}, mentions {r['mentions']}, class {r['class']}, batch {r['batch']}"
        if r["elsewhere"]:
            note += "; also a keyword in " + ", ".join(f"{u['language']} ({u['articles']})" for u in r["elsewhere"])
        lines.append(f"  - {_yaml_scalar(r['term'])}  # {note}")
    if not acc:
        lines[-1] = "accepted: []"
    lines.append("rejected:")
    for r in rej:
        lines.append(f"  - {_yaml_scalar(r['term'])}  # batch {r['batch']}")
    if not rej:
        lines[-1] = "rejected: []"
    return "\n".join(lines) + "\n"


def _yaml_scalar(term: str) -> str:
    """A list item that survives YAML: quote anything YAML would read as a bool, number or null."""
    dumped = yaml.safe_dump(term, allow_unicode=True, default_flow_style=True, width=float("inf")).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[:-4].strip()
    return dumped.removesuffix("\n...").strip()
