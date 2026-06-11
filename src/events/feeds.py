"""
Calendar feed directory: bundled candidates, on-demand verification + import.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer supplied an aggregated directory of ~500 public iCalendar feeds
(2026-06-10) for the Agenda "flood". Honesty rules, in code:

- The bundled catalog (configs/calendar_feeds.yml) is a DIRECTORY of
  candidates. Nothing is fetched at boot; the operator verifies and imports
  explicitly, through the ethical fetcher (robots fail-closed, rate-limited,
  kill-switch aware).
- A *family* groups duplicate feeds describing the same thing from different
  providers — the duplication is SHOWN, never hidden; every source and its
  metadata stays reachable.
- Imported events de-duplicate within a family by (normalized title, date) —
  the PR #53 fingerprint idea — but each kept event lists EVERY source feed
  that carried it, so a date disagreement between providers is visible as two
  entries rather than a silent pick.
- Verdicts and imports are per-machine data (under OO_DATA_DIR), dated.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from contextlib import suppress
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from src.paths import data_dir

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "calendar_feeds.yml"

_MAX_FEED_BYTES = 5 * 1024 * 1024  # an .ics beyond this is refused, not truncated
_MAX_EVENTS_PER_FEED = 3000  # bounded import, like every other scan


# --------------------------------------------------------------------------- #
#  Catalog
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _raw() -> dict:
    if not CATALOG_PATH.exists():
        return {}
    return yaml.safe_load(CATALOG_PATH.read_text("utf-8")) or {}


@lru_cache(maxsize=1)
def load_families() -> list[dict]:
    out = []
    for fam in _raw().get("families", []):
        feeds = [f for f in fam.get("feeds", []) if f.get("id") and f.get("url")]
        if not (fam.get("key") and feeds):
            continue
        out.append(
            {
                "key": str(fam["key"]),
                "name": str(fam.get("name", fam["key"])),
                "kind": str(fam.get("kind", "other")),
                "country": fam.get("country"),
                "feeds": feeds,
            }
        )
    return out


def feed_by_id(feed_id: str) -> tuple[dict, dict] | None:
    """(family, feed) for a feed id, or None."""
    for fam in load_families():
        for f in fam["feeds"]:
            if f["id"] == feed_id:
                return fam, f
    return None


def directory_only() -> list[dict]:
    return [d for d in _raw().get("directory_only", []) if d.get("url")]


# --------------------------------------------------------------------------- #
#  Per-machine stores (verdicts + imported events) — dated, honest, replayable
# --------------------------------------------------------------------------- #
def _store_path(name: str) -> Path:
    return data_dir() / name


def _load_json(name: str) -> dict:
    p = _store_path(name)
    try:
        return json.loads(p.read_text("utf-8")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(name: str, data: dict) -> None:
    # Atomic write (temp + os.replace): these files hold the user's imported
    # events/verdicts -- a crash mid-write must never wipe them all.
    p = _store_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def merge_imported_store(name: str, incoming: dict) -> dict:
    """Union-merge an events/verdicts store arriving via backup restore.

    Local entries always win; incoming events are added by fingerprint with
    their sources/uids unioned (the same dedup discipline as import_feed).
    Idempotent: re-running with the same input converges. Atomic save."""
    local = _load_json(name)
    added = enriched = kept = 0
    if name == "calendar_feed_imports.json":
        for fam_key, bucket in (incoming or {}).items():
            if not isinstance(bucket, dict):
                continue
            lb = local.setdefault(fam_key, {"name": bucket.get("name", fam_key), "events": {}})
            lb.setdefault("events", {})
            for fp, entry in (bucket.get("events") or {}).items():
                le = lb["events"].get(fp)
                if le is None:
                    lb["events"][fp] = entry
                    added += 1
                    continue
                kept += 1
                for src_id in entry.get("sources", []):
                    if src_id not in le.setdefault("sources", []):
                        le["sources"].append(src_id)
                        enriched += 1
                for uid in entry.get("uids", []):
                    if uid not in le.setdefault("uids", []):
                        le["uids"].append(uid)
    else:
        for feed_id, verdict in (incoming or {}).items():
            if feed_id in local:
                kept += 1
            else:
                local[feed_id] = verdict
                added += 1
    _save_json(name, local)
    return {"action": "merged", "added": added, "enriched": enriched, "kept_local": kept}


def load_verdicts() -> dict:
    return _load_json("calendar_feed_checks.json")


def load_imports() -> dict:
    return _load_json("calendar_feed_imports.json")


# --------------------------------------------------------------------------- #
#  Minimal, tolerant ICS parsing (stdlib only; defensive like the hazard parsers)
# --------------------------------------------------------------------------- #
def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the prior."""
    out: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _ics_unescape(s: str) -> str:
    return (
        s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
        .replace("\\;", ";").replace("\\\\", "\\").strip()
    )


def parse_ics(text: str) -> list[dict]:
    """VEVENTs as ``{uid, title, date}`` — date-only precision, malformed skipped.

    Tolerant by design: a bad event is dropped, never guessed; a non-calendar
    payload yields []. Bounded by _MAX_EVENTS_PER_FEED.
    """
    if "BEGIN:VCALENDAR" not in text[:2000]:
        return []
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold(text):
        u = line.upper()
        if u.startswith("BEGIN:VEVENT"):
            cur = {}
        elif u.startswith("END:VEVENT"):
            if cur and cur.get("title") and cur.get("date"):
                events.append(cur)
                if len(events) >= _MAX_EVENTS_PER_FEED:
                    break
            cur = None
        elif cur is not None and ":" in line:
            key, _, value = line.partition(":")
            prop = key.split(";")[0].upper()
            if prop == "SUMMARY":
                cur["title"] = _ics_unescape(value)[:300]
            elif prop == "UID":
                cur["uid"] = value.strip()[:200]
            elif prop == "DTSTART":
                m = re.match(r"^(\d{4})(\d{2})(\d{2})", value.strip())
                if m:
                    # An impossible date is skipped, never coerced.
                    with suppress(ValueError):
                        cur["date"] = date(
                            int(m.group(1)), int(m.group(2)), int(m.group(3))
                        ).isoformat()
    return events


def _fingerprint(title: str, date_iso: str) -> str:
    """The PR #53 family fingerprint: normalized title + exact date."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return f"{t}|{date_iso}"


# --------------------------------------------------------------------------- #
#  Verify + import (explicit operator actions; ethical fetch path only)
# --------------------------------------------------------------------------- #
def _fetch_text(fetcher, url: str) -> str:
    result = fetcher.fetch(url, require_html=False)
    body = result.content or ""
    if len(body.encode("utf-8", "ignore")) > _MAX_FEED_BYTES:
        raise ValueError(f"feed exceeds the {_MAX_FEED_BYTES // (1024 * 1024)} MB cap")
    return body


def verify_feed(fetcher, feed_id: str) -> dict:
    """Fetch one feed and record an honest verdict (reachable? real iCal? stale year?)."""
    hit = feed_by_id(feed_id)
    if hit is None:
        raise KeyError(f"unknown feed id: {feed_id}")
    _fam, feed = hit
    verdict: dict = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        text = _fetch_text(fetcher, feed["url"])
        events = parse_ics(text)
        verdict["status"] = "ok" if events else ("not_ical" if text else "empty")
        verdict["events"] = len(events)
    except Exception as exc:  # noqa: BLE001 - the verdict IS the error report
        verdict["status"] = "unreachable"
        verdict["error"] = str(exc)[:300]
    pinned = feed.get("year_pinned")
    if pinned and int(pinned) < date.today().year:
        verdict["stale_year"] = int(pinned)
    verdicts = load_verdicts()
    verdicts[feed_id] = verdict
    _save_json("calendar_feed_checks.json", verdicts)
    return verdict


def import_feed(fetcher, feed_id: str) -> dict:
    """Import one feed's events under its family, de-duplicating WITHIN the family.

    A fingerprint collision adds the feed to the existing entry's ``sources``
    (the duplicate is shown as one event carried by N providers); a different
    date for the "same" holiday stays a separate entry — disagreement is a
    signal, never silently resolved.
    """
    hit = feed_by_id(feed_id)
    if hit is None:
        raise KeyError(f"unknown feed id: {feed_id}")
    fam, feed = hit
    text = _fetch_text(fetcher, feed["url"])
    events = parse_ics(text)
    imports = load_imports()
    bucket = imports.setdefault(fam["key"], {"name": fam["name"], "events": {}})
    bucket["name"] = fam["name"]
    added = merged = 0
    for ev in events:
        fp = _fingerprint(ev["title"], ev["date"])
        entry = bucket["events"].get(fp)
        if entry is None:
            bucket["events"][fp] = {
                "title": ev["title"],
                "date": ev["date"],
                "sources": [feed_id],
                "uids": [ev.get("uid")] if ev.get("uid") else [],
            }
            added += 1
        else:
            if feed_id not in entry["sources"]:
                entry["sources"].append(feed_id)
                merged += 1
            if ev.get("uid") and ev["uid"] not in entry.get("uids", []):
                entry.setdefault("uids", []).append(ev["uid"])
    bucket["imported_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _save_json("calendar_feed_imports.json", imports)
    return {
        "family": fam["key"],
        "feed": feed_id,
        "events_in_feed": len(events),
        "added": added,
        "merged_into_existing": merged,
        "family_total": len(bucket["events"]),
    }


def imported_agenda(*, family: str | None = None, frm: str | None = None) -> list[dict]:
    """Imported events (optionally one family / from a start date), soonest first."""
    out = []
    for key, bucket in load_imports().items():
        if family and key != family:
            continue
        for entry in bucket.get("events", {}).values():
            if frm and entry["date"] < frm:
                continue
            out.append({**entry, "family": key, "family_name": bucket.get("name", key)})
    out.sort(key=lambda e: (e["date"], e["title"]))
    return out


def directory_status() -> dict:
    """The directory with per-feed verdicts + per-family import counts (for the UI)."""
    verdicts = load_verdicts()
    imports = load_imports()
    families = []
    for fam in load_families():
        feeds = [
            {**f, "verdict": verdicts.get(f["id"])}
            for f in fam["feeds"]
        ]
        imported = imports.get(fam["key"], {}).get("events", {})
        families.append(
            {
                **fam,
                "feeds": feeds,
                "duplicates": len(feeds) > 1,
                "imported_events": len(imported),
            }
        )
    return {
        "catalog_as_of": _raw().get("catalog_as_of"),
        "families": families,
        "directory_only": directory_only(),
        "checked": len(verdicts),
        "total_feeds": sum(len(f["feeds"]) for f in families),
    }
