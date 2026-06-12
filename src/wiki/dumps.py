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
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)
_CHUNK = 1024 * 1024  # 1 MiB
# "pages-articles-multistream" is the DEFAULT for new downloads (T14): its
# companion index makes pages readable OFFLINE by direct seek — the plain
# single-stream dump is kept for legacy files but cannot be random-accessed.
DUMP_KINDS = (
    "pages-articles",
    "pages-articles-multistream",
    "pages-articles-multistream-index",
)


def dump_filename(wiki: str, kind: str) -> str:
    """Official 'latest' filename for an edition+kind (the index is .txt, not .xml)."""
    w = (wiki or "en").strip().lower()
    suffix = ".txt.bz2" if kind.endswith("-index") else ".xml.bz2"
    return f"{w}wiki-latest-{kind}{suffix}"


def dump_url(wiki: str, kind: str = "pages-articles-multistream") -> str:
    """Official 'latest' dump URL for a language edition."""
    w = (wiki or "en").strip().lower()
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

    def __init__(self, *, base_dir: Path | None = None, http_get=None, http_head=None):
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
        # ONE download at a time (T9 download-arbitration ruling): later
        # requests become a REAL, reorderable queue instead of competing
        # threads -- the operator can put the small fr dump before the huge
        # en one (the ledger's acceptance case). Persisted with the entries.
        self.max_concurrent = 1
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
        return sum(
            1
            for k, t in self._threads.items()
            if t.is_alive() and self._entries.get(k) and self._entries[k].status == "downloading"
        )

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
        """Start the next QUEUED entry when a download slot is free (FIFO over
        the operator-reorderable queue_order)."""
        with self._lock:
            if self._downloading_now() >= self.max_concurrent:
                return
            next_key = None
            for k in list(self._order):
                e = self._entries.get(k)
                if e is None or e.status != "queued":
                    self._order.remove(k)
                    continue
                next_key = k
                break
            if next_key is None:
                return
            self._order.remove(next_key)
            entry = self._entries[next_key]
            self._save()
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
            with open(dest, mode) as fh:
                for chunk in resp.iter_content(_CHUNK):
                    if stop_event is not None and stop_event.is_set():
                        entry.status = "paused"
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
        with self._lock:
            busy = self._downloading_now() >= self.max_concurrent
            if busy:
                # Honest arbitration: a visible queue, never a competing thread.
                entry.status = "queued"
                entry.error = None
                if entry.key not in self._order:
                    self._order.append(entry.key)
                self._save()
                return entry.to_dict()
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
    import requests

    return requests.get(
        url, headers={**headers, "User-Agent": "OpenOmniscienceBot/0.4"}, stream=True, timeout=60
    )


def _default_head(url: str):
    import requests

    return requests.head(
        url, headers={"User-Agent": "OpenOmniscienceBot/0.4"}, allow_redirects=True, timeout=30
    )


_manager: DumpDownloadManager | None = None


def get_manager() -> DumpDownloadManager:
    global _manager
    if _manager is None:
        _manager = DumpDownloadManager()
    return _manager
