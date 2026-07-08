"""Weather signal-keywords — derived, (date,place)-anchored, NEVER text keywords.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Open-Meteo weather layer's remainder (ledger): derive ``kind="signal"`` keyword rows
from EXPLICIT THRESHOLD RULES over the corroboration data (:mod:`src.analytics.corroboration`),
each carrying a ``(date, place)`` anchor BY CONSTRUCTION, with an anomaly-vs-stated-baseline
note. These are a DIFFERENT class of thing from text keywords (which are extracted from
prose and have no intrinsic date/place), so they must NEVER be silently mixed with them.

DESIGN NOTE — why a SEPARATE store, not the keyword table. A ``kind="signal"`` row is,
by the ledger ruling, "never silently mixed with text keywords". The keyword tables
(``keywords`` / ``keyword_mentions``) carry no field that would cleanly and permanently
separate a signal row from a text keyword in every aggregation, and adding one is a schema
change (Session D's territory — DEFERRED here). So this module writes the derived signal
rows to its OWN local JSON store — separation is then structural (they physically cannot
appear in a keyword listing), needs no schema, and is honest. When a persisted anomaly
BASELINE (a climatology per place) is wanted, that needs a new column and is DEFERRED to
the migrations owner.

Honesty by construction:
  * the THRESHOLD RULE is explicit — a cluster of ``>= min_articles`` articles matching a
    curated climate-event term AND a deduced place AND a window (the corroboration
    opportunity); the derivation itself makes NO network call;
  * the ANCHOR is ``(window, place)`` by construction — a signal row never floats free of
    its date and place;
  * the ANOMALY is NOT fabricated — a true anomaly check compares Open-Meteo ERA5 daily
    reanalysis for the place/window against a climatological BASELINE, which requires the
    consented network fetch; until then the anomaly is reported as UNCHECKED against the
    stated baseline, never as a value.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

SIGNALS_VERSION = "oo-weather-signals-1"
SIGNAL_KIND = "signal"

WEATHER_SIGNAL_CAVEAT = (
    "A weather SIGNAL keyword is DEDUCED from a cluster of articles mentioning a "
    "climate-event term together with a place and a time window — it is NOT a confirmed "
    "event, and it is NOT a text keyword (it carries its own date + place anchor and is "
    "kept out of the keyword index). The anomaly is UNCHECKED: confirming it against a "
    "climatological baseline needs the consented Open-Meteo reanalysis fetch, which is a "
    "model estimate, not a station record. Word-place co-occurrence is never proof."
)


def _store_path():
    from src.paths import data_dir

    return data_dir() / "weather_signals.json"


def _anomaly_note(variables: list[str]) -> dict:
    var_list = ", ".join(variables) if variables else "the relevant daily variables"
    return {
        "checked": False,
        "baseline": f"climatology of {var_list} (Open-Meteo ERA5 daily) for this place & window",
        "note": (
            "Not yet checked against a baseline: confirming an anomaly requires the "
            "consented Open-Meteo reanalysis fetch for this place and window; reanalysis is "
            "a model estimate, not a station record."
        ),
    }


def derive_weather_signals(
    session,
    *,
    min_articles: int = 3,
    lookback_days: int = 90,
    limit: int = 50,
    now: datetime | None = None,
) -> list[dict]:
    """Derive kind='signal' keyword records from the corroboration opportunities.

    Runs the LOCAL corroboration scan (no network) and maps each opportunity that clears
    the explicit article-cluster threshold to one signal record anchored to (window, place).
    Returns the records (does NOT persist — see :func:`refresh_weather_signals`).
    """
    from src.analytics.corroboration import find_weather_opportunities

    found = find_weather_opportunities(
        session, min_articles=min_articles, lookback_days=lookback_days, limit=limit
    )
    ts = (now or datetime.now(UTC)).isoformat()
    records: list[dict] = []
    for op in found.get("opportunities", []):
        rule = op["rule"]
        place = op["place"]
        country = op.get("place_country")
        records.append(
            {
                "kind": SIGNAL_KIND,  # never a text keyword — kept out of the keyword index
                "term": f"signal:{rule}",
                "signal": rule,
                "label": op.get("rule_label") or rule,
                "place": place,
                "place_country": country,
                "lat": op.get("lat"),
                "lon": op.get("lon"),
                "geocode": op.get("geocode"),
                # The (date, place) ANCHOR — present by construction on every signal row.
                "anchor": {
                    "date_start": op["window_start"],
                    "date_end": op["window_end"],
                    "place": place,
                    "place_country": country,
                },
                "window_start": op["window_start"],
                "window_end": op["window_end"],
                "variables": list(op.get("variables") or []),
                "terms_matched": list(op.get("terms_matched") or []),
                "n_articles": op["n_articles"],
                "article_ids": list(op.get("article_ids") or []),
                "threshold_rule": (
                    f">= {min_articles} articles matching the '{rule}' climate-event terms "
                    f"together with the place '{place}' inside one window"
                ),
                "anomaly": _anomaly_note(list(op.get("variables") or [])),
                "derived_at": ts,
                # A stable identity so a re-derive UPDATES rather than duplicates.
                "key": f"{rule}|{country or ''}|{place}|{op['window_start']}",
            }
        )
    return records


def save_signals(records: list[dict], *, now: datetime | None = None) -> dict:
    """Persist the derived signal records to the local store (atomic; never a schema write)."""
    payload = {
        "version": SIGNALS_VERSION,
        "derived_at": (now or datetime.now(UTC)).isoformat(),
        "kind": SIGNAL_KIND,
        "signals": records,
        "caveat": WEATHER_SIGNAL_CAVEAT,
    }
    path = _store_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    _LOG.info("weather signals saved: %d records", len(records))
    return payload


def load_signals() -> dict:
    """Read the local signal store — network-free; honest empty result when absent."""
    empty: dict = {"version": SIGNALS_VERSION, "derived_at": None, "kind": SIGNAL_KIND,
                   "signals": [], "caveat": WEATHER_SIGNAL_CAVEAT}
    path = _store_path()
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not break the read
        _LOG.warning("weather_signals.json unreadable; treating as empty", exc_info=True)
        return empty
    if not isinstance(data, dict) or data.get("version") != SIGNALS_VERSION:
        return empty
    if not isinstance(data.get("signals"), list):
        data["signals"] = []
    data.setdefault("caveat", WEATHER_SIGNAL_CAVEAT)
    return data


def refresh_weather_signals(
    session, *, min_articles: int = 3, lookback_days: int = 90, now: datetime | None = None
) -> dict:
    """Derive AND persist the weather signal-keywords. Returns the saved payload."""
    records = derive_weather_signals(
        session, min_articles=min_articles, lookback_days=lookback_days, now=now
    )
    return save_signals(records, now=now)


def auto_refresh_weather_due(
    session,
    *,
    refresh_interval_hours: float = 24.0,
    min_articles: int = 3,
    lookback_days: int = 90,
    now: datetime | None = None,
) -> dict:
    """Freshness-gated derive+persist of the weather SIGNAL keywords for the background pass.

    Network-free (the derivation scans the corpus only). Refreshes at most every
    ``refresh_interval_hours`` — a store younger than that is a no-op (``{"skipped":
    "fresh"}``), so the corpus scan isn't repeated on every collect pass. Best-effort;
    counts only. This is the scheduler-side wrapper around :func:`refresh_weather_signals`;
    it fetches nothing, so it needs no airplane gate.
    """
    cur = load_signals()
    derived_at = cur.get("derived_at")
    ref = now or datetime.now(UTC)
    if derived_at:
        try:
            dt = datetime.fromisoformat(derived_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            age_h = max(0.0, (ref - dt).total_seconds() / 3600.0)
            if age_h < float(refresh_interval_hours):
                return {"skipped": "fresh", "age_hours": round(age_h, 2)}
        except (ValueError, TypeError):
            pass  # unparseable timestamp -> treat as due and refresh
    payload = refresh_weather_signals(
        session, min_articles=min_articles, lookback_days=lookback_days, now=now
    )
    return {"refreshed": len(payload.get("signals", [])), "derived_at": payload.get("derived_at")}
