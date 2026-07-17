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
from urllib.parse import urlparse

import yaml

from src.paths import data_dir

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "calendar_feeds.yml"

_MAX_FEED_BYTES = 5 * 1024 * 1024  # an .ics beyond this is refused, not truncated
_MAX_EVENTS_PER_FEED = 3000  # bounded import, like every other scan

# Robots-dead default hosts. The bundled directory shipped every country holiday with
# BOTH a Google Calendar feed and a WorldPublicHoliday feed — but calendar.google.com's
# robots.txt DISALLOWS its /calendar/ical/ paths (field-verified 2026-06-11), so the
# Google feed NEVER delivered: it was a dead "second source" the UI showed beside the
# working one, implying a corroboration that did not exist. www.webcal.guru likewise
# disallows its download endpoints; cantonbecker.com + space.floern.com are robots-
# undetermined (fail-closed refuses them; the local Meeus astronomy already covers moons/
# eclipses). These are now filtered OUT of the loaded directory entirely (load_families),
# so they no longer appear in the UI, the preflight, or the auto-import — a clean,
# honest, single-provider default set (B7 / field finding E). NOT a fabricated verdict:
# each is the host's own robots choice. The bundled YAML keeps the full dated record;
# the fail-closed robots policy still guards any feed a USER adds themselves (user
# calendars go through a separate path, not this directory).
_DEAD_DEFAULT_HOSTS: frozenset[str] = frozenset(
    {"calendar.google.com", "www.webcal.guru", "cantonbecker.com", "space.floern.com"}
)
# Back-compat alias: the auto-import round-robin still guards on this set (belt-and-
# suspenders — load_families already excludes them, so it is a no-op for defaults).
_AUTO_IMPORT_SKIP_HOSTS: frozenset[str] = _DEAD_DEFAULT_HOSTS

# Feeds retired from the defaults as REDUNDANT — not dead, not a robots verdict:
# the in-app Meeus astronomy layer (src/events/astronomy.py) already computes full/new
# moons (ch.49) and equinoxes/solstices (ch.27) with the method + accuracy STATED and
# verified against almanac values, while the Moons-Seasons ICS duplicated the same
# facts with no stated method over plain http — and its imported instances rendered
# BESIDE the computed layer as apparent contradictions (maintainer field report
# 2026-07-17: three moon states on one day). One authority, method stated, wins.
# The bundled YAML keeps the row (dated record, anti-hiding); the directory, the
# auto-import round-robin, and the imported-events view all skip it.
_REDUNDANT_DEFAULT_FEEDS: frozenset[str] = frozenset({"monkeyness-moons"})


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
        feeds = [
            f
            for f in (fam.get("feeds") or [])
            if f.get("id")
            and f.get("url")
            and urlparse(str(f["url"])).netloc not in _DEAD_DEFAULT_HOSTS
            and f["id"] not in _REDUNDANT_DEFAULT_FEEDS
        ]
        # A family left with no working feed (e.g. Google-only, or webcal-only) drops
        # out entirely — it could never have produced an event.
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


def _save_json(name: str, data: dict, *, mirror: bool = True) -> None:
    # Atomic write (temp + os.replace): these files hold the user's imported
    # events/verdicts -- a crash mid-write must never wipe them all.
    p = _store_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    # DB-reliability D1 (Wave 4 J): mirror the imported-events store into the encrypted
    # ``event_imports`` table so the events are durable, transactional and carried by a
    # backup (the JSON is cleartext + absent from backups). Best-effort MIRROR only — the
    # JSON above stays authoritative + the merge target; a DB hiccup never breaks the import.
    # Fires on EVERY normal write path (import_feed / import_ics_* / auto-import /
    # remove_user_feed) to keep the mirror in sync. ``mirror=False`` is passed ONLY by the
    # restore-side merge (``merge_imported_store``): the restore replaces the DB via an atomic
    # swap and treats ``event_imports`` as local-wins (_MERGE_IGNORED), so a live-DB write
    # there would violate the "live DB untouched until the swap" restore guarantee (torture
    # T1/T7). The mirror re-syncs on the next normal event write.
    if mirror and name == "calendar_feed_imports.json":
        try:
            from src.events.event_store import sync_imports

            sync_imports(data)
        except Exception:  # noqa: BLE001 - the mirror must never break the JSON write
            pass


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
    # mirror=False: this runs inside the restore commit, which must not touch the live DB
    # before its atomic swap (torture T1/T7). event_imports is _MERGE_IGNORED (local wins);
    # the mirror re-syncs on the next normal event write.
    _save_json(name, local, mirror=False)
    return {"action": "merged", "added": added, "enriched": enriched, "kept_local": kept}


def load_verdicts() -> dict:
    return _load_json("calendar_feed_checks.json")


def load_imports() -> dict:
    """The imported-events store, with retired-feed ghosts filtered at READ time.

    An event attributed SOLELY to a retired feed no longer surfaces, and a retired
    id is stripped from mixed-source events — so already-imported duplicates of the
    computed astronomy layer disappear immediately. This function never rewrites
    the file itself, but callers that load-modify-SAVE (import_feed) will persist
    the cleanup on their next run — intended: the retirement is deliberate."""
    data = _load_json("calendar_feed_imports.json")
    if not _REDUNDANT_DEFAULT_FEEDS:
        return data
    for bucket in data.values():
        events = bucket.get("events")
        if not isinstance(events, dict):
            continue
        for fp in list(events):
            sources = [
                s for s in (events[fp].get("sources") or []) if s not in _REDUNDANT_DEFAULT_FEEDS
            ]
            if sources:
                events[fp]["sources"] = sources
            else:
                del events[fp]
    return data


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


_USER_FEED_PREFIX = "user-"


def import_ics_text(name: str, ics_text: str) -> dict:
    """Import events from a raw .ics the user UPLOADED (no network) into a user-owned
    family, deduped within the family by fingerprint (same discipline as import_feed).

    The events then join the agenda like any imported feed — the cross-feed collapse
    + reversible per-machine exclude apply automatically. The .ics text is parsed and
    DISCARDED; only event title + date (+ uid) are stored (no raw file retention).
    """
    if len(ics_text.encode("utf-8", "ignore")) > _MAX_FEED_BYTES:
        raise ValueError(f"file exceeds the {_MAX_FEED_BYTES // (1024 * 1024)} MB cap")
    events = parse_ics(ics_text)            # bounded by _MAX_EVENTS_PER_FEED
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:48]
    key = _USER_FEED_PREFIX + (slug or "calendar")
    label = (name or "").strip() or "My calendar"
    imports = load_imports()
    bucket = imports.setdefault(key, {"name": label, "events": {}})
    bucket["name"] = label
    bucket["user"] = True                   # user-owned (vs the bundled directory)
    added = merged = 0
    for ev in events:
        fp = _fingerprint(ev["title"], ev["date"])
        entry = bucket["events"].get(fp)
        if entry is None:
            bucket["events"][fp] = {
                "title": ev["title"], "date": ev["date"],
                "sources": [key], "uids": [ev["uid"]] if ev.get("uid") else [],
            }
            added += 1
        else:
            if key not in entry["sources"]:
                entry["sources"].append(key)
            merged += 1
    bucket["imported_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _save_json("calendar_feed_imports.json", imports)
    return {
        "family": key, "name": label, "events_in_file": len(events),
        "added": added, "merged_into_existing": merged, "family_total": len(bucket["events"]),
    }


def import_ics_url(fetcher, url: str, name: str = "") -> dict:
    """Add a calendar by URL (webcal/https). Fetches through the GUARDED fetcher —
    robots fail-closed, kill switch, per-host politeness, proxy — then imports like an
    uploaded .ics (dedup, user-owned, removable). The network action is consented at
    the UI (the ONE airplane-mode popup) before this is called; the kill switch is the
    backstop (an offline fetch refuses here). webcal:// is normalised to https://."""
    u = (url or "").strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[len("webcal://"):]
    if not u.lower().startswith(("http://", "https://")):
        raise ValueError("URL must be http(s) or webcal")
    text = _fetch_text(fetcher, u)          # robots / kill-switch / size cap inherited
    return import_ics_text(name or u, text)


def list_user_feeds() -> list[dict]:
    """The user's own uploaded calendars (removable), name-sorted."""
    out = [
        {"key": key, "name": bucket.get("name", key), "events": len(bucket.get("events", {}))}
        for key, bucket in load_imports().items()
        if bucket.get("user") or key.startswith(_USER_FEED_PREFIX)
    ]
    out.sort(key=lambda f: f["name"].lower())
    return out


def remove_user_feed(key: str) -> dict:
    """Remove a USER-uploaded calendar family (reversible: re-import the .ics). Only
    user-owned families can be removed — the bundled directory is never deleted."""
    imports = load_imports()
    bucket = imports.get(key)
    if not bucket or not (bucket.get("user") or key.startswith(_USER_FEED_PREFIX)):
        raise KeyError(f"not a user calendar: {key}")
    n = len(bucket.get("events", {}))
    del imports[key]
    _save_json("calendar_feed_imports.json", imports)
    return {"removed": key, "events": n}


def auto_import_due_feeds(fetcher, *, batch: int = 8, min_interval_hours: float = 12.0) -> dict:
    """Import a BOUNDED batch of bundled calendar feeds (continuous auto-import,
    ruled 2026-06-15 "auto-import everything").

    Round-robin by least-recently-imported so over successive collect passes EVERY
    feed is eventually covered WITHOUT hammering: at most ``batch`` feeds per call,
    and a feed imported (or attempted) within ``min_interval_hours`` is skipped
    (per-feed backoff — a robots-blocked/dead feed is not retried every pass). Each
    import is best-effort (one feed's failure never aborts the batch) and idempotent
    (``import_feed`` dedups). The kill switch / robots / per-host politeness / proxy
    are all inherited from ``fetcher`` (the guarded path) — this adds no new fetch
    surface, just schedules the existing operator import. Per-feed timestamps live in
    a per-machine store. Returns a tally; never raises for a single bad feed.
    """
    state = _load_json("calendar_autoimport.json")
    now = datetime.now(UTC)
    due: list[tuple[str, str]] = []
    for fam in load_families():
        for feed in fam["feeds"]:
            # Skip feeds on a field-verified robots-disallowed host: the fetcher would
            # refuse them anyway, and including them starves the working feeds in the
            # round-robin. They stay LISTED (load_families is untouched) — only the
            # automatic import skips them.
            if urlparse(feed.get("url", "")).netloc in _AUTO_IMPORT_SKIP_HOSTS:
                continue
            last = state.get(feed["id"])
            if last:
                try:
                    age_h = (now - datetime.fromisoformat(last)).total_seconds() / 3600
                    if age_h < min_interval_hours:
                        continue
                except (ValueError, TypeError):
                    pass
            due.append((last or "", feed["id"]))   # "" (never imported) sorts first
    due.sort()
    picked = [fid for _, fid in due[: max(0, batch)]]
    imported = failed = 0
    for fid in picked:
        try:
            import_feed(fetcher, fid)
            imported += 1
        except Exception:  # noqa: BLE001 - one bad feed must not abort the batch
            failed += 1
        # Record the ATTEMPT either way, so a failing feed backs off too.
        state[fid] = now.isoformat(timespec="seconds")
    if picked:
        _save_json("calendar_autoimport.json", state)
    return {"due": len(due), "picked": len(picked), "imported": imported, "failed": failed}


def collapse_imported(rows: list[dict]) -> list[dict]:
    """Collapse the SAME imported event seen across DIFFERENT feed families into ONE
    row (ruled 2026-06-15: "we don't want 100 entries mentioning Christmas Day").

    Within-family dedup already happened at import (``import_feed``); this is the
    CROSS-family layer. With auto-import-everything a holiday like Christmas Day is
    carried by dozens of country/religion/aggregator feeds — without this the agenda
    would show one row per feed. Identity = the same normalized title on the same
    EXACT date (``_fingerprint``); a different date stays a separate row (a
    moved/contested date is information, never hidden). Every provider source and
    every folder is preserved and counted, so the collapse is transparent and the
    user can still see who published it. Input order preserved (first wins canonical).
    """
    order: list[str] = []
    groups: dict[str, dict] = {}
    for e in rows:
        fp = _fingerprint(e.get("title", ""), e.get("date", ""))
        g = groups.get(fp)
        if g is None:
            order.append(fp)
            g = groups[fp] = {
                "title": e.get("title", ""), "date": e.get("date", ""),
                "sources": [], "families": [], "family_names": [], "uids": [],
                # Carry the facets through the merge (the canonical kind is the first
                # family's; countries accumulate — one holiday spans many countries).
                "kind": str(e.get("kind") or "other"), "countries": [],
            }
        for s in e.get("sources", []):
            if s not in g["sources"]:
                g["sources"].append(s)
        fam = e.get("family")
        if fam and fam not in g["families"]:
            g["families"].append(fam)
            g["family_names"].append(e.get("family_name", fam))
        c = e.get("country")
        if c and c not in g["countries"]:
            g["countries"].append(c)
        for u in e.get("uids", []) or []:
            if u and u not in g["uids"]:
                g["uids"].append(u)
    out: list[dict] = []
    for fp in order:
        g = groups[fp]
        g["source_count"] = len(g["sources"])
        g["family_count"] = len(g["families"])
        g["family"] = g["families"][0] if g["families"] else None
        g["family_name"] = g["family_names"][0] if g["family_names"] else ""
        g["country"] = g["countries"][0] if g["countries"] else None
        out.append(g)
    return out


def imported_agenda(*, family: str | None = None, frm: str | None = None,
                    collapse: bool = True) -> list[dict]:
    """Imported events (optionally one family / from a start date), soonest first.

    With ``collapse`` (default) and no single ``family`` filter, the same event
    across different feed families is merged into one row (see ``collapse_imported``)
    so the agenda never shows the same holiday once per feed. A single-family view
    is already deduped at import, so it is returned uncollapsed.
    """
    # Each event inherits its feed FAMILY's real facets — kind (holidays / religion
    # / civic / space / science / community) + country — so the agenda can filter to
    # a thin, meaningful view instead of a useless "imported" bucket (maintainer
    # 2026-06-18: "everything is imported; enrich the tag list"). A user-added feed
    # with no directory entry falls back to kind "other".
    fam_meta = {f["key"]: f for f in load_families()}
    out = []
    for key, bucket in load_imports().items():
        if family and key != family:
            continue
        meta = fam_meta.get(key) or {}
        for entry in bucket.get("events", {}).values():
            if frm and entry["date"] < frm:
                continue
            out.append({
                **entry,
                "family": key,
                "family_name": bucket.get("name", key),
                "kind": str(meta.get("kind") or "other"),
                "country": meta.get("country"),
            })
    out.sort(key=lambda e: (e["date"], e["title"]))
    if collapse and family is None:
        out = collapse_imported(out)
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
