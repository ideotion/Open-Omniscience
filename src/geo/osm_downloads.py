"""
Offline OSM region download manager (Group M — offline mapping).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Manages resumable downloads of the bundled-catalog OSM region extracts
(``src.geo.osm_regions``) exactly like the Wikipedia dumps subsystem
(``src.wiki.dumps``): a persisted, operator-reorderable queue; up to
``max_concurrent`` downloads in PARALLEL (these write FILES, not the DB — no
single-writer contention); resume via HTTP Range; pause/resume/cancel. Every
fetch rides the GUARDED socket factory, so:

  * the network KILL SWITCH (airplane mode) refuses a download outright
    (degrade loudly — never a silent clearnet egress, UI invariant #14);
  * the protected-mode proxy (Tor) is honoured, and each download's URL is its
    stream-isolation token, so parallel downloads of DIFFERENT regions ride
    DIFFERENT Tor circuits (aggregate speedup instead of one shared circuit).

This is a SEPARATE, self-contained manager (the proven wiki one stays untouched):
an OSM region has ONE artifact (the ``.osm.pbf``), so the key is simply the region
code — there is no per-region "kind" dimension. No network happens at import or
boot (zero-network boot stands); a download only starts on an explicit, consented
operator action.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.geo.osm_regions import estimate_bytes, get_region, is_valid_code
from src.ingest.segmented_download import (
    choose_mirror,
    default_fetch_segment,
    default_mirror_probe,
    segmented_fetch,
)

_LOG = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1 MiB

# OSM extracts are large (continents are multi-GB, the planet ~72 GB), so the
# default parallelism is conservative; raise via OO_OSM_CONCURRENCY. Parallel
# downloads each ride their own Tor circuit (per-URL stream isolation), so the
# excess still QUEUES reorderably rather than over-launching. Per-host politeness
# (Geofabrik / the planet mirror) is enforced by the guarded session, never
# traded for speed.
_DEFAULT_OSM_CONCURRENCY = max(1, int(os.getenv("OO_OSM_CONCURRENCY", "2")))

# Mirrors used by the URL builder. Geofabrik serves the continent extracts; the
# whole-planet file is NOT a Geofabrik product, it lives on the OSM planet mirror.
GEOFABRIK_BASE = "https://download.geofabrik.de"
PLANET_URL = "https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf"


def osm_filename(code: str) -> str:
    """Local filename for a region's compressed extract."""
    return f"{(code or '').strip().lower()}-latest.osm.pbf"


def osm_download_url(code: str) -> str:
    """Mirror URL for a region code.

    ``is_valid_code`` is the path-safety gate (lowercase letters joined by single
    hyphens, ``^[a-z]+(-[a-z]+)*$``), so a code can never escape into a path/URL
    it shouldn't — Geofabrik country sub-paths (which contain ``/``) are rejected
    here by design (top-level extracts only at this slice).
    """
    c = (code or "").strip().lower()
    if not is_valid_code(c):
        raise ValueError(f"invalid OSM region code {code!r}")
    if c == "planet":
        return PLANET_URL
    return f"{GEOFABRIK_BASE}/{c}-latest.osm.pbf"


@dataclass
class OsmDownloadEntry:
    key: str  # the region code (one artifact per region)
    code: str
    name: str
    url: str
    dest: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    status: str = "queued"  # queued | downloading | paused | done | error
    error: str | None = None
    # C11 (2026-07-24 throughput brief, S-C): operator/config-supplied acceleration
    # inputs — EMPTY for every real catalog entry today (no verified Geofabrik
    # mirror list or per-file checksum could be confirmed from this sandbox; see
    # src.ingest.segmented_download's module docstring). Dormant by construction:
    # blank fields fall straight through to the proven single-stream path below.
    mirrors: list[str] = field(default_factory=list)
    expected_sha256: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["percent"] = (
            round(100.0 * self.downloaded_bytes / self.total_bytes, 1) if self.total_bytes else 0.0
        )
        # The catalog estimate (zero-network) so the UI can show an expected size
        # BEFORE the real Content-Length arrives — labelled an estimate, never
        # conflated with the measured total_bytes (which stays 0 until the fetch).
        d["size_estimate_bytes"] = estimate_bytes(self.code)
        return d


class OsmDownloadManager:
    """Resumable OSM region downloads with persisted, reorderable queue state."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        http_get=None,
        http_head=None,
        max_concurrent: int | None = None,
        mirror_probe=None,
        fetch_segment=None,
        segment_min_bytes: int | None = None,
    ):
        from src.paths import data_dir

        self.base_dir = Path(base_dir) if base_dir else (data_dir() / "osm_regions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "downloads.json"
        self._http_get = http_get
        self._http_head = http_head
        # C11: injectable for tests; the real defaults route through the guarded
        # factory with per-segment/per-mirror isolation tokens (never used unless
        # an entry actually carries mirrors/expected_sha256 — see OsmDownloadEntry).
        self._mirror_probe = mirror_probe or default_mirror_probe
        self._fetch_segment = fetch_segment or default_fetch_segment
        self._segment_min_bytes = (
            segment_min_bytes if segment_min_bytes and segment_min_bytes > 0 else 1024 * 1024
        )
        self._entries: dict[str, OsmDownloadEntry] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()  # state-file writes only (see _save)
        self.max_concurrent = (
            max_concurrent if max_concurrent and max_concurrent > 0 else _DEFAULT_OSM_CONCURRENCY
        )
        self._order: list[str] = []
        self._load()

    # -- state ------------------------------------------------------------- #

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text("utf-8"))
                if isinstance(raw, dict) and "entries" in raw:
                    self._order = [k for k in raw.get("queue_order", []) if isinstance(k, str)]
                    raw = raw["entries"]
                for k, v in raw.items():
                    self._entries[k] = OsmDownloadEntry(
                        **{f: v[f] for f in OsmDownloadEntry.__annotations__ if f in v}
                    )
            except Exception:  # noqa: BLE001 - a bad state file must not crash startup
                _LOG.warning("OSM downloads state unreadable; ignoring", exc_info=True)
        # No worker thread survives a process restart, so a persisted
        # "downloading" status is stale -- demote it to "paused" (the partial file
        # is kept and resumable) rather than leaving a phantom blocking a slot.
        for e in self._entries.values():
            if e.status == "downloading":
                e.status = "paused"

    def _save(self) -> None:
        # Serialized under one lock so each written state file is internally
        # consistent (the worker thread and the API thread both write it).
        with self._save_lock:
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "entries": {k: asdict(e) for k, e in self._entries.items()},
                        "queue_order": list(self._order),
                    },
                    indent=2,
                ),
                "utf-8",
            )
            tmp.replace(self.state_path)

    def _downloading_now(self) -> int:
        # Count by STATUS, not thread liveness: a slot is claimed (status set under
        # the lock) the instant it is selected, so concurrent _pump/start calls can
        # never over-launch past max_concurrent.
        return sum(1 for e in self._entries.values() if e.status == "downloading")

    def _launch(self, entry: OsmDownloadEntry) -> None:
        stop = threading.Event()
        self._stops[entry.key] = stop

        def _run() -> None:
            self._download(entry, stop)
            self._pump()  # a finished/paused/errored slot frees the queue

        t = threading.Thread(target=_run, name=f"oo-osm-{entry.key}", daemon=True)
        self._threads[entry.key] = t
        t.start()

    def _pump(self) -> None:
        """Start QUEUED entries until ``max_concurrent`` are in flight, FIFO over
        the operator-reorderable queue. Each selected entry claims its slot (status
        -> "downloading") UNDER THE LOCK before launch, so two concurrent pumps can
        never exceed capacity; the launch itself runs outside the lock."""
        to_launch: list[OsmDownloadEntry] = []
        with self._lock:
            free = self.max_concurrent - self._downloading_now()
            for k in list(self._order):
                if free <= 0:
                    break
                e = self._entries.get(k)
                if e is None or e.status != "queued":
                    self._order.remove(k)
                    continue
                self._order.remove(k)
                e.status = "downloading"  # claim the slot atomically
                to_launch.append(e)
                free -= 1
            if to_launch:
                self._save()
        for entry in to_launch:
            self._launch(entry)

    def reorder(self, keys: list[str]) -> list[str]:
        """Reorder the QUEUED downloads (the same prioritisation control as the
        wiki dump queue). Unknown/non-queued keys are ignored; queued keys missing
        from the request keep their relative order at the tail. Returns the order."""
        with self._lock:
            queued = [
                k for k in self._order
                if self._entries.get(k) and self._entries[k].status == "queued"
            ]
            wanted = [k for k in keys if k in queued]
            tail = [k for k in queued if k not in wanted]
            self._order = wanted + tail
            self._save()
            return list(self._order)

    def queue_order(self) -> list[str]:
        with self._lock:
            return [
                k for k in self._order
                if self._entries.get(k) and self._entries[k].status == "queued"
            ]

    def list(self) -> list[dict]:
        with self._lock:
            order = [
                k for k in self._order
                if self._entries.get(k) and self._entries[k].status == "queued"
            ]
            out = []
            for e in self._entries.values():
                d = e.to_dict()
                # Queue position lets the Settings list render + reorder the queue,
                # the same prioritisation control the task manager already offers.
                d["queue_position"] = (order.index(e.key) + 1) if e.key in order else None
                out.append(d)
            return out

    # -- size probe -------------------------------------------------------- #

    def probe_size(self, code: str) -> int | None:
        """Server-reported size in bytes (HEAD), or None. A NETWORK call through
        the guarded factory (kill switch / proxy honoured); the catalog estimate
        is the zero-network default shown without this."""
        return self._probe_url_size(osm_download_url(code))

    def _probe_url_size(self, url: str) -> int | None:
        head = self._http_head or _default_head
        try:
            resp = head(url)
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
        except Exception:  # noqa: BLE001 - size is best-effort
            return None

    # -- download ---------------------------------------------------------- #

    def _entry_for(
        self,
        code: str,
        name: str | None = None,
        *,
        mirrors: Sequence[str] | None = None,
        expected_sha256: str = "",
    ) -> OsmDownloadEntry:
        key = (code or "").strip().lower()
        e = self._entries.get(key)
        if e is None:
            region = get_region(key)
            dest = self.base_dir / osm_filename(key)
            e = OsmDownloadEntry(
                key=key,
                code=key,
                name=name or (region.name if region else key),
                url=osm_download_url(key),  # raises on a path-unsafe code
                dest=str(dest),
                mirrors=list(mirrors or []),
                expected_sha256=expected_sha256,
            )
            self._entries[key] = e
            self._save()
        return e

    def _download_segmented(self, entry: OsmDownloadEntry, fetch_url: str, dest: Path) -> bool:
        """C11: attempt a segmented multi-circuit fetch. Returns True when it
        engaged and the file is written + entry updated; False when it declines
        (no size known, too large, or too small to split — the caller falls back
        to the proven sequential path). RAISES when it engaged but
        ``reassemble``'s integrity check failed — a corrupt/short segment must
        surface as a genuine download error, never a silently-downgraded
        fallback that could mask a tampered fetch."""
        total = self._probe_url_size(fetch_url) or entry.total_bytes
        if not total:
            return False
        data = segmented_fetch(
            fetch_url,
            total_bytes=total,
            expected_sha256=entry.expected_sha256,
            fetch_segment=self._fetch_segment,
            min_seg=self._segment_min_bytes,
        )
        if data is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        entry.total_bytes = len(data)
        entry.downloaded_bytes = len(data)
        entry.status = "done"
        entry.error = None
        self._save()
        return True

    def _download(
        self, entry: OsmDownloadEntry, stop_event: threading.Event | None = None
    ) -> OsmDownloadEntry:
        """Run the (resumable) download loop. Synchronous; used by start() in a thread."""
        http_get = self._http_get or _default_get
        dest = Path(entry.dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        resume = dest.stat().st_size if dest.exists() else 0

        # C11 (2026-07-24 throughput brief, S-C): pick the fastest REACHABLE
        # mirror for THIS attempt — a no-op (fetch_url stays entry.url) when
        # entry.mirrors is empty, which is every real catalog entry today (see
        # src.ingest.segmented_download's module docstring).
        fetch_url = entry.url
        if entry.mirrors:
            try:
                fetch_url = choose_mirror(entry.url, entry.mirrors, probe=self._mirror_probe)
            except Exception:  # noqa: BLE001 - mirror selection is best-effort
                fetch_url = entry.url

        try:
            # A segmented multi-circuit fetch ONLY on a fresh start (no partial
            # file — segmented+resume semantics are out of scope) with a
            # verified whole-file checksum configured (dormant by default).
            if (
                resume == 0
                and entry.expected_sha256
                and self._download_segmented(entry, fetch_url, dest)
            ):
                return entry

            headers = {"Range": f"bytes={resume}-"} if resume else {}
            resp = http_get(fetch_url, headers)
            resp.raise_for_status()
            status_code = getattr(resp, "status_code", 200)
            cl = int(resp.headers.get("Content-Length", 0) or 0)
            if status_code == 206:  # partial -> append
                mode, entry.total_bytes = "ab", resume + cl
            else:  # full -> restart
                resume, mode, entry.total_bytes = 0, "wb", (cl or entry.total_bytes)
            entry.downloaded_bytes = resume
            entry.status = "downloading"
            entry.error = None
            self._save()
            from src.ingest import kill_switch_active

            with open(dest, mode) as fh:
                for chunk in resp.iter_content(_CHUNK):
                    # Pause (resumable) on Pause OR when airplane mode engages MID-DOWNLOAD
                    # — the kill switch must halt an open file download, not only refuse new
                    # fetches (field test 2026-06-19 #36). Resume continues via HTTP Range.
                    if (stop_event is not None and stop_event.is_set()) or kill_switch_active():
                        entry.status = "paused"
                        entry.error = None
                        self._save()
                        return entry
                    if not chunk:
                        continue
                    fh.write(chunk)
                    entry.downloaded_bytes += len(chunk)
            entry.status = "done"
            self._save()
        except Exception as exc:  # noqa: BLE001 - record, never crash the worker thread
            entry.status = "error"
            entry.error = str(exc)
            self._save()
            _LOG.warning("OSM region download failed for %s", entry.key, exc_info=True)
        return entry

    def start(
        self,
        code: str,
        name: str | None = None,
        *,
        mirrors: Sequence[str] | None = None,
        expected_sha256: str = "",
    ) -> dict:
        """Begin or resume a region download in a background thread.

        Raises ``ValueError`` for a path-unsafe code (via the URL builder). When
        capacity is full the entry QUEUES (reorderable) instead of over-launching.
        ``mirrors``/``expected_sha256`` (C11, keyword-only, both default empty —
        byte-identical to today) are ONLY applied when a NEW entry is created.
        """
        entry = self._entry_for(code, name, mirrors=mirrors, expected_sha256=expected_sha256)
        if self._threads.get(entry.key) and self._threads[entry.key].is_alive():
            return entry.to_dict()
        from src.ingest import kill_switch_active

        if kill_switch_active():
            # Airplane mode: never open a socket. Present as PAUSED (resumable), never a
            # cryptic "error" (field test 2026-06-19 #36/#41); resume re-prompts go-online.
            with self._lock:
                if entry.key in self._order:
                    self._order.remove(entry.key)
                entry.status = "paused"
                entry.error = None
                self._save()
            return entry.to_dict()
        with self._lock:
            if self._downloading_now() >= self.max_concurrent:
                entry.status = "queued"
                entry.error = None
                if entry.key not in self._order:
                    self._order.append(entry.key)
                self._save()
                return entry.to_dict()
            entry.status = "downloading"  # claim the slot atomically
            entry.error = None
            self._save()
        self._launch(entry)
        return entry.to_dict()

    def pause(self, key: str) -> bool:
        key = (key or "").strip().lower()
        with self._lock:
            e = self._entries.get(key)
            if e is not None and e.status == "queued":
                if key in self._order:
                    self._order.remove(key)
                e.status = "paused"
                self._save()
                return True
        stop = self._stops.get(key)
        if stop:
            stop.set()
            return True
        return False

    def resume(self, key: str) -> dict | None:
        """Resume a paused/failed region download via start() (continues the
        partial file from ``downloaded_bytes``). Returns the entry dict, or None
        for an unknown key."""
        key = (key or "").strip().lower()
        with self._lock:
            e = self._entries.get(key)
        if e is None:
            return None
        return self.start(e.code, e.name)

    def delete(self, key: str) -> bool:
        key = (key or "").strip().lower()
        self.pause(key)
        with self._lock:
            if key in self._order:
                self._order.remove(key)
            entry = self._entries.pop(key, None)
        if entry is None:
            return False
        with contextlib.suppress(OSError):
            Path(entry.dest).unlink(missing_ok=True)
        self._save()
        return True


def _default_get(url: str, headers: dict):
    # Through the guarded factory: refuses while the kill switch is engaged and
    # rides the protected-mode proxy (no clearnet leak). The honest versioned UA
    # comes from the session; ``headers`` carries only request-specific fields
    # (e.g. a Range header for resume). The URL is the isolation token, so parallel
    # downloads of DIFFERENT regions each get their own Tor circuit.
    from src.safety.fetcher import guarded_session

    return guarded_session(isolation_token=url).get(
        url, headers=headers, stream=True, timeout=60
    )


def _default_head(url: str):
    from src.safety.fetcher import guarded_session

    return guarded_session(isolation_token=url).head(url, allow_redirects=True, timeout=30)


_manager: OsmDownloadManager | None = None


def get_manager() -> OsmDownloadManager:
    global _manager
    if _manager is None:
        _manager = OsmDownloadManager()
    return _manager
