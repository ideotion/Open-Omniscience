"""
GUI-editable keyword filter: automatic stopword exclusion + user fine-tuning.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two layers keep "dumb" keywords out of the analytics:

  * **Automatic** — a built-in multilingual stoplist (src.analytics.extract.
    global_stopwords) drops function words ("the", "you", "not", "one", …) at
    extraction time AND is also applied at query time, so even keywords already in
    the store are hidden without re-indexing.
  * **Manual** — this small, persisted, GUI-editable list lets the operator
    exclude (or re-include) specific terms and tune the minimum length. Stored as a
    tiny JSON file under the data dir (same pattern as the other settings stores).

Exclusions hide terms from listings (top / trending / associations / map); they
never delete stored mentions, so re-including a term brings it straight back.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import asdict, dataclass, field

_LOG = logging.getLogger(__name__)
SETTINGS_VERSION = "oo-keyword-filter-1"
_MIN_LEN_LO, _MIN_LEN_HI = 1, 20


def _normalize(term: str) -> str:
    return " ".join(str(term).split()).casefold()


@dataclass
class KeywordFilter:
    """Operator-controlled keyword filtering."""

    excluded: list[str] = field(default_factory=list)   # normalized terms to hide
    min_length: int = 3
    drop_numeric: bool = True
    use_builtin_stopwords: bool = True                   # apply the automatic multilingual stoplist

    def to_dict(self) -> dict:
        return asdict(self)


def _path():
    from src.paths import data_dir

    return data_dir() / "keyword_filter.json"


def load_settings() -> KeywordFilter:
    p = _path()
    if not p.exists():
        return KeywordFilter()
    try:
        raw = json.loads(p.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not break analytics
        _LOG.warning("keyword_filter.json unreadable; using defaults", exc_info=True)
        return KeywordFilter()
    d = KeywordFilter()
    excluded = raw.get("excluded", [])
    if not isinstance(excluded, list):
        excluded = []
    ml = raw.get("min_length", d.min_length)
    try:
        ml = max(_MIN_LEN_LO, min(_MIN_LEN_HI, int(ml)))
    except (TypeError, ValueError):
        ml = d.min_length
    return KeywordFilter(
        excluded=sorted({_normalize(t) for t in excluded if _normalize(t)}),
        min_length=ml,
        drop_numeric=bool(raw.get("drop_numeric", d.drop_numeric)),
        use_builtin_stopwords=bool(raw.get("use_builtin_stopwords", d.use_builtin_stopwords)),
    )


def save_settings(updates: dict) -> KeywordFilter:
    cur = load_settings()
    if "excluded" in updates and updates["excluded"] is not None:
        vals = updates["excluded"]
        if isinstance(vals, str):
            vals = vals.replace("\n", ",").split(",")
        cur.excluded = sorted({_normalize(t) for t in vals if _normalize(t)})
    if "min_length" in updates and updates["min_length"] is not None:
        with contextlib.suppress(TypeError, ValueError):
            cur.min_length = max(_MIN_LEN_LO, min(_MIN_LEN_HI, int(updates["min_length"])))
    if "drop_numeric" in updates and updates["drop_numeric"] is not None:
        cur.drop_numeric = bool(updates["drop_numeric"])
    if "use_builtin_stopwords" in updates and updates["use_builtin_stopwords"] is not None:
        cur.use_builtin_stopwords = bool(updates["use_builtin_stopwords"])
    _write(cur)
    return cur


def add_excluded(term: str) -> KeywordFilter:
    cur = load_settings()
    n = _normalize(term)
    if n and n not in cur.excluded:
        cur.excluded = sorted(set(cur.excluded) | {n})
        _write(cur)
    return cur


def remove_excluded(term: str) -> KeywordFilter:
    cur = load_settings()
    n = _normalize(term)
    if n in cur.excluded:
        cur.excluded = [t for t in cur.excluded if t != n]
        _write(cur)
    return cur


def excluded_set() -> set[str]:
    return set(load_settings().excluded)


def hidden_set() -> set[str]:
    """User exclusions plus the built-in stoplist (when enabled) — the full hide set."""
    s = load_settings()
    hidden = set(s.excluded)
    if s.use_builtin_stopwords:
        from src.analytics.extract import global_stopwords

        hidden |= global_stopwords()
    return hidden


def _write(cur: KeywordFilter) -> None:
    p = _path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": SETTINGS_VERSION, **cur.to_dict()}, indent=2, sort_keys=True), "utf-8")
    tmp.replace(p)
