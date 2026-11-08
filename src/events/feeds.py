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

import errno
import json
import logging
import os
import re
import stat
import unicodedata
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml

from src.catalog.countries import config_country
from src.monitoring.secret_scrub import log_failure, record_text
from src.paths import data_dir

_LOG = logging.getLogger(__name__)

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
                "country": config_country(fam.get("country"), upper=True),
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


#: A lone surrogate escape (a JSON text of ``"\\ud800"``): ``json`` accepts it, but no file can hold it as UTF-8.
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_IMPORTS = "calendar_feed_imports.json"


#: The JSON ESCAPE of a UTF-16 surrogate half, in the raw text of a file. A parsed text can only hold a surrogate if its source wrote one this way
#: (the file is read as UTF-8, which refuses an encoded one), so a text without this pattern needs no walk at all.
_SURROGATE_ESCAPE = re.compile(r"\\u[dD][89a-fA-F]")


def _may_hold_lone_surrogate(data: object, raw: str | None) -> bool:
    """Could ``data`` hold a lone surrogate? Decided without recursing in Python, so a deeply nested store costs no more than before.

    From the file's raw text when there is one (a regular expression: a false positive only costs the walk). Without one (a restore
    artifact's store arrives parsed) from encoding the document, which is C code and raises exactly when a surrogate is in it. A document
    too deep for that is left as it was: it behaved the same before, and a walk would only raise ``RecursionError`` where none was.
    """
    if raw is not None:
        return _SURROGATE_ESCAPE.search(raw) is not None
    try:
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return True
    except (RecursionError, ValueError, TypeError):
        return False
    return False


def _scrub_surrogates(value: object, found: list[int]) -> object:
    """``value`` with every lone surrogate in any text (a key or a value) replaced by U+FFFD.

    ``found`` is ``[texts changed, entries lost to a key that became another key]``. ``json.loads`` joins a valid escaped pair into one
    character, so any surrogate left in a parsed text IS a lone one: it parses, and the next save then raises ``UnicodeEncodeError`` on
    it, for every save from then on (and the restore merge ends at that save).
    """
    if isinstance(value, str):
        if _LONE_SURROGATE.search(value):
            found[0] += 1
            return _LONE_SURROGATE.sub("\ufffd", value)
        return value
    if isinstance(value, dict):
        out = {_scrub_surrogates(k, found): _scrub_surrogates(v, found) for k, v in value.items()}
        found[1] += len(value) - len(out)
        return out
    if isinstance(value, list):
        return [_scrub_surrogates(v, found) for v in value]
    return value


def _imports_shape(data: dict) -> tuple[dict, int]:
    """The imported-events store with only what its readers can walk: ``{family: {"name", "events": {fingerprint: {...}}}}``.

    Valid JSON of another shape (a family that is not an object, ``events`` as a list, an event that is a number, ``sources`` as a
    string or holding a non-text item) parses, then raises in the first reader or merge that calls ``.items()``, ``.get()`` or ``in`` on
    it. Each such piece is left out and COUNTED; nothing of its content is kept or reported. A family always comes back with an
    ``events`` dict (``{}`` when it had none or a null), and a healthy store keeps its keys in their order.
    """
    left_out = 0
    clean: dict = {}
    for fam_key, bucket in data.items():
        if not isinstance(bucket, dict):
            left_out += 1
            continue
        fam = dict(bucket)
        # Every reader and the merge index ``fam["events"]`` directly, so it is always a dict: a missing or null one is an empty one
        # (nothing of the file's content is lost by that), a non-object one is left out and counted.
        events = fam.get("events")
        if events is not None and not isinstance(events, dict):
            left_out += 1
            events = None
        kept: dict = {}
        for fp, entry in (events or {}).items():
            if not isinstance(entry, dict):
                left_out += 1
                continue
            entry = dict(entry)
            for field in ("sources", "uids"):
                if field not in entry:
                    continue
                if entry[field] is None:
                    entry[field] = []  # a null list is an empty one (not counted: it is not wrong data), or ``setdefault`` hands the merge the None
                    continue
                if not isinstance(entry[field], list):
                    left_out += 1
                    entry[field] = []  # an empty list, not a missing key: ``entry["sources"]`` is indexed in the importers
                    continue
                texts = [x for x in entry[field] if isinstance(x, str)]
                left_out += len(entry[field]) - len(texts)
                entry[field] = texts
            kept[fp] = entry
        fam["events"] = kept  # assigns in place when the key exists, so the family's key order is kept
        clean[fam_key] = fam
    return clean, left_out


def _sanitized(name: str, data: object, *, what: str, raw: str | None = None) -> dict:
    """``data`` as a store of ``name`` that every reader can walk, with a class-only line for what had to change.

    ``what`` says where it came from in the line ("reads as" for a store on disk, "arrives as" for a restore artifact's); ``raw`` is the
    file's text when there is one.
    """
    if not isinstance(data, dict):
        _LOG.warning("%s holds JSON that is not an object (%s), so it %s empty", name, type(data).__name__, what)
        return {}
    out: dict = data
    if _may_hold_lone_surrogate(data, raw):
        found = [0, 0]
        try:
            scrubbed = _scrub_surrogates(data, found)
        except RecursionError:
            _LOG.warning("%s is nested too deeply to check for lone surrogate escapes, so it %s empty", name, what)
            return {}
        assert isinstance(scrubbed, dict)
        out = scrubbed
        if found[0]:
            _LOG.warning(
                "%s: %d text(s) held a lone surrogate escape, which no file can store as UTF-8; each was replaced by U+FFFD", name, found[0]
            )
        if found[1]:
            _LOG.warning("%s: %d entry(ies) shared a key once the surrogates were replaced and were merged into one (the last wins)", name, found[1])
    if name == _IMPORTS:
        out, left_out = _imports_shape(out)
        if left_out:
            _LOG.warning("%s: %d piece(s) of the wrong shape were left out of what is read (a save drops them from the file)", name, left_out)
    return out


#: The stores read as damaged this process whose bytes the next save keeps (R397 (b), item 31): only the imported-events store, the one
#: store that holds the user's own imports and is not rebuilt by the next pass (the verdicts, attempts and auto-import stamps are).
_KEEP_DAMAGED = frozenset({_IMPORTS})
#: Keyed by the store's PATH, not its name, so that a read under one data folder never moves a file under another; the value is the
#: file's identity when it was read (``_identity``), so that a mark noted after another thread or process replaced the file never
#: moves the healthy file that replaced it.
_READ_AS_DAMAGED: dict[Path, tuple[int, int, int]] = {}


def _identity(p: Path) -> tuple[int, int, int] | None:
    """The regular file at ``p`` as (inode, modification time in ns, size), or None when there is no regular file to keep."""
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size) if stat.S_ISREG(st.st_mode) else None


def _note_read(name: str, p: Path, ident: tuple[int, int, int] | None, *, damaged: bool) -> None:
    """Remember whether ``name`` was last read as damaged, and which file was read, so that ``_save_json`` keeps its bytes before it replaces them."""
    if name not in _KEEP_DAMAGED:
        return
    if damaged and ident is not None and ident[2] > 0:  # an empty file holds nothing to keep, and must not spend the one slot
        _READ_AS_DAMAGED[p] = ident
    else:
        _READ_AS_DAMAGED.pop(p, None)


def _load_json(name: str) -> dict:
    p = _store_path(name)
    ident = _identity(p) if name in _KEEP_DAMAGED else None  # taken BEFORE the read: if the file is replaced after it, the two differ
    try:
        raw = p.read_text("utf-8") if p.exists() else None
        data = json.loads(raw) if raw is not None else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        # (RecursionError: JSON nested too deeply for the parser, a parse failure like the others.)
        # A store that EXISTS but cannot be read reads as empty (R386, R397). For the imported-events store the next save first keeps its
        # bytes as ``<name>.damaged`` (R397 (b)); the others are rebuilt by the next pass and are replaced as before.
        # The line does not claim the replacement: where the store is a directory or the data folder is not writable, no save succeeds.
        # The class only: the store holds the user's imported events, and what is wrong with it is not worth a line of its words.
        _LOG.warning("%s exists but could not be read, so it reads as empty: %s", name, type(exc).__name__)
        # A parse failure or EIO is damage in the file; any other OSError (too many open files, a Windows sharing violation while another
        # thread replaces it) may pass and must not mark a healthy store, since the one ``.damaged`` slot is never overwritten. On Windows a
        # bad sector reaches Python through the C runtime as EACCES or EINVAL, with no ``winerror`` to tell it from a passing lock, so it is
        # not marked there: the store reads as empty and is replaced, as it was before R397 (b).
        damaged = not isinstance(exc, OSError) or exc.errno == errno.EIO
        if damaged:  # a passing error says nothing about the file: it neither marks it nor clears a mark an earlier read noted
            _note_read(name, p, ident, damaged=True)
        return {}
    out = _sanitized(name, data, what="reads as", raw=raw)
    # Read as empty although the file held something (not an object, nested too deeply, every piece of the wrong shape): the next save
    # would replace it all, so its bytes are kept too. An absent file or a real ``{}`` holds nothing to keep.
    _note_read(name, p, ident, damaged=raw is not None and not out and data != {})
    return out


def _keep_damaged_bytes(name: str, p: Path) -> None:
    """Move the store read as damaged to ``<name>.damaged`` before a save replaces it, ONCE: an existing copy is the first evidence and is never overwritten.

    The copy sits beside the store and is not in the backup list (``src/backup/artifact.py``); a synced data folder syncs it like the
    store. Nothing serialises two saves of the store, so after the copy is made its identity is compared with the file read as damaged,
    and a copy of anything else (another writer's new store, replaced in between) is undone.
    """
    read = _READ_AS_DAMAGED.pop(p, None)
    # The mark goes on every path: this save replaces the damaged bytes, whether or not they were kept, and a mark left on the new,
    # healthy file would move it at the next save.
    if read is None or _identity(p) != read:
        return  # not marked, or the file read as damaged has since been replaced (by another writer, a restore, a hand repair)
    kept = p.with_name(p.name + ".damaged")
    try:
        # A second name for the same file: it fails, never overwrites, when the name is taken, even by another process at the same moment,
        # and the save's own os.replace then gives the store's name to the new file while the copy keeps the damaged one.
        os.link(p, kept)
    except FileExistsError:
        _LOG.warning("%s was read as damaged; an earlier copy is already kept as %s and is not overwritten, so this save replaces it", name, kept.name)
        return
    except OSError:
        pass  # a drive that cannot give a file a second name (FAT, exFAT, some network shares): the check-then-move below instead
    else:
        if _identity(kept) != read:
            with suppress(OSError):
                os.unlink(kept)  # the second name went to a file that replaced the damaged one: the store keeps it, the slot stays free
            return
        _LOG.warning("%s was read as damaged; its bytes are kept as %s before this save replaces it", name, kept.name)
        return
    if kept.exists() or kept.is_symlink():
        _LOG.warning("%s was read as damaged; an earlier copy is already kept as %s and is not overwritten, so this save replaces it", name, kept.name)
        return
    try:
        os.replace(p, kept)
    except OSError as exc:
        # The save goes on, as it did before R397 (b): a copy that cannot be made never blocks the import. The class only.
        _LOG.warning("%s was read as damaged and could not be kept as %s, so this save replaces it: %s", name, kept.name, type(exc).__name__)
        return
    if _identity(kept) != read:
        with suppress(OSError):
            os.replace(kept, p)  # moved a file that replaced the damaged one: it goes back under the store's name, the slot stays free
        return
    _LOG.warning("%s was read as damaged; its bytes are kept as %s before this save replaces it", name, kept.name)


def _save_json(name: str, data: dict, *, mirror: bool = True) -> None:
    # Atomic write (temp + os.replace): these files hold the user's imported
    # events/verdicts -- a crash mid-write must never wipe them all.
    p = _store_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    # Only once the new text is written, so a failed write leaves the damaged store where it was. Where the copy is a second name (the
    # usual case) the store's name never goes missing; where it is a move, a crash between the two moves leaves no store (it reads as
    # absent) and the damaged bytes safe in ``.damaged``, while this save's new text, left in ``.tmp``, is overwritten by the next save.
    _keep_damaged_bytes(name, p)
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
        except Exception as exc:  # noqa: BLE001 - the mirror must never break the JSON write
            # ``sync_imports`` logs its own database errors; what lands here failed before it could start, and was dropped without a record (R386).
            log_failure(_LOG, "event_imports mirror could not be synced; the JSON side-file is authoritative", exc, level=logging.WARNING)


def merge_imported_store(name: str, incoming: dict) -> dict:
    """Union-merge an events/verdicts store arriving via backup restore.

    Local entries always win; incoming events are added by fingerprint with
    their sources/uids unioned (the same dedup discipline as import_feed).
    Idempotent: re-running with the same input converges. Atomic save."""
    local = _load_json(name)
    # The artifact's store arrives as parsed JSON of any shape: it gets the same treatment as a store read from disk (R397), or one
    # lone surrogate in it ends the restore at the save below and a list where an object belongs ends it at the first ``.items()``.
    incoming = _sanitized(name, incoming if incoming is not None else {}, what="arrives as")
    added = enriched = kept = 0
    if name == "calendar_feed_imports.json":
        for fam_key, bucket in incoming.items():
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
        for feed_id, verdict in incoming.items():
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


# --------------------------------------------------------------------------- #
#  The re-check LADDER (maintainer ruling 12, 2026-07-31)
#
#  "Dysfunctional calendar feeds get automated re-check MIRRORING the source
#  ladder (1 -> 2 -> 4 -> 6 months capped, append-only attempts, bounded
#  per-pass) -- never a permanent exclusion."
#
#  So this is deliberately the SAME shape as src/catalog/qualification.py's
#  re-qualification ladder, down to the cap and the 30-day month: a feed that
#  fails is re-checked after 1 month, then 2, then 4, then 6 and no further
#  apart -- the cap is what makes "never a permanent exclusion" true, exactly
#  as the capped RSS feed-backoff guarantees every feed is re-fetched.
#
#  It is symmetric on purpose: a feed that PASSES is also re-checked (at the
#  1-month rung), because a working feed can break and a stale "ok" verdict is
#  a claim about the past, not the present.
#
#  Attempts are APPEND-ONLY history (bounded per feed), never a mutable
#  counter -- the same discipline as source qualification attempts and stat
#  vintages: how a verdict was reached stays inspectable.
# --------------------------------------------------------------------------- #
_LADDER_CAP_MONTHS = 6
_MONTH_DAYS = 30  # the ruling's interval is casual ("1 to 6 months"), not calendar-exact
_MAX_ATTEMPTS_PER_FEED = 12  # bounded history: enough to read the ladder, never unbounded


def load_attempts() -> dict:
    """The append-only per-feed verification history: {feed_id: [{at, status}, ...]}
    with the NEWEST entry last."""
    return _load_json("calendar_feed_attempts.json")


def feed_backoff_months(consecutive_failures: int) -> int:
    """1st failure -> 1 month, doubling on each REPEATED failure, capped at 6
    (1 -> 2 -> 4 -> 6 -> 6 -> ...). A feed with no failures (0) also gets the
    1-month rung: re-checking a working feed is how a feed that BREAKS is
    noticed. Resetting after a success is not this function's job -- it falls
    out of :func:`consecutive_failures_from_attempts` counting only the
    TRAILING run of failures."""
    n = max(1, consecutive_failures)
    return min(2 ** (n - 1), _LADDER_CAP_MONTHS)


def feed_recheck_due_at(last_attempt_at: datetime, consecutive_failures: int) -> datetime:
    """When the next verification of this feed becomes due."""
    return last_attempt_at + timedelta(days=_MONTH_DAYS * feed_backoff_months(consecutive_failures))


def consecutive_failures_from_attempts(statuses_newest_first: list[str]) -> int:
    """PURE core: the length of the TRAILING run of non-``ok`` verdicts, counted
    from the newest attempt backwards. A single ``ok`` stops the count, so the
    ladder resets to its first rung after any success."""
    n = 0
    for status in statuses_newest_first:
        if status == "ok":
            break
        n += 1
    return n


def _parse_at(value: object) -> datetime | None:
    """Tolerant ISO parse for a stored timestamp; None when unusable.

    A corrupt/absent timestamp must never make a feed permanently un-due (the
    whole point of the ladder), so callers treat None as "due now" rather than
    as "not due".
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def select_feeds_to_verify(
    feed_ids: list[str], attempts: dict, *, now: datetime, limit: int
) -> list[str]:
    """PURE core: which feeds to verify next, most-overdue first, bounded.

    NEVER-checked feeds come first (the initial sweep across the directory),
    in catalog order; then feeds whose ladder due-date has passed, oldest
    attempt first. A feed that is not yet due is simply not selected -- it is
    never dropped from the pool, so it returns the moment its rung elapses.
    """
    never: list[str] = []
    due: list[tuple[datetime, str]] = []
    for fid in feed_ids:
        history = attempts.get(fid) or []
        if not history:
            never.append(fid)
            continue
        last_at = _parse_at((history[-1] or {}).get("at"))
        if last_at is None:
            # An unreadable timestamp is treated as due NOW, never as "not due":
            # the alternative would silently retire the feed forever.
            due.append((datetime.min.replace(tzinfo=UTC), fid))
            continue
        statuses = [str((a or {}).get("status", "")) for a in reversed(history)]
        if now >= feed_recheck_due_at(last_at, consecutive_failures_from_attempts(statuses)):
            due.append((last_at, fid))
    due.sort()
    return (never + [fid for _, fid in due])[: max(0, limit)]


def record_attempt(feed_id: str, status: str, *, at: datetime | None = None) -> dict:
    """Append one verification attempt to the bounded, append-only history."""
    attempts = load_attempts()
    history = list(attempts.get(feed_id) or [])
    history.append(
        {
            "at": (at or datetime.now(UTC)).isoformat(timespec="seconds"),
            "status": status,
        }
    )
    attempts[feed_id] = history[-_MAX_ATTEMPTS_PER_FEED:]
    _save_json("calendar_feed_attempts.json", attempts)
    return attempts[feed_id][-1]


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
    """Fetch one feed and record an honest verdict (reachable? real iCal? stale year?).

    A fetch the kill switch refused returns ``{"status": "skipped_offline", ...}`` and records NOTHING (no verdict, no ladder attempt)."""
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
        from src.ingest import kill_switch_active
        from src.ingest.fetch_verdict import classify_fetch_failure

        # Classify the WHOLE scrubbed text and cut only what is stored: the socket guard's sentence, as requests wraps it, ends past
        # 300 characters for a realistic URL, and a cut text reads as a host failure.
        full = record_text(exc)
        text = full[:300]
        # OR the switch is engaged now: a Stop that lands mid-fetch reaches here in shapes the anchored sentence match rightly refuses
        # (a robots read the refusal cut is "robots.txt ... could not be determined (unreachable)"), and a feed filed as unreachable
        # under the person's own Stop moves up the ladder. The cost is a genuine failure coinciding with a Stop going unrecorded (R320).
        if classify_fetch_failure(full) == "offline" or kill_switch_active():
            # The network kill switch refused the fetch: nothing was asked of the host, so there is no verdict about it. Storing
            # "unreachable" would blame the feed for the person's own airplane mode AND move it up the re-check ladder (a month per
            # rung); the feed stays exactly as eligible as it was, and the caller is told why nothing was checked.
            return {"checked_at": verdict["checked_at"], "status": "skipped_offline", "error": text}
        verdict["status"] = "unreachable"
        verdict["error"] = text
    pinned = feed.get("year_pinned")
    if pinned and int(pinned) < date.today().year:
        verdict["stale_year"] = int(pinned)
    verdicts = load_verdicts()
    verdicts[feed_id] = verdict
    _save_json("calendar_feed_checks.json", verdicts)
    # The verdict store keeps only the LATEST answer (what the UI shows); the
    # attempt log keeps the history the re-check ladder reads (ruling 12).
    record_attempt(feed_id, str(verdict.get("status", "unreachable")))
    return verdict


def _feed_secrets(fid: str) -> tuple[str | None, ...] | None:
    """What a log line about feed ``fid`` must not carry: its URL and any credentials in it. A fetch failure's text quotes the
    URL, so the scrubbing log sink is told to take them out (the line names the feed by id). The bundled catalogue holds no credentials today, so this is defence in depth: a catalogue
    entry that gains some must not start leaking them into a log. ``None`` when the feed cannot be looked up: then nothing is known to take out."""
    try:
        hit = feed_by_id(fid)
        if not hit:
            return None
        url = str((hit[1] or {}).get("url") or "")
        parts = urlparse(url)
        return (url or None, parts.username, parts.password)
    except Exception:  # noqa: BLE001 - a lookup that fails here must not cost the batch its next feed; the caller then logs the class only
        return None


def _log_class_only(what: str, exc_class: str) -> None:
    """The line for a failure about a feed that could not be looked up. Fail closed: with nothing known to take out of the exception's text (which quotes the URL), the line
    carries the feed id (in ``what``) and the exception CLASS only (R386)."""
    _LOG.warning("%s: %s (its text is withheld: the feed's URL could not be looked up to take it out)", what, exc_class)


def verify_due_feeds(fetcher, *, batch: int = 5) -> dict:
    """Verify a BOUNDED batch of feeds that the ladder says are due.

    This is the PROGRESSIVE verification the maintainer asked for (ruling 11):
    it rides the collect pass instead of a manual "Verify next 25" button, and
    it NEVER runs at boot -- the caller is the scheduler's housekeeping lane,
    which only exists on an online pass, so airplane-mode/zero-network boot is
    untouched by construction.

    Best-effort per feed (one bad feed never aborts the batch) and idempotent.
    robots / per-host politeness / the kill switch / the proxy all come from
    ``fetcher`` -- this adds no new fetch surface, it only schedules the
    existing verification.
    """
    ids = [f["id"] for fam in load_families() for f in fam["feeds"]]
    picked = select_feeds_to_verify(ids, load_attempts(), now=datetime.now(UTC), limit=batch)
    ok = failed = skipped_offline = 0
    for fid in picked:
        try:
            verdict = verify_feed(fetcher, fid)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not abort the batch
            # verify_feed records its own attempt for a fetch-level failure; an
            # exception here is a LOOKUP/store failure, so record the attempt
            # ourselves or this feed would never advance its rung.
            secrets = _feed_secrets(fid)
            if secrets is None:
                _log_class_only(f"calendar feed {fid}: verification raised", type(exc).__name__)
            else:
                log_failure(_LOG, f"calendar feed {fid}: verification raised", exc, *secrets, level=logging.WARNING)
            try:
                record_attempt(fid, "unreachable")
            except Exception as write_exc:  # noqa: BLE001 - and if THAT write fails too, the feed is picked again next pass: say so (R386)
                # the failed write is chained to ``exc`` (raised inside its handler), so its traceback prints the fetch failure's text too: the same secrets, or the class only
                what = f"calendar feed {fid}: the attempt could not be written, so its rung does not advance"
                if secrets is None:
                    _log_class_only(what, type(write_exc).__name__)
                else:
                    log_failure(_LOG, what, write_exc, *secrets, level=logging.WARNING)
            failed += 1
            continue
        if verdict.get("status") == "ok":
            ok += 1
        elif verdict.get("status") == "skipped_offline":
            skipped_offline += 1  # refused by the kill switch: neither checked nor failed
        else:
            failed += 1
    out = {"checked": len(picked) - skipped_offline, "ok": ok, "failed": failed, "due_pool": len(ids)}
    if skipped_offline:
        out["skipped_offline"] = skipped_offline  # present ONLY when the kill switch caused it
    return out


def verification_status() -> dict:
    """Honest progress of the progressive verification, for the UI.

    Counts only -- never a score. ``unchecked`` is the initial-sweep backlog;
    ``due_now`` is what the ladder would pick next; ``waiting`` is the rest
    (checked, not yet due). A feed is never in more than one bucket.
    """
    ids = [f["id"] for fam in load_families() for f in fam["feeds"]]
    attempts = load_attempts()
    now = datetime.now(UTC)
    unchecked = [fid for fid in ids if not (attempts.get(fid) or [])]
    due = select_feeds_to_verify(ids, attempts, now=now, limit=len(ids))
    verdicts = load_verdicts()
    return {
        "total": len(ids),
        "unchecked": len(unchecked),
        "due_now": max(0, len(due) - len(unchecked)),
        "waiting": len(ids) - len(due),
        "ok": sum(1 for fid in ids if (verdicts.get(fid) or {}).get("status") == "ok"),
        "method": (
            "Feeds are verified a few at a time on each collection pass, never at "
            "startup. A feed that fails is re-checked after 1 month, then 2, 4 and "
            "6 — capped, so it is never written off permanently."
        ),
    }


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
    a per-machine store. Returns a tally; never raises for a single bad feed. A Stop (the kill switch) ends the batch at the feed in flight:
    that feed and the rest are not counted as failed and are not stamped, so the next pass asks them first (``picked`` then exceeds
    ``imported`` + ``failed``: the difference is the feeds the Stop kept from being asked).
    """
    from src.ingest import kill_switch_active

    state = _load_json("calendar_autoimport.json")
    attempts = load_attempts()
    now = datetime.now(UTC)
    due: list[tuple[str, str]] = []
    backed_off = 0
    for fam in load_families():
        for feed in fam["feeds"]:
            # Skip feeds on a field-verified robots-disallowed host: the fetcher would
            # refuse them anyway, and including them starves the working feeds in the
            # round-robin. They stay LISTED (load_families is untouched) — only the
            # automatic import skips them.
            if urlparse(feed.get("url", "")).netloc in _AUTO_IMPORT_SKIP_HOSTS:
                continue
            # Ladder back-off (ruling 12): a feed whose LAST verification failed is
            # not re-imported every 12 h until its re-check rung elapses -- importing
            # it would just re-run the same failing fetch. Capped at 6 months, so
            # this is a delay and never an exclusion; a feed that has never been
            # verified, or whose last verdict was ok, is untouched by this branch.
            history = attempts.get(feed["id"]) or []
            if history:
                statuses = [str((a or {}).get("status", "")) for a in reversed(history)]
                fails = consecutive_failures_from_attempts(statuses)
                last_at = _parse_at((history[-1] or {}).get("at"))
                if fails and last_at is not None and now < feed_recheck_due_at(last_at, fails):
                    backed_off += 1
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
        if kill_switch_active():
            break  # a Stop: the feeds not yet asked for are neither failures nor attempts, and stay exactly as due as they were
        try:
            import_feed(fetcher, fid)
            imported += 1
        except Exception as exc:  # noqa: BLE001 - one bad feed must not abort the batch
            if kill_switch_active():
                # The Stop cut THIS feed's check, in whatever shape the error took (a Stop inside the request arrives as the raw requests
                # error, which no sentence match recognises, R298): nothing was asked of the host, so it is not a failure and, because the
                # stamp below means "this feed was checked", it is not stamped either (R293/R294). The next pass asks it first. The cost is a
                # genuine failure coinciding with a Stop going unrecorded (R320). No new tally key: a Stop is not an outcome.
                break
            secrets = _feed_secrets(fid)
            if secrets is None:
                _log_class_only(f"calendar feed {fid}: auto-import failed", type(exc).__name__)
            else:
                log_failure(_LOG, f"calendar feed {fid}: auto-import failed", exc, *secrets, level=logging.WARNING)
            failed += 1
        # Record the ATTEMPT either way, so a failing feed backs off too.
        state[fid] = now.isoformat(timespec="seconds")
    if picked:
        _save_json("calendar_autoimport.json", state)
    return {
        "due": len(due),
        "picked": len(picked),
        "imported": imported,
        "failed": failed,
        "backed_off": backed_off,  # visible, never hidden: how many the ladder deferred
    }


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
        # The progressive-verification progress, so the directory can SHOW the
        # automation that replaced its manual "Verify next 25" button (ruling 10:
        # surface what already runs, rather than add another thing to click).
        "verification": verification_status(),
    }
