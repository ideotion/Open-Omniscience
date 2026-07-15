"""
Offline Wikipedia baseline downloader (per-language dumps, resumable).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A deliberately SEPARATE subsystem from live change-tracking: heavy, optional, and
opt-in per language edition. Downloads the official Wikimedia ``pages-articles``
dump (current article text) for a language to the data dir, with HTTP Range
**resume**, progress, pause and delete. Size is read from the server before you
commit (no guessed figures). The download loop takes an injected HTTP callable so
it is unit-tested on a tiny payload without the network.

Honest scope: this fetches the current-text dump (enwiki ≈ tens of GB; most
editions far smaller). Full edit history (terabytes) is out of scope.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)
_CHUNK = 1024 * 1024  # 1 MiB
# Parallel dump downloads (maintainer 2026-06-13). Dumps write FILES, not the
# DB, so concurrency has no single-writer contention; over Tor each download
# rides its own circuit (per-stream SOCKS isolation) so aggregate throughput
# multiplies. Bounded + conservative because dumps share ONE host
# (dumps.wikimedia.org) and per-host politeness is never traded for speed; a
# few parallel streams is normal for a bulk dump mirror. Operator-tunable via the
# power-profile knob ``dump_concurrency()`` (OO_DUMP_CONCURRENCY override, else the active
# profile; Optimized = 3, byte-identical to today), read when a manager is constructed.
# "pages-articles-multistream" is the DEFAULT for new downloads (T14): its
# companion index makes pages readable OFFLINE by direct seek — the plain
# single-stream dump is kept for legacy files but cannot be random-accessed.
DUMP_KINDS = (
    "pages-articles",
    "pages-articles-multistream",
    "pages-articles-multistream-index",
)


# A Wikipedia edition code is lowercase alphanumeric segments joined by single
# hyphens (en, fr, simple, zh-min-nan, bat-smg, be-x-old, zh-classical). This
# deliberately allows MORE than the suggested ^[a-z]{2,3}(-[a-z]+)?$ (which would
# wrongly reject "simple" and multi-hyphen editions) while still forbidding the
# only thing that matters for safety: anything that could escape the dumps
# directory. The code flows into a filesystem path (dump_filename ->
# data_dir()/wiki_dumps/<code>wiki-...) AND into dump_url's path, so a "../",
# "/", "\\", whitespace or "." would be a path-traversal vector — all rejected.
_WIKI_CODE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_wiki_code(wiki: str) -> str:
    """Normalise + validate a Wikipedia edition code; raise on anything unsafe.

    Returns the lowercased, stripped code. Raises ``ValueError`` for empty input
    or any code that is not pure ``[a-z0-9]`` segments joined by single hyphens —
    blocking ``../`` / ``/`` / ``\\`` path-traversal before the value can reach a
    filesystem path or a fetch URL. The API converts the ValueError to HTTP 400.
    """
    w = (wiki or "").strip().lower()
    if not w or len(w) > 32 or not _WIKI_CODE_RE.match(w):
        raise ValueError(f"invalid Wikipedia edition code: {wiki!r}")
    return w


def dump_filename(wiki: str, kind: str) -> str:
    """Official 'latest' filename for an edition+kind (the index is .txt, not .xml)."""
    w = validate_wiki_code(wiki)
    suffix = ".txt.bz2" if kind.endswith("-index") else ".xml.bz2"
    return f"{w}wiki-latest-{kind}{suffix}"


def dump_url(wiki: str, kind: str = "pages-articles-multistream") -> str:
    """Official 'latest' dump URL for a language edition."""
    w = validate_wiki_code(wiki or "en")
    return f"https://dumps.wikimedia.org/{w}wiki/latest/{dump_filename(w, kind)}"


@dataclass
class DownloadEntry:
    key: str
    wiki: str
    kind: str
    url: str
    dest: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    status: str = "queued"  # queued | downloading | paused | done | error
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["percent"] = (
            round(100.0 * self.downloaded_bytes / self.total_bytes, 1) if self.total_bytes else 0.0
        )
        return d


class DumpDownloadManager:
    """Manages resumable dump downloads with persisted state under the data dir."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        http_get=None,
        http_head=None,
        max_concurrent: int | None = None,
    ):
        from src.paths import data_dir

        self.base_dir = Path(base_dir) if base_dir else (data_dir() / "wiki_dumps")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "downloads.json"
        self._http_get = http_get
        self._http_head = http_head
        self._entries: dict[str, DownloadEntry] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()  # state-file writes only (see _save)
        # Up to ``max_concurrent`` downloads run in PARALLEL (maintainer
        # 2026-06-13). When MORE dumps are requested than the capacity, the
        # excess becomes a REAL, reorderable queue (the T9 fr-before-en
        # acceptance case still holds) -- parallelism adds speed without losing
        # prioritisation. Persisted with the entries.
        from src.config.power_profiles import dump_concurrency

        self.max_concurrent = (
            max_concurrent if max_concurrent and max_concurrent > 0 else dump_concurrency()
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
                    self._entries[k] = DownloadEntry(
                        **{f: v[f] for f in DownloadEntry.__annotations__ if f in v}
                    )
            except Exception:  # noqa: BLE001 - a bad state file must not crash startup
                _LOG.warning("wiki dumps state unreadable; ignoring", exc_info=True)
        # No worker thread survives a process restart, so a persisted
        # "downloading" status is stale -- demote it to "paused" (the partial
        # file is kept and resumable) rather than leaving a phantom that would
        # block a parallel slot forever. Honest state after a restart; nothing
        # re-fetches here (zero-network boot stands).
        for e in self._entries.values():
            if e.status == "downloading":
                e.status = "paused"

    def _save(self) -> None:
        # Serialized: the worker thread saves progress while the API thread
        # saves queue changes — both used ONE tmp path, so an interleaved
        # write/replace pair crashed with FileNotFoundError (caught by CI on
        # test_queue_order_survives_a_reload). The snapshot is taken under the
        # same lock so each written state file is internally consistent.
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
        # Count by STATUS, not thread liveness: a slot is claimed (status set to
        # "downloading" under the lock) the instant it is selected, BEFORE its
        # thread starts -- so concurrent _pump/start calls can never over-launch
        # past max_concurrent. _download always reaches a terminal status
        # (done/error/paused), and _load demotes any stale "downloading", so this
        # never sticks.
        return sum(1 for e in self._entries.values() if e.status == "downloading")

    def _launch(self, entry: DownloadEntry) -> None:
        stop = threading.Event()
        self._stops[entry.key] = stop

        def _run() -> None:
            self._download(entry, stop)
            self._pump()  # a finished/paused/errored slot frees the queue

        t = threading.Thread(target=_run, name=f"oo-dump-{entry.key}", daemon=True)
        self._threads[entry.key] = t
        t.start()

    def _pump(self) -> None:
        """Start QUEUED entries until ``max_concurrent`` are in flight, FIFO over
        the operator-reorderable queue. PARALLEL by design: each selected entry
        claims its slot (status -> "downloading") UNDER THE LOCK before launch, so
        two concurrent pumps can never exceed the capacity; the launch itself runs
        outside the lock."""
        to_launch: list[DownloadEntry] = []
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
        """Reorder the QUEUED downloads (the fr-before-en acceptance case).
        Unknown/non-queued keys are ignored; queued keys missing from the
        request keep their relative order at the tail. Returns the new order."""
        with self._lock:
            queued = [k for k in self._order if self._entries.get(k) and self._entries[k].status == "queued"]
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
            return [e.to_dict() for e in self._entries.values()]

    # -- size probe -------------------------------------------------------- #

    def probe_size(self, wiki: str, kind: str = "pages-articles") -> int | None:
        """Return the server-reported size in bytes (HEAD), or None."""
        head = self._http_head or _default_head
        try:
            resp = head(dump_url(wiki, kind))
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
        except Exception:  # noqa: BLE001 - size is best-effort
            return None

    # -- download ---------------------------------------------------------- #

    def _entry_for(self, wiki: str, kind: str) -> DownloadEntry:
        key = f"{wiki.lower()}:{kind}"
        e = self._entries.get(key)
        if e is None:
            dest = self.base_dir / dump_filename(wiki, kind)
            e = DownloadEntry(
                key=key, wiki=wiki.lower(), kind=kind, url=dump_url(wiki, kind), dest=str(dest)
            )
            self._entries[key] = e
            self._save()
        return e

    def _download(
        self, entry: DownloadEntry, stop_event: threading.Event | None = None
    ) -> DownloadEntry:
        """Run the (resumable) download loop. Synchronous; used by start() in a thread."""
        http_get = self._http_get or _default_get
        dest = Path(entry.dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        resume = dest.stat().st_size if dest.exists() else 0
        headers = {"Range": f"bytes={resume}-"} if resume else {}
        try:
            resp = http_get(entry.url, headers)
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
                    # Pause (resumable) on an explicit Pause OR when airplane mode
                    # engages MID-DOWNLOAD: the kill switch must halt an already-open
                    # file download, not only refuse new fetches (field test 2026-06-19
                    # #36 — downloads kept running after airplane). A partial file is
                    # left on disk; resume continues it via an HTTP Range request.
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
            _LOG.warning("dump download failed for %s", entry.key, exc_info=True)
        return entry

    def start(self, wiki: str, kind: str = "pages-articles") -> dict:
        """Begin or resume a download in a background thread."""
        if kind not in DUMP_KINDS:
            raise ValueError(f"unknown dump kind {kind!r}; use one of {DUMP_KINDS}")
        entry = self._entry_for(wiki, kind)
        if self._threads.get(entry.key) and self._threads[entry.key].is_alive():
            return entry.to_dict()
        from src.ingest import kill_switch_active

        if kill_switch_active():
            # Airplane mode: never open a socket. Present as PAUSED (resumable), never a
            # cryptic "error" (field test 2026-06-19 #36/#41). The UI's resume re-prompts
            # the go-online consent (ensureOnline) before calling start() again.
            with self._lock:
                if entry.key in self._order:
                    self._order.remove(entry.key)
                entry.status = "paused"
                entry.error = None
                self._save()
            return entry.to_dict()
        with self._lock:
            if self._downloading_now() >= self.max_concurrent:
                # Capacity full: a visible, reorderable queue, never a competing
                # thread (T9 arbitration). The excess waits its turn.
                entry.status = "queued"
                entry.error = None
                if entry.key not in self._order:
                    self._order.append(entry.key)
                self._save()
                return entry.to_dict()
            # Claim the slot atomically (status set under the lock) so a rapid
            # second start() cannot race past max_concurrent before the worker
            # thread marks it downloading.
            entry.status = "downloading"
            entry.error = None
            self._save()
        self._launch(entry)
        return entry.to_dict()

    def pause(self, key: str) -> bool:
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
        """Resume a paused/failed download by re-entering the queue / starting a
        slot — start() continues the partial file from ``downloaded_bytes`` via an
        HTTP Range request. Returns the entry dict, or None for an unknown key."""
        with self._lock:
            e = self._entries.get(key)
        if e is None:
            return None
        return self.start(e.wiki, e.kind)

    def delete(self, key: str) -> bool:
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
    # Through the guarded factory: a multi-GB dump download now refuses while the
    # kill switch is engaged and rides the protected-mode proxy (no clearnet
    # leak). The honest versioned UA comes from the session; ``headers`` carries
    # only request-specific fields (e.g. a Range header for resume). The URL is
    # the isolation token, so parallel downloads of DIFFERENT dumps each get
    # their own Tor circuit (over a SOCKS proxy) instead of sharing one.
    from src.safety.fetcher import guarded_session

    return guarded_session(isolation_token=url).get(
        url, headers=headers, stream=True, timeout=60
    )


def _default_head(url: str):
    from src.safety.fetcher import guarded_session

    return guarded_session(isolation_token=url).head(url, allow_redirects=True, timeout=30)


_manager: DumpDownloadManager | None = None


def get_manager() -> DumpDownloadManager:
    global _manager
    if _manager is None:
        _manager = DumpDownloadManager()
    return _manager
